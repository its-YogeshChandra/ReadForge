"""Location of the SQL schema used to initialize PostgreSQL."""

from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
