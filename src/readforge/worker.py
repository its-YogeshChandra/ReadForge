"""Redis worker for the PDF → OCR → embedding pipeline."""

import asyncio
import logging
import os
from tempfile import TemporaryDirectory

from readforge.database import close_database
from readforge.utils.db_utils import fail_job, save_embeddings, save_ocr, start_job
from readforge.utils.embedding_utils import EmbeddingsPayload, embed_text
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
    close_redis_client,
    fetch_jobs,
    send_to_dead_letter_queue,
)

JOB_COUNT = 10
PAGE_BATCH_SIZE = 10
POLL_INTERVAL_SECONDS = 1

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
    model = os.getenv("EMBEDDING_MODEL", "clip").strip() or "clip"
    chunks: list[tuple[int, str, str, list[float]]] = []

    # ponytail: one chunk per page until the embedding model's token limit is known.
    for result in results:
        page_text = result.file_data.get("text", "")
        text = page_text.strip() if isinstance(page_text, str) else ""
        if not text:
            continue
        chunks.append(
            (
                result.page_number,
                text,
                model,
                embed_text(EmbeddingsPayload(result.file_name, text)),
            )
        )
    return chunks


async def process_job(job: RedisJob) -> None:
    """Process one Redis job and persist its OCR and embeddings."""
    identifiers = await start_job(
        job.job_id,
        job.file_name,
        job.idem_key,
        job.created_at,
        checksum=job.checksum,
    )
    if identifiers is None:
        return

    job_id, document_id = identifiers
    size_bytes = get_file_size(job.file_name, expected_checksum=job.checksum)
    results = _read_and_ocr(job, size_bytes)
    ocr_result = [
        {"page_number": result.page_number, **result.file_data} for result in results
    ]
    await save_ocr(document_id, size_bytes, ocr_result)
    await save_embeddings(job_id, document_id, _embed_pages(results))


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
                    await send_to_dead_letter_queue(job, reason)
    finally:
        await close_redis_client()
        await close_database()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
