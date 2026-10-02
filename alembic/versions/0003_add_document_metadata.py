"""Add EOC plan metadata to documents.

Revision ID: 0003_add_document_metadata
Revises: 0002_add_conversations
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_document_metadata"
down_revision: str | Sequence[str] | None = "0002_add_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("insurer", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("plan_name", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("plan_type", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("jurisdiction_state", sa.Text(), nullable=True),
    )
    op.add_column("documents", sa.Column("coverage_year", sa.Integer(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("effective_start", sa.Date(), nullable=True),
    )
    op.add_column("documents", sa.Column("effective_end", sa.Date(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "document_type",
            sa.Text(),
            server_default=sa.text("'eoc'"),
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "source_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "documents_coverage_year_valid",
        "documents",
        "coverage_year IS NULL OR coverage_year BETWEEN 2000 AND 2100",
    )
    op.create_check_constraint(
        "documents_effective_dates_valid",
        "documents",
        "effective_start IS NULL OR effective_end IS NULL "
        "OR effective_start <= effective_end",
    )


def downgrade() -> None:
    op.drop_constraint(
        "documents_effective_dates_valid",
        "documents",
        type_="check",
    )
    op.drop_constraint(
        "documents_coverage_year_valid",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "source_verified")
    op.drop_column("documents", "document_type")
    op.drop_column("documents", "effective_end")
    op.drop_column("documents", "effective_start")
    op.drop_column("documents", "coverage_year")
    op.drop_column("documents", "jurisdiction_state")
    op.drop_column("documents", "plan_type")
    op.drop_column("documents", "plan_name")
    op.drop_column("documents", "insurer")
