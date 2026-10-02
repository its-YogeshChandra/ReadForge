"""FastAPI application for the ReadForge service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from readforge.controllers.chat_controller import ChatRequest, ChatResponse, chat
from readforge.controllers.doc_controller import (
    UploadDocRequest,
    UploadResponse,
    upload_doc,
)
from readforge.controllers.document_metadata_controller import (
    DocumentMetadataRequest,
    DocumentMetadataResponse,
    update_document_metadata,
)
from readforge.database import close_database
from readforge.utils.redis_utils import close_redis_client


# Closes shared resources after FastAPI stops accepting requests.
# Used to prevent Redis connections from remaining open during shutdown.
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release shared application resources during shutdown."""
    yield
    await close_redis_client()
    await close_database()


app = FastAPI(
    title="ReadForge API",
    description="Queue documents stored in the media bucket for processing.",
    version="0.1.0",
    lifespan=lifespan,
)


# Returns a simple response confirming that the API process is running.
# Used by monitoring systems and deployment health checks.
@app.get("/health", tags=["Service"])
async def health_check() -> dict[str, bool]:
    """Return a lightweight service health response."""
    return {"success": True}


# Passes a validated document request to the upload controller for queueing.
# Used to create asynchronous document-processing jobs through the HTTP API.
@app.post(
    "/documents",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Documents"],
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": UploadResponse,
            "description": "The document does not exist in the media bucket.",
        },
        status.HTTP_409_CONFLICT: {
            "model": UploadResponse,
            "description": "The media object checksum did not match.",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": UploadResponse,
            "description": "The media bucket rejected the request.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": UploadResponse,
            "description": "Storage or the job infrastructure is unavailable.",
        },
    },
)
async def create_document_job(request: UploadDocRequest) -> JSONResponse:
    """Queue an existing R2 document for processing."""
    return await upload_doc(request)


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["Conversations"],
)
async def create_chat_message(request: ChatRequest) -> ChatResponse:
    """Answer one question using evidence retrieved from an uploaded document."""
    return await chat(request)


@app.patch(
    "/documents/{document_id}/metadata",
    response_model=DocumentMetadataResponse,
    tags=["Documents"],
)
async def patch_document_metadata(
    document_id: UUID,
    request: DocumentMetadataRequest,
) -> DocumentMetadataResponse:
    """Store plan metadata used to ground later agent answers."""
    return await update_document_metadata(document_id, request)
