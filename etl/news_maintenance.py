"""News storage maintenance: dedupe + retention cleanup.

Default policy:
- Deduplicate legacy duplicates by article_url (keep earliest article_id)
- Delete news older than RETENTION_DAYS (default 200)
- Delete dependent/orphan summaries
"""
from __future__ import annotations

import os

from sqlalchemy import text

from etl.db import get_engine


def _ensure_indexes(conn) -> None:
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_news_raw_published_date ON news_raw (published_date)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_news_raw_fetched_at ON news_raw (fetched_at)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_news_raw_ai_relevance_flag ON news_raw (ai_relevance_flag)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_news_summary_article_id ON news_summary (article_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_news_summary_fetched_at ON news_summary (fetched_at)"))


def _dedupe_news(conn) -> tuple[int, int]:
    duplicate_ids = conn.execute(
        text(
            """
            WITH ranked AS (
                SELECT
                    article_id,
                    ROW_NUMBER() OVER (PARTITION BY article_url ORDER BY article_id ASC) AS rn
                FROM news_raw
            )
            SELECT article_id
            FROM ranked
            WHERE rn > 1
            """
        )
    ).scalars().all()

    if not duplicate_ids:
        return 0, 0

    deleted_summaries = conn.execute(
        text("DELETE FROM news_summary WHERE article_id = ANY(:ids)"),
        {"ids": duplicate_ids},
    ).rowcount or 0

    deleted_raw = conn.execute(
        text("DELETE FROM news_raw WHERE article_id = ANY(:ids)"),
        {"ids": duplicate_ids},
    ).rowcount or 0

    return deleted_raw, deleted_summaries


def _cleanup_old_news(conn, retention_days: int) -> tuple[int, int, int]:
    old_raw_ids = conn.execute(
        text(
            """
            SELECT article_id
            FROM news_raw
            WHERE COALESCE(published_date, fetched_at) < now() - make_interval(days => :days)
            """
        ),
        {"days": retention_days},
    ).scalars().all()

    deleted_old_summaries = 0
    deleted_old_raw = 0

    if old_raw_ids:
        deleted_old_summaries = conn.execute(
            text("DELETE FROM news_summary WHERE article_id = ANY(:ids)"),
            {"ids": old_raw_ids},
        ).rowcount or 0

        deleted_old_raw = conn.execute(
            text("DELETE FROM news_raw WHERE article_id = ANY(:ids)"),
            {"ids": old_raw_ids},
        ).rowcount or 0

    deleted_orphan_summaries = conn.execute(
        text(
            """
            DELETE FROM news_summary ns
            WHERE ns.fetched_at < now() - make_interval(days => :days)
              AND (
                    ns.article_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1
                        FROM news_raw nr
                        WHERE nr.article_id = ns.article_id
                    )
              )
            """
        ),
        {"days": retention_days},
    ).rowcount or 0

    return deleted_old_raw, deleted_old_summaries, deleted_orphan_summaries


def run(retention_days: int | None = None) -> int:
    retention_days = retention_days or int(os.environ.get("NEWS_RETENTION_DAYS", "200"))

    engine = get_engine()
    with engine.begin() as conn:
        _ensure_indexes(conn)
        dedup_raw, dedup_summary = _dedupe_news(conn)
        old_raw, old_summary, orphan_summary = _cleanup_old_news(conn, retention_days)

    # rows_affected-like return for orchestrator logging
    return dedup_raw + dedup_summary + old_raw + old_summary + orphan_summary


if __name__ == "__main__":
    affected = run()
    print(f"news_maintenance rows_affected={affected}")
