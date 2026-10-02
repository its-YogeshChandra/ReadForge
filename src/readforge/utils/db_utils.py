"""Database operations used by the document worker."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select

from readforge.database import SessionLocal
from readforge.database.schema import Conversation, Document, DocumentChunk, Job


class WorkerJobError(RuntimeError):
    """A queued job cannot be persisted safely."""


class ConversationNotFoundError(LookupError):
    """The requested conversation does not exist."""


class ConversationDocumentMismatchError(ValueError):
    """A conversation belongs to a different document."""


async def append_conversation_messages(
    document_id: UUID,
    conversation_id: UUID | None,
    messages: list[dict],
) -> UUID:
    """Create a conversation or atomically append messages to one."""
    async with SessionLocal() as session:
        if conversation_id is None:
            conversation = Conversation(
                document_id=document_id,
                messages=list(messages),
            )
            session.add(conversation)
        else:
            conversation = await session.scalar(
                select(Conversation)
                .where(Conversation.id == conversation_id)
                .with_for_update()
            )
            if conversation is None:
                raise ConversationNotFoundError("Conversation was not found")
            if conversation.document_id != document_id:
                raise ConversationDocumentMismatchError(
                    "Conversation belongs to a different document"
                )
            conversation.messages.extend(messages)

        await session.commit()
        return conversation.id


async def load_conversation_messages(
    document_id: UUID,
    conversation_id: UUID | None,
) -> list[dict]:
    """Load a conversation after confirming that it belongs to the document."""
    if conversation_id is None:
        return []

    async with SessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError("Conversation was not found")
        if conversation.document_id != document_id:
            raise ConversationDocumentMismatchError(
                "Conversation belongs to a different document"
            )
        return list(conversation.messages)


async def start_job(
    job_id: str,
    object_key: str,
    idempotency_key: str,
    created_at: datetime,
) -> tuple[UUID, UUID] | None:
    """Mark a database job as processing and return its IDs."""
    try:
        parsed_job_id = UUID(job_id)
    except ValueError as error:
        raise WorkerJobError("Redis job_id is not a valid UUID") from error

    async with SessionLocal() as session:
        document = await session.scalar(
            select(Document).where(Document.object_key == object_key)
        )
        if document is None:
            raise WorkerJobError(
                f"Document '{object_key}' does not exist in PostgreSQL"
            )

        database_job = await session.get(Job, parsed_job_id)
        if database_job is not None and database_job.status == "completed":
            return None
        if database_job is None:
            database_job = Job(
                id=parsed_job_id,
                document_id=document.id,
                idempotency_key=idempotency_key,
                attempt_count=0,
                created_at=created_at,
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
        return parsed_job_id, document.id


async def save_ocr(
    document_id: UUID,
    size_bytes: int,
    ocr_result: list[dict],
) -> None:
    """Store document metadata and page OCR JSON."""
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise WorkerJobError("Document was deleted while OCR was running")
        document.content_type = "application/pdf"
        document.size_bytes = size_bytes
        document.page_count = len(ocr_result)
        document.ocr_result = ocr_result
        await session.commit()


async def save_embeddings(
    job_id: UUID,
    document_id: UUID,
    chunks: list[tuple[int, str, str, list[float]]],
) -> None:
    """Replace a document's chunks and mark its job completed."""
    async with SessionLocal() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        session.add_all(
            DocumentChunk(
                document_id=document_id,
                page_number=page_number,
                chunk_index=0,
                content=content,
                embedding_model=model,
                embedding=embedding,
            )
            for page_number, content, model, embedding in chunks
        )
        database_job = await session.get(Job, job_id)
        if database_job is None:
            raise WorkerJobError("Database job was deleted while processing")
        database_job.status = "completed"
        database_job.completed_at = datetime.now(UTC)
        await session.commit()


async def fail_job(job_id: str, reason: str) -> None:
    """Mark an existing database job as failed."""
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
