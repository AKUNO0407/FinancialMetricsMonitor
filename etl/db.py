"""Shared DB engine helper. All ETL jobs import `get_engine()` from here."""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

load_dotenv()

_engine: Engine | None = None


def _normalize_database_url(database_url: str) -> str:
    """Normalize DATABASE_URL and prefer psycopg v3 driver for stability on Windows."""
    url = (database_url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        database_url = _normalize_database_url(os.environ["DATABASE_URL"])
        _engine = create_engine(database_url, pool_pre_ping=True)
    return _engine
