"""Controllers for document-processing endpoints."""

import logging

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from readforge.utils.db_utils import ChecksumConflictError, ensure_document
from readforge.utils.media_bucket import is_unavailable_error
from readforge.utils.reading_util import (
    FileTamperingError,
    create_presigned_url,
    is_file_exist,
    verify_object_checksum_metadata,
)
from readforge.utils.redis_utils import RedisJobRequest, create_job

logger = logging.getLogger(__name__)

# HTTP status codes used by this controller:
# 202 Accepted: The document was successfully added to the processing queue.
# 404 Not Found: The requested document does not exist in R2.
# 409 Conflict: Stored or supplied checksums do not agree.
# 422 Unprocessable Entity: FastAPI rejected an invalid request body.
# 502 Bad Gateway: Storage returned an unexpected request error.
# 503 Service Unavailable: Storage, PostgreSQL, or Redis is unavailable.


class UploadDocRequest(BaseModel):
    """Request body for adding an existing media object to the job queue."""

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1)
    idem_key: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("checksum")
    @classmethod
    def normalize_checksum(cls, value: str) -> str:
        return value.lower()

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
    document_id: str | None = None


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

        verify_object_checksum_metadata(request.file_name, request.checksum)
        signed_url = create_presigned_url(request.file_name)
    except FileTamperingError:
        logger.warning("Checksum mismatch for media object %s", request.file_name)
        return _response(
            status.HTTP_409_CONFLICT,
            UploadResponse(
                success=False,
                message="File integrity verification failed",
            ),
        )
    except (BotoCoreError, ClientError) as error:
        logger.exception("Could not access media object %s", request.file_name)
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if is_unavailable_error(error)
            else status.HTTP_502_BAD_GATEWAY
        )
        return _response(
            response_status,
            UploadResponse(
                success=False,
                message=(
                    "Document storage is temporarily unavailable"
                    if response_status == status.HTTP_503_SERVICE_UNAVAILABLE
                    else "Document storage rejected the request"
                ),
            ),
        )

    try:
        document_id = await ensure_document(request.file_name, request.checksum)
        job = await create_job(
            RedisJobRequest(
                file_name=request.file_name,
                presigned_url=signed_url,
                idem_key=request.idem_key,
                checksum=request.checksum,
            )
        )
    except ChecksumConflictError:
        logger.warning("Stored checksum conflict for %s", request.file_name)
        return _response(
            status.HTTP_409_CONFLICT,
            UploadResponse(
                success=False,
                message="File integrity verification failed",
            ),
        )
    except (RedisError, SQLAlchemyError, RuntimeError):
        logger.exception("Could not queue media object %s", request.file_name)
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
            document_id=str(document_id),
        ),
    )
