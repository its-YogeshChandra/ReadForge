"""Integration tests for the ``worker.py`` PDF → OCR → embedding pipeline.

These tests exercise the real Redis, PostgreSQL, R2, Apple Vision, and CLIP
embedding services exactly as the production worker does.  Nothing is
monkeypatched.

Prerequisites before running:
    • PostgreSQL with pgvector is up:      ``docker compose up -d postgres``
    • Schema is initialised:               ``uv run readforge-migrate``
    • Redis is running:                     ``docker compose up -d redis`` (or local)
    • R2 credentials are in ``.env``
    • CLIP embedding service is reachable at ``CLIP_API_URL``
    • ``EXISTING_MEDIA_FILE`` points to a real PDF in the R2 ``datasets`` bucket
    • ``EXISTING_MEDIA_SHA256`` contains that PDF's trusted SHA-256 checksum
    • macOS with Apple Vision framework

Run with:
    uv run --with pytest pytest tests/test_worker.py -v
"""

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from readforge.database import SessionLocal
from readforge.database.schema import Document, DocumentChunk, Job, User
from readforge.utils.db_utils import fail_job, save_embeddings, save_ocr, start_job
from readforge.utils.db_utils import WorkerJobError
from readforge.utils.embedding_utils import EmbeddingsPayload, embed_text
from readforge.utils.reading_util import (
    MAX_PDF_BYTES,
    OcrResponse,
    PDFReadError,
    PdfPage,
    download_page_from_pdf,
    get_file_size,
    page_to_image,
    ocr_util,
    OcrRequest,
)
from readforge.utils.redis_utils import (
    RedisJob,
    RedisJobRequest,
    close_redis_client,
    create_job,
    fetch_jobs,
    get_redis_client,
    send_to_dead_letter_queue,
)
from readforge.worker import (
    _embed_pages,
    _ocr_pages,
    _read_and_ocr,
    process_job,
)


# ── configuration ─────────────────────────────────────────────────────────
# Replace with a real PDF that exists in the configured R2 bucket.
EXISTING_MEDIA_FILE = "Fintech-Edge-April-2018.pdf"
EXISTING_MEDIA_CHECKSUM = os.getenv("EXISTING_MEDIA_SHA256", "0" * 64)

# Replace with a key that definitely does NOT exist.
MISSING_MEDIA_FILE = "DOES_NOT_EXIST__test_worker.pdf"


# ── helpers ───────────────────────────────────────────────────────────────


def _run(coro):
    """Run an async coroutine from a sync test without pytest-asyncio."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _new_idem_key() -> str:
    """Return a fresh idempotency key that fits the 20-byte constraint."""
    return uuid4().hex[:20]


@pytest.fixture(scope="module", autouse=True)
def _isolated_redis_namespace():
    """Keep test jobs separate and remove every Redis key created here."""
    previous = os.environ.get("REDIS_KEY_NAMESPACE")
    namespace = f"readforge:test-worker:{uuid4().hex}"
    os.environ["REDIS_KEY_NAMESPACE"] = namespace
    yield

    async def _cleanup() -> None:
        client = get_redis_client()
        keys = [key async for key in client.scan_iter(match=f"{namespace}:*")]
        if keys:
            await client.delete(*keys)
        await close_redis_client()

    _run(_cleanup())
    if previous is None:
        os.environ.pop("REDIS_KEY_NAMESPACE", None)
    else:
        os.environ["REDIS_KEY_NAMESPACE"] = previous


async def _ensure_user() -> UUID:
    """Return the ID of a test user, creating one if needed."""
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.username == "test_worker_user")
        )
        if user is None:
            user = User(username="test_worker_user", email="test_worker@readforge.dev")
            session.add(user)
            await session.commit()
        return user.id


async def _ensure_document(object_key: str) -> UUID:
    """Return the ID of a document row, creating one if missing."""
    user_id = await _ensure_user()
    async with SessionLocal() as session:
        doc = await session.scalar(
            select(Document).where(Document.object_key == object_key)
        )
        if doc is None:
            doc = Document(user_id=user_id, object_key=object_key)
            session.add(doc)
            await session.commit()
        return doc.id


async def _create_redis_job(
    file_name: str = EXISTING_MEDIA_FILE,
    idem_key: str | None = None,
) -> RedisJob:
    """Push a real job through Redis and return the RedisJob."""
    return await create_job(
        RedisJobRequest(
            file_name=file_name,
            presigned_url="https://example.invalid/test-worker.pdf",
            idem_key=idem_key or _new_idem_key(),
            checksum=EXISTING_MEDIA_CHECKSUM,
        )
    )


async def _cleanup_job(job_id: str, document_id: UUID) -> None:
    """Remove the job and its chunks so repeated runs don't collide."""
    async with SessionLocal() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await session.execute(delete(Job).where(Job.id == UUID(job_id)))
        await session.commit()


def _make_minimal_pdf_pages():
    """Build a one-page blank PDF in memory and return its PdfPage list."""
    from Foundation import NSMutableData
    import Quartz as Q

    data = NSMutableData.data()
    consumer = Q.CGDataConsumerCreateWithCFData(data)
    context = Q.CGPDFContextCreate(consumer, ((0, 0), (200, 100)), None)
    Q.CGPDFContextBeginPage(context, None)
    Q.CGPDFContextEndPage(context)
    Q.CGPDFContextClose(context)
    return download_page_from_pdf("test.pdf", file_data=bytes(data))


# ═══════════════════════════════════════════════════════════════════════════
# 1. POSITIVE TESTS — these conditions must pass
# ════════════════════════════r══════════════════════════════════════════════


# what : Gets the byte-size of a real R2 object without downloading the body.
# why  : get_file_size is the first I/O call inside process_job; it must
#         return a positive integer for the pipeline to decide its download path.
class TestGetFileSize:
    def test_returns_positive_integer_for_existing_file(self) -> None:
        size = get_file_size(EXISTING_MEDIA_FILE)
        assert isinstance(size, int)
        assert size > 0


# what : Downloads the real PDF, renders pages, and OCRs them through Apple Vision.
# why  : This is the core pipeline that _read_and_ocr calls; every stage must
#         produce a non-empty result on real R2 data with the real macOS OCR backend.
class TestOcrPipeline:
    def test_download_pdf_returns_pages(self) -> None:
        size = get_file_size(EXISTING_MEDIA_FILE)
        if size > MAX_PDF_BYTES:
            pytest.skip("File exceeds in-memory limit; needs S3 download path")

        pages = download_page_from_pdf(EXISTING_MEDIA_FILE)

        assert len(pages) >= 1
        for page in pages:
            assert isinstance(page, PdfPage)
            assert page.file_name == EXISTING_MEDIA_FILE
            assert page.page_number >= 1

    def test_pages_render_to_images(self) -> None:
        size = get_file_size(EXISTING_MEDIA_FILE)
        if size > MAX_PDF_BYTES:
            pytest.skip("File exceeds in-memory limit")
        pages = download_page_from_pdf(EXISTING_MEDIA_FILE)
        images = page_to_image(pages[:1])

        assert len(images) == 1
        assert images[0].page_number == pages[0].page_number
        assert images[0].file_data is not None

    def test_ocr_returns_text_for_rendered_pages(self) -> None:
        size = get_file_size(EXISTING_MEDIA_FILE)
        if size > MAX_PDF_BYTES:
            pytest.skip("File exceeds in-memory limit")
        pages = download_page_from_pdf(EXISTING_MEDIA_FILE)
        images = page_to_image(pages[:1])
        results = ocr_util(images)

        assert len(results) == 1
        assert isinstance(results[0], OcrResponse)
        assert results[0].file_name == EXISTING_MEDIA_FILE
        assert results[0].page_number >= 1
        assert isinstance(results[0].file_data, dict)
        assert "text" in results[0].file_data
        assert "lines" in results[0].file_data
        assert results[0].file_data["text"].strip()

    def test_ocr_pages_batches_correctly(self) -> None:
        size = get_file_size(EXISTING_MEDIA_FILE)
        if size > MAX_PDF_BYTES:
            pytest.skip("File exceeds in-memory limit")
        pages = download_page_from_pdf(EXISTING_MEDIA_FILE)[:2]
        results = _ocr_pages(pages)

        assert len(results) == len(pages)
        assert all(isinstance(r, OcrResponse) for r in results)

    def test_read_and_ocr_produces_results(self) -> None:
        if EXISTING_MEDIA_CHECKSUM == "0" * 64:
            pytest.skip("EXISTING_MEDIA_SHA256 is not configured")
        job = RedisJob(
            file_name=EXISTING_MEDIA_FILE,
            presigned_url="https://example.invalid/test-worker.pdf",
            idem_key=_new_idem_key(),
            checksum=EXISTING_MEDIA_CHECKSUM,
            job_id=str(uuid4()),
            created_at=datetime.now(UTC),
        )
        size = get_file_size(EXISTING_MEDIA_FILE)
        results = _read_and_ocr(job, size)

        assert len(results) >= 1
        for result in results:
            assert isinstance(result, OcrResponse)
            assert isinstance(result.file_data, dict)


# what : Sends real page text to the CLIP embedding service.
# why  : The worker stores these vectors in pgvector; the service must return
#         a list of finite floats for every non-empty page.
class TestEmbedding:
    def test_embed_text_returns_float_vector(self) -> None:
        clip_url = os.getenv("CLIP_API_URL", "")
        if not clip_url:
            pytest.skip("CLIP_API_URL is not configured")

        payload = EmbeddingsPayload(
            file_name=EXISTING_MEDIA_FILE,
            text_data="This is a sample text for embedding.",
        )
        vector = embed_text(payload)

        assert isinstance(vector, list)
        assert len(vector) > 0
        assert all(isinstance(v, float) for v in vector)

    def test_embed_pages_returns_tuples(self) -> None:
        clip_url = os.getenv("CLIP_API_URL", "")
        if not clip_url:
            pytest.skip("CLIP_API_URL is not configured")

        ocr_results = [
            OcrResponse(
                file_name=EXISTING_MEDIA_FILE,
                page_number=1,
                file_data={"text": "Sample text content for embedding test."},
            ),
        ]
        chunks = _embed_pages(ocr_results)

        assert len(chunks) == 1
        page_number, text, model, vector = chunks[0]
        assert page_number == 1
        assert isinstance(text, str) and len(text) > 0
        assert isinstance(model, str) and len(model) > 0
        assert isinstance(vector, list) and len(vector) > 0


# what : Runs start_job, save_ocr, and save_embeddings against real PostgreSQL.
# why  : The database layer must create/update rows without constraint violations
#         when given valid worker data.
class TestDatabaseOperations:
    def test_start_job_returns_identifiers(self) -> None:
        async def _test():
            document_id = await _ensure_document(EXISTING_MEDIA_FILE)
            job_id = str(uuid4())
            idem_key = _new_idem_key()

            result = await start_job(
                job_id, EXISTING_MEDIA_FILE, idem_key, datetime.now(UTC)
            )

            assert result is not None
            returned_job_id, returned_doc_id = result
            assert returned_job_id == UUID(job_id)
            assert returned_doc_id == document_id

            await _cleanup_job(job_id, document_id)

        _run(_test())

    def test_start_job_skips_completed_job(self) -> None:
        async def _test():
            document_id = await _ensure_document(EXISTING_MEDIA_FILE)
            job_id = str(uuid4())
            idem_key = _new_idem_key()

            # first run: creates the job
            await start_job(job_id, EXISTING_MEDIA_FILE, idem_key, datetime.now(UTC))

            # mark it completed
            async with SessionLocal() as session:
                db_job = await session.get(Job, UUID(job_id))
                db_job.status = "completed"
                db_job.completed_at = datetime.now(UTC)
                await session.commit()

            # second run: should return None for a completed job
            result = await start_job(
                job_id, EXISTING_MEDIA_FILE, idem_key, datetime.now(UTC)
            )
            assert result is None

            await _cleanup_job(job_id, document_id)

        _run(_test())

    def test_save_ocr_updates_document(self) -> None:
        async def _test():
            document_id = await _ensure_document(EXISTING_MEDIA_FILE)
            ocr_result = [
                {"page_number": 1, "text": "Test page content", "lines": []},
            ]

            await save_ocr(document_id, 12345, ocr_result)

            async with SessionLocal() as session:
                doc = await session.get(Document, document_id)
                assert doc.size_bytes == 12345
                assert doc.page_count == 1
                assert doc.content_type == "application/pdf"
                assert doc.ocr_result == ocr_result

        _run(_test())

    def test_save_embeddings_marks_job_completed(self) -> None:
        async def _test():
            document_id = await _ensure_document(EXISTING_MEDIA_FILE)
            job_id = str(uuid4())
            idem_key = _new_idem_key()

            await start_job(job_id, EXISTING_MEDIA_FILE, idem_key, datetime.now(UTC))

            chunks = [
                (1, "Sample text", "clip", [0.1, 0.2, 0.3]),
            ]
            await save_embeddings(UUID(job_id), document_id, chunks)

            async with SessionLocal() as session:
                db_job = await session.get(Job, UUID(job_id))
                assert db_job.status == "completed"
                assert db_job.completed_at is not None

            await _cleanup_job(job_id, document_id)

        _run(_test())

    def test_fail_job_marks_job_failed(self) -> None:
        async def _test():
            document_id = await _ensure_document(EXISTING_MEDIA_FILE)
            job_id = str(uuid4())
            idem_key = _new_idem_key()

            await start_job(job_id, EXISTING_MEDIA_FILE, idem_key, datetime.now(UTC))
            await fail_job(job_id, "Test failure reason")

            async with SessionLocal() as session:
                db_job = await session.get(Job, UUID(job_id))
                assert db_job.status == "failed"
                assert db_job.error_message == "Test failure reason"
                assert db_job.completed_at is not None

            await _cleanup_job(job_id, document_id)

        _run(_test())


# what : Creates, fetches, and dead-letters jobs through real Redis.
# why  : The worker loop depends on fetch_jobs returning valid RedisJob objects
#         and send_to_dead_letter_queue storing failures for later replay.
class TestRedisOperations:
    def test_create_and_fetch_job(self) -> None:
        async def _test():
            job = await _create_redis_job()
            jobs = await fetch_jobs(1)

            assert isinstance(job.job_id, str)
            assert UUID(job.job_id)
            assert job.file_name == EXISTING_MEDIA_FILE
            assert isinstance(job.created_at, datetime)
            assert [queued.job_id for queued in jobs] == [job.job_id]

        _run(_test())

    def test_idempotent_job_creation(self) -> None:
        async def _test():
            idem_key = _new_idem_key()
            job1 = await _create_redis_job(idem_key=idem_key)
            job2 = await _create_redis_job(idem_key=idem_key)

            assert job1.job_id == job2.job_id

        _run(_test())

    def test_fetch_jobs_returns_list(self) -> None:
        async def _test():
            created = await _create_redis_job()
            jobs = await fetch_jobs(10)

            assert isinstance(jobs, list)
            assert all(isinstance(job, RedisJob) for job in jobs)
            assert created.job_id in {job.job_id for job in jobs}

        _run(_test())

    def test_send_to_dead_letter_queue(self) -> None:
        async def _test():
            job = await _create_redis_job()
            dlq_job = await send_to_dead_letter_queue(job, "test failure reason")

            assert dlq_job.job.job_id == job.job_id
            assert dlq_job.reason == "test failure reason"
            assert isinstance(dlq_job.failed_at, datetime)

        _run(_test())


# what : Runs the full process_job pipeline from Redis job to completed DB state.
# why  : This is the end-to-end integration path: R2 → PDF → OCR → embeddings → PostgreSQL.
#         If any seam breaks between real services, this test catches it.
class TestProcessJob:
    def test_process_job_end_to_end(self) -> None:
        clip_url = os.getenv("CLIP_API_URL", "")
        if not clip_url:
            pytest.skip("CLIP_API_URL is not configured")
        if EXISTING_MEDIA_CHECKSUM == "0" * 64:
            pytest.skip("EXISTING_MEDIA_SHA256 is not configured")

        async def _test():
            document_id = await _ensure_document(EXISTING_MEDIA_FILE)
            job = await _create_redis_job()

            try:
                await process_job(job)

                async with SessionLocal() as session:
                    doc = await session.get(Document, document_id)
                    assert doc.content_type == "application/pdf"
                    assert doc.size_bytes is not None and doc.size_bytes > 0
                    assert doc.page_count is not None and doc.page_count > 0
                    assert doc.ocr_result is not None and len(doc.ocr_result) > 0

                    db_job = await session.get(Job, UUID(job.job_id))
                    assert db_job.status == "completed"
                    assert db_job.completed_at is not None

                    chunks = (
                        await session.scalars(
                            select(DocumentChunk).where(
                                DocumentChunk.document_id == document_id
                            )
                        )
                    ).all()
                    assert chunks
                    for chunk in chunks:
                        assert chunk.content.strip() != ""
                        assert len(chunk.embedding) > 0
            finally:
                await _cleanup_job(job.job_id, document_id)

        _run(_test())


# ═══════════════════════════════════════════════════════════════════════════
# 2. NEGATIVE TESTS — these conditions must fail cleanly
# ═══════════════════════════════════════════════════════════════════════════


# what : Verifies get_file_size rejects garbage file names.
# why  : A malformed or empty key passed to R2 must raise before the pipeline
#         wastes resources downloading or OCR-ing nothing.
class TestGetFileSizeNegative:
    def test_empty_file_name_raises(self) -> None:
        with pytest.raises(ValueError, match="file_name must not be empty"):
            get_file_size("")

    def test_whitespace_only_file_name_raises(self) -> None:
        with pytest.raises(ValueError, match="file_name must not be empty"):
            get_file_size("   ")

    def test_non_string_file_name_raises(self) -> None:
        with pytest.raises(ValueError, match="file_name must not be empty"):
            get_file_size(None)  # type: ignore[arg-type]

    def test_missing_file_raises_pdf_read_error(self) -> None:
        with pytest.raises(PDFReadError):
            get_file_size(MISSING_MEDIA_FILE)


# what : Verifies the PDF download path rejects corrupt and invalid inputs.
# why  : Corrupt bytes or empty files must not reach the OCR pipeline.
class TestPdfDownloadNegative:
    def test_invalid_bytes_raises(self) -> None:
        with pytest.raises(PDFReadError, match="not a valid PDF"):
            download_page_from_pdf("bad.pdf", file_data=b"not a pdf at all")

    def test_empty_bytes_raises(self) -> None:
        with pytest.raises(PDFReadError, match="PDF is empty"):
            download_page_from_pdf("empty.pdf", file_data=b"")

    def test_empty_file_name_raises(self) -> None:
        with pytest.raises(ValueError, match="file_name must not be empty"):
            download_page_from_pdf("")

    def test_both_file_data_and_file_path_raises(self) -> None:
        with pytest.raises(
            ValueError, match="Provide only one of file_data or file_path"
        ):
            download_page_from_pdf(
                "test.pdf",
                file_data=b"%PDF-1.4",
                file_path="/tmp/test.pdf",
            )


# what : Verifies page_to_image rejects empty and invalid inputs.
# why  : An empty page list or wrong types must not silently produce no output.
class TestPageToImageNegative:
    def test_empty_pages_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one PDF page"):
            page_to_image([])

    def test_zero_scale_raises(self) -> None:
        pages = _make_minimal_pdf_pages()
        with pytest.raises(ValueError, match="scale must be greater than zero"):
            page_to_image(pages, scale=0)

    def test_negative_scale_raises(self) -> None:
        pages = _make_minimal_pdf_pages()
        with pytest.raises(ValueError, match="scale must be greater than zero"):
            page_to_image(pages, scale=-1.0)


# what : Verifies ocr_util rejects empty, invalid, and malformed requests.
# why  : The OCR layer is expensive; bad data must be rejected before Vision calls.
class TestOcrUtilNegative:
    def test_empty_data_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one OCR request"):
            ocr_util([])

    def test_zero_attempts_raises(self) -> None:
        with pytest.raises(ValueError, match="attempts must be greater than zero"):
            ocr_util([OcrRequest("test.pdf", 1, object())], attempts=0)

    def test_empty_file_name_in_request_raises(self) -> None:
        with pytest.raises(ValueError, match="file_name must not be empty"):
            ocr_util([OcrRequest("", 1, object())])

    def test_zero_page_number_raises(self) -> None:
        with pytest.raises(ValueError, match="page_number must be greater than zero"):
            ocr_util([OcrRequest("test.pdf", 0, object())])

    def test_none_image_data_raises(self) -> None:
        with pytest.raises(ValueError, match="has no image data"):
            ocr_util([OcrRequest("test.pdf", 1, None)])


# what : Verifies the embedding client rejects empty and invalid payloads.
# why  : Empty text or missing config must fail fast, not send garbage to CLIP.
class TestEmbeddingNegative:
    def test_empty_text_raises(self) -> None:
        with pytest.raises(ValueError, match="text_data must not be empty"):
            EmbeddingsPayload(file_name="test.pdf", text_data="")

    def test_whitespace_only_text_raises(self) -> None:
        with pytest.raises(ValueError, match="text_data must not be empty"):
            EmbeddingsPayload(file_name="test.pdf", text_data="   ")

    def test_empty_file_name_raises(self) -> None:
        with pytest.raises(ValueError, match="file_name must not be empty"):
            EmbeddingsPayload(file_name="", text_data="some text")

    def test_non_string_text_raises(self) -> None:
        with pytest.raises(TypeError, match="text_data must be a string"):
            EmbeddingsPayload(file_name="test.pdf", text_data=123)  # type: ignore[arg-type]

    def test_non_payload_type_raises(self) -> None:
        with pytest.raises(TypeError, match="data must be an EmbeddingsPayload"):
            embed_text({"file_name": "test.pdf", "text_data": "text"})  # type: ignore[arg-type]


# what : Verifies _embed_pages skips OCR results with no text.
# why  : Pages with blank or whitespace-only text must not produce embeddings
#         or crash the CLIP service.
class TestEmbedPagesNegative:
    def test_empty_text_pages_produce_no_chunks(self) -> None:
        results = [
            OcrResponse(file_name="test.pdf", page_number=1, file_data={"text": ""}),
            OcrResponse(file_name="test.pdf", page_number=2, file_data={"text": "   "}),
            OcrResponse(file_name="test.pdf", page_number=3, file_data={}),
        ]
        chunks = _embed_pages(results)
        assert chunks == []

    def test_non_string_text_is_skipped(self) -> None:
        results = [
            OcrResponse(file_name="test.pdf", page_number=1, file_data={"text": 12345}),
            OcrResponse(file_name="test.pdf", page_number=2, file_data={"text": None}),
        ]
        chunks = _embed_pages(results)
        assert chunks == []


# what : Verifies start_job rejects an invalid UUID job_id.
# why  : A corrupted Redis job_id must raise WorkerJobError, not crash with a
# generic ValueError deep in the database layer.
class TestStartJobNegative:
    def test_invalid_uuid_raises(self) -> None:
        async def _test():
            with pytest.raises(WorkerJobError, match="not a valid UUID"):
                await start_job(
                    "not-a-uuid", EXISTING_MEDIA_FILE, "key", datetime.now(UTC)
                )

        _run(_test())

    def test_missing_document_raises(self) -> None:
        async def _test():
            with pytest.raises(WorkerJobError, match="does not exist"):
                await start_job(
                    str(uuid4()),
                    "ABSOLUTELY_DOES_NOT_EXIST_IN_DB.pdf",
                    _new_idem_key(),
                    datetime.now(UTC),
                )

        _run(_test())

    def test_document_mismatch_raises(self) -> None:
        """Two different documents but same job_id must raise."""

        async def _test():
            user_id = await _ensure_user()
            doc_key_a = f"test_mismatch_a_{uuid4().hex[:8]}.pdf"
            doc_key_b = f"test_mismatch_b_{uuid4().hex[:8]}.pdf"

            async with SessionLocal() as session:
                doc_a = Document(user_id=user_id, object_key=doc_key_a)
                doc_b = Document(user_id=user_id, object_key=doc_key_b)
                session.add_all([doc_a, doc_b])
                await session.commit()
                doc_a_id = doc_a.id
                doc_b_id = doc_b.id

            job_id = str(uuid4())
            # start_job for document A
            await start_job(job_id, doc_key_a, _new_idem_key(), datetime.now(UTC))

            # same job_id for document B — must raise
            with pytest.raises(WorkerJobError, match="different documents"):
                await start_job(job_id, doc_key_b, _new_idem_key(), datetime.now(UTC))

            # cleanup
            async with SessionLocal() as session:
                await session.execute(delete(Job).where(Job.id == UUID(job_id)))
                await session.execute(delete(Document).where(Document.id == doc_a_id))
                await session.execute(delete(Document).where(Document.id == doc_b_id))
                await session.commit()

        _run(_test())


# what : Verifies save_ocr and save_embeddings fail when the document row is gone.
# why  : A concurrent DELETE must produce a WorkerJobError, not a silent no-op or
#         an integrity error.
class TestSaveNegative:
    def test_save_ocr_missing_document_raises(self) -> None:
        async def _test():
            fake_doc_id = uuid4()
            with pytest.raises(WorkerJobError, match="deleted while OCR was running"):
                await save_ocr(fake_doc_id, 100, [{"page_number": 1, "text": "test"}])

        _run(_test())

    def test_save_embeddings_missing_job_raises(self) -> None:
        async def _test():
            document_id = await _ensure_document(EXISTING_MEDIA_FILE)
            fake_job_id = uuid4()

            with pytest.raises(
                WorkerJobError, match="job was deleted while processing"
            ):
                await save_embeddings(
                    fake_job_id,
                    document_id,
                    [(1, "text", "clip", [0.1, 0.2])],
                )

        _run(_test())


# what : Verifies Redis utilities reject bad inputs.
# why  : Zero or negative job_count, or empty reason strings, must be caught
#         at the Redis layer rather than producing broken queue state.
class TestRedisNegative:
    def test_fetch_zero_jobs_raises(self) -> None:
        async def _test():
            with pytest.raises(ValueError, match="job_count must be greater than zero"):
                await fetch_jobs(0)

        _run(_test())

    def test_fetch_negative_jobs_raises(self) -> None:
        async def _test():
            with pytest.raises(ValueError, match="job_count must be greater than zero"):
                await fetch_jobs(-1)

        _run(_test())

    def test_dead_letter_empty_reason_raises(self) -> None:
        async def _test():
            job = await _create_redis_job()
            with pytest.raises(ValueError, match="reason must not be empty"):
                await send_to_dead_letter_queue(job, "")

        _run(_test())

    def test_dead_letter_whitespace_reason_raises(self) -> None:
        async def _test():
            job = await _create_redis_job()
            with pytest.raises(ValueError, match="reason must not be empty"):
                await send_to_dead_letter_queue(job, "   ")

        _run(_test())


# what : Verifies process_job fails cleanly when the document is missing in the DB.
# why  : If a Redis job references a file that was never registered in PostgreSQL,
#         the worker must raise and not silently succeed.
class TestProcessJobNegative:
    def test_process_job_missing_document_raises(self) -> None:
        async def _test():
            ghost_key = f"ghost_file_{uuid4().hex[:8]}.pdf"
            job = RedisJob(
                file_name=ghost_key,
                presigned_url="https://example.com/fake",
                idem_key=_new_idem_key(),
                checksum="0" * 64,
                job_id=str(uuid4()),
                created_at=datetime.now(UTC),
            )

            with pytest.raises(WorkerJobError, match="does not exist"):
                await process_job(job)

        _run(_test())


# ═══════════════════════════════════════════════════════════════════════════
# 3. SECURITY PATCHES — exploitable flaws documented; tests commented out
#    Uncomment each test after applying the corresponding fix.
# ═══════════════════════════════════════════════════════════════════════════

# ── SECURITY-1 : Path traversal in download_files_from_s3 ─────────────────
# The download function resolves file_name inside dest_folder, but a crafted
# key with encoded path components (e.g. URL-encoded /../) or symlink races
# could bypass the is_relative_to check on some filesystems.
#
# class TestSecurityPathTraversal:
#     def test_encoded_traversal_is_blocked(self) -> None:
#         """URL-encoded /../ in file_name must not escape dest_folder."""
#         from readforge.utils.reading_util import download_files_from_s3
#         import tempfile
#
#         with tempfile.TemporaryDirectory() as tmpdir:
#             with pytest.raises(ValueError, match="must stay inside"):
#                 download_files_from_s3("..%2F..%2Fetc%2Fpasswd", tmpdir)
#
#     def test_double_dot_traversal_is_blocked(self) -> None:
#         """Literal ../../ in file_name must not escape dest_folder."""
#         from readforge.utils.reading_util import download_files_from_s3
#         import tempfile
#
#         with tempfile.TemporaryDirectory() as tmpdir:
#             with pytest.raises(ValueError, match="must stay inside"):
#                 download_files_from_s3("../../etc/passwd", tmpdir)

# ── SECURITY-2 : No authentication on the worker loop ─────────────────────
# The worker trusts any job it pulls from Redis. A compromised Redis lets an
# attacker enqueue arbitrary file_name values that the worker will download,
# OCR, and store without validating the caller's identity or permissions.
#
# class TestSecurityWorkerAuth:
#     def test_worker_rejects_unsigned_jobs(self) -> None:
#         """Jobs without a valid HMAC signature must be rejected."""
#         async def _test():
#             job = RedisJob(
#                 file_name=EXISTING_MEDIA_FILE,
#                 presigned_url="https://example.com/fake",
#                 idem_key=_new_idem_key(),
#                 job_id=str(uuid4()),
#                 created_at=datetime.now(UTC),
#             )
#             # After the fix, process_job should verify a signature field
#             with pytest.raises(Exception, match="signature"):
#                 await process_job(job)
#         _run(_test())

# ── SECURITY-3 : Unrestricted file type processing ────────────────────────
# The worker downloads and OCRs any object key from R2 without validating
# the content type or file extension. An attacker could enqueue a .exe, .zip,
# or polyglot file that causes unexpected behaviour in Quartz/Vision.
#
# class TestSecurityFileTypeValidation:
#     def test_non_pdf_content_type_is_rejected(self) -> None:
#         """Files with non-PDF content types must not enter the OCR pipeline."""
#         async def _test():
#             job = RedisJob(
#                 file_name="malicious.exe",
#                 presigned_url="https://example.com/fake",
#                 idem_key=_new_idem_key(),
#                 job_id=str(uuid4()),
#                 created_at=datetime.now(UTC),
#             )
#             with pytest.raises(Exception, match="content.type|unsupported"):
#                 await process_job(job)
#         _run(_test())
#
#     def test_non_pdf_extension_is_rejected(self) -> None:
#         """Object keys without .pdf extension must be refused."""
#         with pytest.raises(ValueError, match="file type"):
#             get_file_size("payload.html")

# ── SECURITY-4 : SSRF via presigned URL ───────────────────────────────────
# The presigned_url field is stored but not validated. If the worker ever
# follows it (or if it leaks to another service), an attacker can point it
# to an internal service endpoint (e.g. http://169.254.169.254/metadata).
#
# class TestSecuritySSRF:
#     def test_presigned_url_internal_ip_is_rejected(self) -> None:
#         """Presigned URLs targeting internal IPs must be blocked."""
#         async def _test():
#             with pytest.raises(ValueError, match="internal|private"):
#                 await create_job(
#                     RedisJobRequest(
#                         file_name=EXISTING_MEDIA_FILE,
#                         presigned_url="http://169.254.169.254/latest/meta-data/",
#                         idem_key=_new_idem_key(),
#                     )
#                 )
#         _run(_test())
#
#     def test_presigned_url_localhost_is_rejected(self) -> None:
#         """Presigned URLs targeting localhost must be blocked."""
#         async def _test():
#             with pytest.raises(ValueError, match="internal|private"):
#                 await create_job(
#                     RedisJobRequest(
#                         file_name=EXISTING_MEDIA_FILE,
#                         presigned_url="http://localhost:6379/",
#                         idem_key=_new_idem_key(),
#                     )
#                 )
#         _run(_test())

# ── SECURITY-5 : Unbounded PDF page count / pixel bomb ────────────────────
# The worker renders every page of a PDF at 2× scale with no upper bound on
# page count. A crafted PDF with thousands of large pages can exhaust memory
# and crash the worker (denial of service).
#
# class TestSecurityResourceExhaustion:
#     def test_excessive_page_count_is_capped(self) -> None:
#         """PDFs with more than MAX_PAGES pages must be rejected."""
#         # After the fix, download_page_from_pdf should enforce a page limit
#         # (e.g. MAX_PAGES = 500) and raise PDFReadError for documents exceeding it.
#         pass  # Requires a crafted test PDF with >500 blank pages
#
#     def test_pixel_bomb_page_is_rejected(self) -> None:
#         """A single page that exceeds max_image_pixels must raise."""
#         # This is already partially handled by max_image_pixels, but the
#         # default (20M pixels) at 2× scale allows ~5000×2000pt pages which
#         # each allocate ~80 MB of bitmap RAM. A tighter default or per-job
#         # limit should be enforced.
#         pass

# ── SECURITY-6 : Redis key injection via idem_key ─────────────────────────
# The idempotency key is interpolated directly into Redis key strings.
# A crafted idem_key containing Redis protocol characters (e.g. newlines,
# null bytes) can corrupt key layout or collide with internal namespaces.
#
# class TestSecurityRedisKeyInjection:
#     def test_idem_key_with_newlines_is_rejected(self) -> None:
#         """Idempotency keys with newline characters must be rejected."""
#         async def _test():
#             with pytest.raises((ValueError, Exception)):
#                 await create_job(
#                     RedisJobRequest(
#                         file_name=EXISTING_MEDIA_FILE,
#                         presigned_url="https://example.com/test",
#                         idem_key="key\r\nINJECTED",
#                     )
#                 )
#         _run(_test())
#
#     def test_idem_key_with_null_bytes_is_rejected(self) -> None:
#         """Idempotency keys with null bytes must be rejected."""
#         async def _test():
#             with pytest.raises((ValueError, Exception)):
#                 await create_job(
#                     RedisJobRequest(
#                         file_name=EXISTING_MEDIA_FILE,
#                         presigned_url="https://example.com/test",
#                         idem_key="key\x00INJECTED",
#                     )
#                 )
#         _run(_test())

# ── SECURITY-7 : Embedding service response injection ────────────────────
# embed_text validates vector contents but trusts the outer JSON structure.
# A compromised or misconfigured embedding service could return extra fields
# (e.g. overwriting model metadata) that propagate to pgvector storage.
#
# class TestSecurityEmbeddingResponseInjection:
#     def test_extra_fields_in_embedding_response_are_ignored(self) -> None:
#         """Only the 'vector' field from the embedding response must be used."""
#         # After the fix, embed_text should reject responses with unexpected
#         # top-level keys or nested objects that could influence storage.
#         pass

# ── SECURITY-8 : Log injection via file_name ──────────────────────────────
# The worker logs job failures with the file_name directly interpolated into
# log messages. A crafted file_name containing newlines or ANSI escape codes
# can forge multiline log entries or corrupt terminal output.
#
# class TestSecurityLogInjection:
#     def test_file_name_with_newlines_is_sanitised_in_logs(self) -> None:
#         """File names with newlines must be sanitised before logging."""
#         import logging
#         from io import StringIO
#
#         handler = logging.StreamHandler(StringIO())
#         logger = logging.getLogger("readforge.worker")
#         logger.addHandler(handler)
#
#         async def _test():
#             job = RedisJob(
#                 file_name="legit.pdf\nINJECTED: admin logged in",
#                 presigned_url="https://example.com/fake",
#                 idem_key=_new_idem_key(),
#                 job_id=str(uuid4()),
#                 created_at=datetime.now(UTC),
#             )
#             try:
#                 await process_job(job)
#             except Exception:
#                 pass
#
#         _run(_test())
#
#         output = handler.stream.getvalue()
#         # After the fix, the log output must not contain the raw injected line
#         assert "INJECTED: admin logged in" not in output.split("\n")[0]
#         logger.removeHandler(handler)

# ── SECURITY-9 : No job timeout / runaway worker ──────────────────────────
# process_job has no timeout. A PDF that causes Quartz or Vision to hang
# (e.g. infinite-loop font parsing) will block the worker forever, preventing
# all other jobs from being processed.
#
# class TestSecurityJobTimeout:
#     def test_process_job_respects_timeout(self) -> None:
#         """Jobs exceeding MAX_JOB_SECONDS must be cancelled and failed."""
#         # After the fix, process_job should wrap its work in
#         # asyncio.wait_for(coro, timeout=MAX_JOB_SECONDS) and call
#         # fail_job on TimeoutError.
#         pass

# ── SECURITY-10 : R2 credentials in environment without rotation ──────────
# The R2 client reads R2_ACCESS_KEY and R2_SECRET_ACCESS_KEY from
# the environment once at import time (via load_dotenv). There is no
# credential rotation, expiry checking, or vault integration. Leaked .env
# files grant permanent bucket access.
#
# class TestSecurityCredentialRotation:
#     def test_r2_client_rejects_expired_credentials(self) -> None:
#         """Stale credentials must trigger a clear error, not silent failures."""
#         # After the fix, _r2_client should check credential age or
#         # integrate with a secrets manager that rotates keys.
#         pass
