"""Controllers for document-processing endpoints."""

import logging

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.exceptions import RedisError

from readforge.utils.reading_util import (
    create_presigned_url,
    is_file_exist,
)
from readforge.utils.redis_utils import RedisJobRequest, create_job

logger = logging.getLogger(__name__)

# HTTP status codes used by this controller:
# 202 Accepted: The document was successfully added to the processing queue.
# 404 Not Found: The requested document does not exist in R2.
# 422 Unprocessable Entity: FastAPI rejected an invalid request body.
# 502 Bad Gateway: R2 could not be reached or returned an unexpected error.
# 503 Service Unavailable: Redis could not accept the processing job.


class UploadDocRequest(BaseModel):
    """Request body for adding an existing R2 document to the job queue."""

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1)
    idem_key: str = Field(min_length=1)

    @field_validator("idem_key")
    @classmethod
    def validate_idem_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idem_key must not be empty")
        if len(value.encode("utf-8")) > 20:
            raise ValueError("idem_key must not exceed 20 bytes")
        return value


class UploadResponse(BaseModel):
    """Response returned after attempting to queue a document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    message: str
    job_id: str | None = None


def _response(status_code: int, payload: UploadResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def upload_doc(request: UploadDocRequest) -> JSONResponse:
    """Validate an R2 document and enqueue it for asynchronous processing."""
    try:
        file_exists = await is_file_exist(request.file_name)
        if not file_exists:
            return _response(
                status.HTTP_404_NOT_FOUND,
                UploadResponse(
                    success=False,
                    message=f"File '{request.file_name}' was not found",
                ),
            )

        signed_url = create_presigned_url(request.file_name)
    except (BotoCoreError, ClientError):
        logger.exception("Could not access R2 object %s", request.file_name)
        return _response(
            status.HTTP_502_BAD_GATEWAY,
            UploadResponse(
                success=False,
                message="Could not access document storage",
            ),
        )

    try:
        job = await create_job(
            RedisJobRequest(
                file_name=request.file_name,
                presigned_url=signed_url,
                idem_key=request.idem_key,
            )
        )
    except (RedisError, RuntimeError):
        logger.exception("Could not queue R2 object %s", request.file_name)
        return _response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            UploadResponse(
                success=False,
                message="Could not queue document for processing",
            ),
        )

    return _response(
        status.HTTP_202_ACCEPTED,
        UploadResponse(
            success=True,
            message="Document queued for processing",
            job_id=job.job_id,
        ),
    )
