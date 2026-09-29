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
    }
    assert isinstance(tables["documents"].c.ocr_result.type, JSONB)
    assert isinstance(tables["document_chunks"].c.embedding.type, Vector)
    document_key = next(
        iter(tables["document_chunks"].c.document_id.foreign_keys)
    )
    assert document_key.target_fullname == "documents.id"
