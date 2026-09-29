"""Small checks for the SQLAlchemy schema without requiring PostgreSQL."""

from pgvector.sqlalchemy import Vector

from readforge.database.schema import Base


def test_database_schema_contains_ocr_and_vector_tables() -> None:
    tables = Base.metadata.tables

    assert set(tables) == {
        "users",
        "documents",
        "jobs",
        "document_pages",
        "document_chunks",
    }
    assert isinstance(tables["document_chunks"].c.embedding.type, Vector)
    assert {
        column.name for column in tables["document_pages"].primary_key.columns
    } == {"document_id", "page_number"}
