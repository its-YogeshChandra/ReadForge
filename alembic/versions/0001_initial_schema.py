"""Create the initial ReadForge schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-30
"""

from collections.abc import Sequence
from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.CheckConstraint("btrim(username) <> ''", name="users_username_not_empty"),
        sa.CheckConstraint("btrim(email) <> ''", name="users_email_not_empty"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "users_username_unique",
        "users",
        [sa.literal_column("lower(username)")],
        unique=True,
    )
    op.create_index(
        "users_email_unique",
        "users",
        [sa.literal_column("lower(email)")],
        unique=True,
    )

    op.create_table(
        "documents",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ocr_result", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(object_key) <> ''", name="documents_object_key_not_empty"
        ),
        sa.CheckConstraint("size_bytes >= 0", name="documents_size_bytes_valid"),
        sa.CheckConstraint("page_count > 0", name="documents_page_count_valid"),
        sa.CheckConstraint(
            "ocr_result IS NULL OR jsonb_typeof(ocr_result) = 'array'",
            name="documents_ocr_result_valid",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )

    op.create_table(
        "jobs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column(
            "attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(btrim(idempotency_key)) BETWEEN 1 AND 20",
            name="jobs_idempotency_key_valid",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="jobs_status_valid",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="jobs_attempt_count_valid"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "idempotency_key",
            name="jobs_document_idempotency_unique",
        ),
    )
    op.create_index(
        "jobs_pending_idx",
        "jobs",
        ["status", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'processing')"),
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name="document_chunks_index_valid"),
        sa.CheckConstraint("page_number > 0", name="document_chunks_page_number_valid"),
        sa.CheckConstraint(
            "btrim(content) <> ''", name="document_chunks_content_not_empty"
        ),
        sa.CheckConstraint(
            "btrim(embedding_model) <> ''",
            name="document_chunks_embedding_model_not_empty",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "page_number",
            "chunk_index",
            name="document_chunks_position_unique",
        ),
    )
    op.create_index(
        "document_chunks_page_idx",
        "document_chunks",
        ["document_id", "page_number"],
    )


def downgrade() -> None:
    op.drop_index("document_chunks_page_idx", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("jobs_pending_idx", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("documents")
    op.drop_index("users_email_unique", table_name="users")
    op.drop_index("users_username_unique", table_name="users")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
