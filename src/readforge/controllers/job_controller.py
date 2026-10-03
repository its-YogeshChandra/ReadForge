"""Job lifecycle status for upload clients."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from readforge.database import SessionLocal
from readforge.database.schema import Job
from readforge.utils.redis_utils import (
    get_job,
    get_job_status as get_redis_job_status,
    get_redis_client,
    job_events_channel,
)
from readforge.utils.tracing import trace


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    document_id: UUID | None = None
    status: Literal["queued", "processing", "completed", "failed"]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


async def job_status(job_id: UUID) -> JobStatusResponse:
    """Read the durable worker state, falling back to the queued Redis trace."""
    database_error: SQLAlchemyError | None = None
    try:
        async with SessionLocal() as session:
            database_job = await session.get(Job, job_id)
    except SQLAlchemyError as error:
        database_error = error
        database_job = None

    if database_job is not None:
        return JobStatusResponse(
            job_id=database_job.id,
            document_id=database_job.document_id,
            status=database_job.status,
            created_at=database_job.created_at,
            started_at=database_job.started_at,
            completed_at=database_job.completed_at,
            error_message=database_job.error_message,
        )

    try:
        redis_status = await get_redis_job_status(str(job_id))
        if redis_status is not None:
            return JobStatusResponse.model_validate(redis_status.model_dump())
        queued_job = await get_job(str(job_id))
    except RedisError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Job queue is unavailable",
        ) from error

    if queued_job is None:
        if database_error is not None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Job status database is unavailable",
            ) from database_error
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job was not found")

    return JobStatusResponse(
        job_id=job_id,
        status="queued",
        created_at=queued_job.created_at,
    )


async def job_events(job_id: UUID) -> StreamingResponse:
    """Stream retained and live job transitions over server-sent events."""
    pubsub = get_redis_client().pubsub()
    channel = job_events_channel(str(job_id))
    try:
        await pubsub.subscribe(channel)
        current = await job_status(job_id)
    except Exception:
        await pubsub.aclose()
        raise

    async def stream():
        trace(job_id, "job_events.connected")
        try:
            yield f"data:{current.model_dump_json()}\n\n"
            if current.status in {"completed", "failed"}:
                return
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=15,
                )
                if message is None:
                    yield ":keep-alive\n\n"
                    continue
                payload = message.get("data")
                if not isinstance(payload, (str, bytes, bytearray)):
                    continue
                event = JobStatusResponse.model_validate_json(payload)
                yield f"data:{event.model_dump_json()}\n\n"
                if event.status in {"completed", "failed"}:
                    return
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            trace(job_id, "job_events.disconnected")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
