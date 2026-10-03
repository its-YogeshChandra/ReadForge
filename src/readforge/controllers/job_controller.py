"""Job lifecycle status for upload clients."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from readforge.database import SessionLocal
from readforge.database.schema import Job
from readforge.utils.redis_utils import get_job


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
    try:
        async with SessionLocal() as session:
            database_job = await session.get(Job, job_id)
    except SQLAlchemyError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Job status database is unavailable",
        ) from error

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
        queued_job = await get_job(str(job_id))
    except RedisError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Job queue is unavailable",
        ) from error

    if queued_job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job was not found")

    return JobStatusResponse(
        job_id=job_id,
        status="queued",
        created_at=queued_job.created_at,
    )
