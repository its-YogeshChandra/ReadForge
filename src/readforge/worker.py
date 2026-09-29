"""Redis worker for the PDF → OCR → embedding pipeline."""

import asyncio
from datetime import UTC, datetime
import logging
import os
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import delete, select

from readforge.database import SessionLocal, close_database
from readforge.database.schema import Document, DocumentChunk, Job
from readforge.utils.embedding_utils import EmbeddingsPayload, embed_text
from readforge.utils.reading_util import (
    MAX_PDF_BYTES,
    OcrResponse,
    PdfPage,
    download_files_from_s3,
    download_page_from_pdf,
    get_file_size,
    ocr_util,
    page_to_image,
)
from readforge.utils.redis_utils import (
    RedisJob,
    close_redis_client,
    fetch_jobs,
    send_to_dead_letter_queue,
)

JOB_COUNT = 10
PAGE_BATCH_SIZE = 10
POLL_INTERVAL_SECONDS = 1

logger = logging.getLogger(__name__)


class WorkerJobError(RuntimeError):
    """A queued job cannot be processed safely."""


async def _start_job(job: RedisJob) -> tuple[UUID, UUID] | None:
    """Mark a database job as processing and return its IDs."""
    try:
        job_id = UUID(job.job_id)
    except ValueError as error:
        raise WorkerJobError("Redis job_id is not a valid UUID") from error

    async with SessionLocal() as session:
        document = await session.scalar(
            select(Document).where(Document.object_key == job.file_name)
        )
        if document is None:
            raise WorkerJobError(
                f"Document '{job.file_name}' does not exist in PostgreSQL"
            )

        database_job = await session.get(Job, job_id)
        if database_job is not None and database_job.status == "completed":
            return None
        if database_job is None:
            database_job = Job(
                id=job_id,
                document_id=document.id,
                idempotency_key=job.idem_key,
                attempt_count=0,
                created_at=job.created_at,
            )
            session.add(database_job)
        elif database_job.document_id != document.id:
            raise WorkerJobError(
                "Redis and PostgreSQL jobs reference different documents"
            )

        database_job.status = "processing"
        database_job.attempt_count += 1
        database_job.error_message = None
        database_job.started_at = datetime.now(UTC)
        database_job.completed_at = None
        await session.commit()
        return job_id, document.id


def _ocr_pages(pages: list[PdfPage]) -> list[OcrResponse]:
    results: list[OcrResponse] = []
    for start in range(0, len(pages), PAGE_BATCH_SIZE):
        images = page_to_image(pages[start : start + PAGE_BATCH_SIZE])
        results.extend(ocr_util(images))
    return results


def _read_and_ocr(job: RedisJob, size_bytes: int) -> list[OcrResponse]:
    if size_bytes <= MAX_PDF_BYTES:
        return _ocr_pages(download_page_from_pdf(job.file_name))

    with TemporaryDirectory(prefix="readforge-") as directory:
        path = download_files_from_s3(job.file_name, directory)
        pages = download_page_from_pdf(job.file_name, file_path=path)
        return _ocr_pages(pages)


async def _save_ocr(
    document_id: UUID,
    size_bytes: int,
    results: list[OcrResponse],
) -> None:
    ocr_result = [
        {"page_number": result.page_number, **result.file_data} for result in results
    ]
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise WorkerJobError("Document was deleted while OCR was running")
        document.content_type = "application/pdf"
        document.size_bytes = size_bytes
        document.page_count = len(results)
        document.ocr_result = ocr_result
        await session.commit()


async def _save_embeddings(
    job_id: UUID,
    document_id: UUID,
    results: list[OcrResponse],
) -> None:
    model = os.getenv("EMBEDDING_MODEL", "clip").strip() or "clip"
    chunks: list[DocumentChunk] = []

    # ponytail: one chunk per page until the embedding model's token limit is known.
    for result in results:
        page_text = result.file_data.get("text", "")
        text = page_text.strip() if isinstance(page_text, str) else ""
        if not text:
            continue
        chunks.append(
            DocumentChunk(
                document_id=document_id,
                page_number=result.page_number,
                chunk_index=0,
                content=text,
                embedding_model=model,
                embedding=embed_text(EmbeddingsPayload(result.file_name, text)),
            )
        )

    async with SessionLocal() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        session.add_all(chunks)
        database_job = await session.get(Job, job_id)
        if database_job is None:
            raise WorkerJobError("Database job was deleted while processing")
        database_job.status = "completed"
        database_job.completed_at = datetime.now(UTC)
        await session.commit()


async def _fail_job(job_id: str, reason: str) -> None:
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        return

    async with SessionLocal() as session:
        database_job = await session.get(Job, parsed_job_id)
        if database_job is None:
            return
        database_job.status = "failed"
        database_job.error_message = reason
        database_job.completed_at = datetime.now(UTC)
        await session.commit()


async def process_job(job: RedisJob) -> None:
    """Process one Redis job and persist its OCR and embeddings."""
    identifiers = await _start_job(job)
    if identifiers is None:
        return

    job_id, document_id = identifiers
    size_bytes = get_file_size(job.file_name)
    results = _read_and_ocr(job, size_bytes)
    await _save_ocr(document_id, size_bytes, results)
    await _save_embeddings(job_id, document_id, results)


async def run_worker() -> None:
    """Poll Redis forever and process queued jobs sequentially."""
    try:
        while True:
            jobs = await fetch_jobs(JOB_COUNT)
            if not jobs:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            for job in jobs:
                try:
                    await process_job(job)
                except Exception as error:
                    reason = f"{type(error).__name__}: {error}"
                    logger.exception("Job %s failed", job.job_id)
                    try:
                        await _fail_job(job.job_id, reason)
                    except Exception:
                        logger.exception("Could not mark job %s as failed", job.job_id)
                    await send_to_dead_letter_queue(job, reason)
    finally:
        await close_redis_client()
        await close_database()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
