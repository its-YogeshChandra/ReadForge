"""Persist document and job checksums and allow anonymous documents.

Revision ID: 0004_add_integrity_checksums
Revises: 0003_add_document_metadata
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_add_integrity_checksums"
down_revision: str | Sequence[str] | None = "0003_add_document_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("documents", "user_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("documents", sa.Column("checksum", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("checksum", sa.Text(), nullable=True))
    op.create_check_constraint(
        "documents_checksum_valid",
        "documents",
        "checksum IS NULL OR checksum ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "jobs_checksum_valid",
        "jobs",
        "checksum IS NULL OR checksum ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint("jobs_checksum_valid", "jobs", type_="check")
    op.drop_constraint("documents_checksum_valid", "documents", type_="check")
    op.drop_column("jobs", "checksum")
    op.drop_column("documents", "checksum")
    op.alter_column("documents", "user_id", existing_type=sa.Uuid(), nullable=False)
