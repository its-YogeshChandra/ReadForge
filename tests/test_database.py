"""Small checks for the SQLAlchemy schema without requiring PostgreSQL."""

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from readforge.database.schema import Base


def test_database_schema_contains_ocr_and_vector_tables() -> None:
    tables = Base.metadata.tables

    assert set(tables) == {
        "users",
        "documents",
        "jobs",
        "document_chunks",
        "conversations",
    }
    assert isinstance(tables["documents"].c.ocr_result.type, JSONB)
    assert {
        "insurer",
        "plan_name",
        "plan_type",
        "jurisdiction_state",
        "coverage_year",
        "effective_start",
        "effective_end",
        "document_type",
        "source_verified",
    }.issubset(tables["documents"].c.keys())
    assert isinstance(tables["document_chunks"].c.embedding.type, Vector)
    assert isinstance(tables["conversations"].c.messages.type, JSONB)
    document_key = next(
        iter(tables["document_chunks"].c.document_id.foreign_keys)
    )
    assert document_key.target_fullname == "documents.id"
    conversation_document_key = next(
        iter(tables["conversations"].c.document_id.foreign_keys)
    )
    assert conversation_document_key.target_fullname == "documents.id"
