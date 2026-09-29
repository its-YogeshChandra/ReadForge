"""Explicit Alembic migration command for startup/deployment scripts."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from readforge.database import DATABASE_URL


def run_migrations() -> None:
    project_root = Path(__file__).resolve().parents[3]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    command.upgrade(config, "head")


def main() -> None:
    run_migrations()
