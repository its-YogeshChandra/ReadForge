"""SQLAlchemy models for documents, OCR output, jobs, and embeddings."""

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("btrim(username) <> ''", name="users_username_not_empty"),
        CheckConstraint("btrim(email) <> ''", name="users_email_not_empty"),
        Index("users_username_unique", func.lower(text("username")), unique=True),
        Index("users_email_unique", func.lower(text("email")), unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    username: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "btrim(object_key) <> ''", name="documents_object_key_not_empty"
        ),
        CheckConstraint("size_bytes >= 0", name="documents_size_bytes_valid"),
        CheckConstraint("page_count > 0", name="documents_page_count_valid"),
        CheckConstraint(
            "ocr_result IS NULL OR jsonb_typeof(ocr_result) = 'array'",
            name="documents_ocr_result_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_result: Mapped[list[dict] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "octet_length(btrim(idempotency_key)) BETWEEN 1 AND 20",
            name="jobs_idempotency_key_valid",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="jobs_status_valid",
        ),
        CheckConstraint("attempt_count >= 0", name="jobs_attempt_count_valid"),
        UniqueConstraint(
            "document_id", "idempotency_key", name="jobs_document_idempotency_unique"
        ),
        Index(
            "jobs_pending_idx",
            "status",
            "created_at",
            postgresql_where=text("status IN ('queued', 'processing')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    idempotency_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="document_chunks_index_valid"),
        CheckConstraint("page_number > 0", name="document_chunks_page_number_valid"),
        CheckConstraint(
            "btrim(content) <> ''", name="document_chunks_content_not_empty"
        ),
        CheckConstraint(
            "btrim(embedding_model) <> ''",
            name="document_chunks_embedding_model_not_empty",
        ),
        UniqueConstraint(
            "document_id",
            "page_number",
            "chunk_index",
            name="document_chunks_position_unique",
        ),
        Index("document_chunks_page_idx", "document_id", "page_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(Text)
    # ponytail: unconstrained until the embedding model fixes its dimension;
    # change to Vector(N) and add HNSW when approximate search is needed.
    embedding: Mapped[list[float]] = mapped_column(Vector())
