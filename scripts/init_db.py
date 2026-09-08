"""
Create/verify all tables in the hosted Postgres instance using db/schema.sql.

Usage:
    python scripts/init_db.py

Reads DATABASE_URL from .env (see .env.example).
"""
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import os

load_dotenv()

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _table_exists(conn, table_name: str) -> bool:
    return bool(
        conn.execute(
            text(
                """ 
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :table_name
                LIMIT 1
                """
            ),
            {"table_name": table_name},
        ).scalar()
    )


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = :column_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar()
    )


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with engine.begin() as conn:
        pre_existing_watchlist = _table_exists(conn, "watchlist")
        pre_has_high_relevance = _column_exists(conn, "watchlist", "ai_high_relevance") if pre_existing_watchlist else False
        pre_has_relevance_tag = _column_exists(conn, "watchlist", "ai_relevance_tag") if pre_existing_watchlist else False

        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))

        post_existing_watchlist = _table_exists(conn, "watchlist")
        post_has_high_relevance = _column_exists(conn, "watchlist", "ai_high_relevance")
        post_has_relevance_tag = _column_exists(conn, "watchlist", "ai_relevance_tag")

    print("Schema apply completed (idempotent mode).")
    if pre_existing_watchlist:
        print("- watchlist table already existed: no CREATE failure expected (IF NOT EXISTS).")
    else:
        print("- watchlist table created.")

    if not pre_has_high_relevance and post_has_high_relevance:
        print("- column added: watchlist.ai_high_relevance")
    elif post_has_high_relevance:
        print("- column already present: watchlist.ai_high_relevance")

    if not pre_has_relevance_tag and post_has_relevance_tag:
        print("- column added: watchlist.ai_relevance_tag")
    elif post_has_relevance_tag:
        print("- column already present: watchlist.ai_relevance_tag")

    if not post_existing_watchlist:
        print("- warning: watchlist table not found after apply.")


if __name__ == "__main__":
    main()
