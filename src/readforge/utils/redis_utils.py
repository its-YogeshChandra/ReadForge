"""Redis-backed FIFO queue utilities for document-processing jobs."""

from datetime import UTC, datetime
import os
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

load_dotenv()

# tatal time limit for job
JOB_TTL_SECONDS = 2 * 60 * 60

_redis_client: Redis | None = None

_CREATE_JOB_SCRIPT = """
local existing_payload = redis.call("GET", KEYS[1])
if existing_payload then
    return existing_payload
end

redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
redis.call("SET", KEYS[2], ARGV[1], "EX", ARGV[2])
redis.call("RPUSH", KEYS[3], ARGV[3])
redis.call("EXPIRE", KEYS[3], ARGV[2])
redis.call("SET", KEYS[4], ARGV[4], "EX", ARGV[2])
redis.call("PUBLISH", KEYS[5], ARGV[4])
return ARGV[1]
"""


# create redis job request
class RedisJobRequest(BaseModel):
    """Data required to add a document-processing job to Redis."""

    model_config = ConfigDict(extra="forbid", frozen=True)  # forbid unexpected fields
    file_name: str = Field(min_length=1)
    presigned_url: str = Field(min_length=1)
    idem_key: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class RedisJob(RedisJobRequest):
    """A queued job, including its generated identifier and creation time."""

    job_id: str
    created_at: datetime


class RedisJobStatus(BaseModel):
    """Latest job state sent to upload clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str
    document_id: str | None = None
    status: Literal["queued", "processing", "completed", "failed"]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class DeadLetterJob(BaseModel):
    """A failed job retained for later inspection or replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    job: RedisJob
    reason: str = Field(min_length=1)
    failed_at: datetime


def get_redis_client() -> Redis:
    """Return the shared async Redis client.

    ``REDIS_URL`` defaults to a local Redis database for development.
    """
    global _redis_client

    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = Redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def _key_namespace() -> str:
    return os.getenv("REDIS_KEY_NAMESPACE", "readforge")


def _queue_key() -> str:
    return f"{_key_namespace()}:{{jobs}}:queue"


def _job_key(job_id: str) -> str:
    return f"{_key_namespace()}:{{jobs}}:job:{job_id}"


def job_status_key(job_id: str) -> str:
    return f"{_key_namespace()}:{{jobs}}:status:{job_id}"


def job_events_channel(job_id: str) -> str:
    return f"{_key_namespace()}:{{jobs}}:events:{job_id}"


def _dead_letter_queue_key() -> str:
    return f"{_key_namespace()}:{{jobs}}:dead-letter"


def _idempotency_key(idem_key: str) -> str:
    return f"{_key_namespace()}:{{jobs}}:idempotency:{idem_key}"


async def create_job(request: RedisJobRequest) -> RedisJob:
    """Create a two-hour job and append it to the FIFO queue.

    Reusing an idempotency key within the two-hour window returns the original
    job without adding a duplicate queue entry.
    """
    job = RedisJob(
        **request.model_dump(),
        job_id=str(uuid4()),
        created_at=datetime.now(UTC),
    )
    payload = job.model_dump_json()
    status_payload = RedisJobStatus(
        job_id=job.job_id,
        status="queued",
        created_at=job.created_at,
    ).model_dump_json()

    stored_payload = await get_redis_client().eval(
        _CREATE_JOB_SCRIPT,
        5,
        _idempotency_key(request.idem_key),
        _job_key(job.job_id),
        _queue_key(),
        job_status_key(job.job_id),
        job_events_channel(job.job_id),
        payload,
        JOB_TTL_SECONDS,
        job.job_id,
        status_payload,
    )

    if not isinstance(stored_payload, (str, bytes, bytearray)):
        raise RuntimeError("Redis returned an invalid job payload")

    return RedisJob.model_validate_json(stored_payload)


async def get_job(job_id: str) -> RedisJob | None:
    """Return a queued job while its Redis trace is retained."""
    payload = await get_redis_client().get(_job_key(job_id))
    if not isinstance(payload, (str, bytes, bytearray)):
        return None
    return RedisJob.model_validate_json(payload)


async def get_job_status(job_id: str) -> RedisJobStatus | None:
    """Return the latest retained status for reconnecting clients."""
    payload = await get_redis_client().get(job_status_key(job_id))
    if not isinstance(payload, (str, bytes, bytearray)):
        return None
    return RedisJobStatus.model_validate_json(payload)


async def publish_job_status(status: RedisJobStatus) -> None:
    """Persist and publish one job transition atomically."""
    payload = status.model_dump_json()
    async with get_redis_client().pipeline(transaction=True) as pipeline:
        pipeline.set(job_status_key(status.job_id), payload, ex=JOB_TTL_SECONDS)
        pipeline.publish(job_events_channel(status.job_id), payload)
        await pipeline.execute()


def _as_text(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


async def fetch_jobs(job_count: int) -> list[RedisJob]:
    """Remove and return up to ``job_count`` jobs in FIFO order.

    Queue entries whose two-hour job data has expired are discarded.
    """
    if job_count <= 0:
        raise ValueError("job_count must be greater than zero")

    client = get_redis_client()
    jobs: list[RedisJob] = []

    while len(jobs) < job_count:
        remaining = job_count - len(jobs)
        popped = await client.lpop(_queue_key(), count=remaining)
        if not popped:
            break

        if isinstance(popped, (str, bytes)):
            job_ids = [_as_text(popped)]
        else:
            job_ids = [_as_text(job_id) for job_id in popped]

        payloads = await client.mget([_job_key(job_id) for job_id in job_ids])
        for payload in payloads:
            if isinstance(payload, (str, bytes, bytearray)):
                jobs.append(RedisJob.model_validate_json(payload))

    return jobs


async def send_to_dead_letter_queue(job: RedisJob, reason: str) -> DeadLetterJob:
    """Append a failed job and its reason to the dead-letter queue."""
    reason = reason.strip()
    if not reason:
        raise ValueError("reason must not be empty")

    dead_letter_job = DeadLetterJob(
        job=job,
        reason=reason,
        failed_at=datetime.now(UTC),
    )
    await get_redis_client().rpush(
        _dead_letter_queue_key(), dead_letter_job.model_dump_json()
    )
    return dead_letter_job


async def close_redis_client() -> None:
    """Close the shared Redis connection pool, if it was created."""
    global _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
