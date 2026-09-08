"""Maintain news storage with deduplication and retention cleanup.

This script is idempotent and safe to run daily.

What it does:
1) Ensure key news indexes exist.
2) Deduplicate legacy duplicate rows by article_url (keep smallest article_id).
3) Delete news older than retention days (default 200), including dependent summaries.
4) Delete orphan summaries older than retention days.

Usage:
    python scripts/maintain_news_storage.py
    python scripts/maintain_news_storage.py --retention-days 200
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.news_maintenance import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate and clean old news data")
    parser.add_argument("--retention-days", type=int, default=200)
    args = parser.parse_args()

    affected = run(retention_days=args.retention_days)
    print("maintenance_done", {"retention_days": args.retention_days, "rows_affected": affected})


if __name__ == "__main__":
    main()
