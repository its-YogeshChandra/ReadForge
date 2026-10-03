"""Redis worker for the PDF → OCR → embedding pipeline."""

import asyncio
from datetime import UTC, datetime
import logging
from tempfile import TemporaryDirectory

from readforge.database import close_database
from readforge.utils.db_utils import fail_job, save_embeddings, save_ocr, start_job
from readforge.utils.embedding_utils import embed_texts, embedding_model
from readforge.utils.reading_util import (
    MAX_PDF_BYTES,
    OcrResponse,
    PdfPage,
    download_file_from_media_bucket,
    download_page_from_pdf,
    get_file_size,
    ocr_util,
    page_to_image,
)
from readforge.utils.redis_utils import (
    RedisJob,
    RedisJobStatus,
    close_redis_client,
    fetch_jobs,
    publish_job_status,
    send_to_dead_letter_queue,
)
from readforge.utils.tracing import trace

JOB_COUNT = 10
PAGE_BATCH_SIZE = 10
POLL_INTERVAL_SECONDS = 1
EMBEDDING_BATCH_SIZE = 32

logger = logging.getLogger(__name__)


def _ocr_pages(pages: list[PdfPage]) -> list[OcrResponse]:
    results: list[OcrResponse] = []
    for start in range(0, len(pages), PAGE_BATCH_SIZE):
        images = page_to_image(pages[start : start + PAGE_BATCH_SIZE])
        results.extend(ocr_util(images))
    return results


def _read_and_ocr(job: RedisJob, size_bytes: int) -> list[OcrResponse]:
    if size_bytes <= MAX_PDF_BYTES:
        return _ocr_pages(
            download_page_from_pdf(
                job.file_name,
                expected_checksum=job.checksum,
            )
        )

    with TemporaryDirectory(prefix="readforge-") as directory:
        path = download_file_from_media_bucket(
            job.file_name, directory, job.checksum
        )
        pages = download_page_from_pdf(job.file_name, file_path=path)
        return _ocr_pages(pages)


def _embed_pages(
    results: list[OcrResponse],
) -> list[tuple[int, str, str, list[float]]]:
    chunks: list[tuple[int, str, str, list[float]]] = []
    pages: list[tuple[int, str]] = []
    for result in results:
        page_text = result.file_data.get("text", "")
        text = page_text.strip() if isinstance(page_text, str) else ""
        if text:
            pages.append((result.page_number, text))

    if not pages:
        return []

    model = embedding_model()
    for start in range(0, len(pages), EMBEDDING_BATCH_SIZE):
        batch = pages[start : start + EMBEDDING_BATCH_SIZE]
        vectors = embed_texts([text for _, text in batch])
        chunks.extend(
            (page_number, text, model, vector)
            for (page_number, text), vector in zip(batch, vectors, strict=True)
        )
    return chunks


async def process_job(job: RedisJob) -> None:
    """Process one Redis job and persist its OCR and embeddings."""
    trace(job.job_id, "worker.claimed", object_key=job.file_name)
    identifiers = await start_job(
        job.job_id,
        job.file_name,
        job.idem_key,
        job.created_at,
        checksum=job.checksum,
    )
    if identifiers is None:
        trace(job.job_id, "worker.skipped_completed")
        return

    job_id, document_id = identifiers
    started_at = datetime.now(UTC)
    await publish_job_status(
        RedisJobStatus(
            job_id=job.job_id,
            document_id=str(document_id),
            status="processing",
            created_at=job.created_at,
            started_at=started_at,
        )
    )
    trace(job_id, "document.processing", document_id=document_id)
    size_bytes = get_file_size(job.file_name, expected_checksum=job.checksum)
    trace(job_id, "document.download_verified", size_bytes=size_bytes)
    results = _read_and_ocr(job, size_bytes)
    trace(job_id, "document.ocr_completed", page_count=len(results))
    ocr_result = [
        {"page_number": result.page_number, **result.file_data} for result in results
    ]
    await save_ocr(document_id, size_bytes, ocr_result)
    embeddings = _embed_pages(results)
    trace(job_id, "document.embeddings_created", chunk_count=len(embeddings))
    await save_embeddings(job_id, document_id, embeddings)
    completed_at = datetime.now(UTC)
    await publish_job_status(
        RedisJobStatus(
            job_id=job.job_id,
            document_id=str(document_id),
            status="completed",
            created_at=job.created_at,
            started_at=started_at,
            completed_at=completed_at,
        )
    )
    trace(job_id, "document.completed", document_id=document_id)


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
                        await fail_job(job.job_id, reason)
                    except Exception:
                        logger.exception("Could not mark job %s as failed", job.job_id)
                    try:
                        await publish_job_status(
                            RedisJobStatus(
                                job_id=job.job_id,
                                status="failed",
                                created_at=job.created_at,
                                completed_at=datetime.now(UTC),
                                error_message=reason,
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Could not publish failure for job %s", job.job_id
                        )
                    trace(job.job_id, "document.failed", error_type=type(error).__name__)
                    await send_to_dead_letter_queue(job, reason)
    finally:
        await close_redis_client()
        await close_database()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
