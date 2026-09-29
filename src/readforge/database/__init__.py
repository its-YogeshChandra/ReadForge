"""Shared asynchronous SQLAlchemy setup for PostgreSQL."""

import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://readforge:readforge@localhost:5432/readforge",
)

engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def close_database() -> None:
    await engine.dispose()
