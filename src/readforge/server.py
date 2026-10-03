"""FastAPI application for the ReadForge service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

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
from readforge.controllers.job_controller import (
    JobStatusResponse,
    job_events,
    job_status,
)
from readforge.database import close_database, engine
from readforge.observability import configure_observability, shutdown_observability
from readforge.utils.redis_utils import close_redis_client

logger = logging.getLogger(__name__)
telemetry_enabled = configure_observability(
    "readforge-api", sqlalchemy_engine=engine.sync_engine
)

# Closes shared resources after FastAPI stops accepting requests.
# Used to prevent Redis connections from remaining open during shutdown.
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release shared application resources during shutdown."""
    yield
    await close_redis_client()
    await close_database()
    shutdown_observability()


app = FastAPI(
    title="ReadForge API",
    description="Queue documents stored in the media bucket for processing.",
    version="0.1.0",
    lifespan=lifespan,
)

if telemetry_enabled:
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=r"/health$,/jobs/[^/]+/events$",
    )


@app.middleware("http")
async def persist_server_errors(request: Request, call_next):
    """Keep successful requests out of logs while retaining server failures."""
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled API request failure")
        raise

    if response.status_code >= 500:
        logger.error(
            "API request failed",
            extra={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "http.response.status_code": response.status_code,
            },
        )
    return response


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


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["Documents"],
)
async def get_job_status(job_id: UUID) -> JobStatusResponse:
    """Return the processing state for one upload request."""
    return await job_status(job_id)


@app.get("/jobs/{job_id}/events", tags=["Documents"])
async def stream_job_status(job_id: UUID) -> StreamingResponse:
    """Stream processing transitions for one upload request."""
    return await job_events(job_id)


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["Conversations"],
)
async def create_chat_message(
    request: ChatRequest,
    http_request: Request,
) -> ChatResponse:
    """Answer one question using evidence retrieved from an uploaded document."""
    correlation_id = http_request.headers.get("x-request-id") or str(uuid4())
    return await chat(request, correlation_id)


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
