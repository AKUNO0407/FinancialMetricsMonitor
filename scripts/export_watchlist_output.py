"""Export watchlist output as JSON for quick inspection.

Usage examples:
    # 1) Preview portfolio directly from builder (may call Yahoo Screener when --full-refresh)
    python scripts/export_watchlist_output.py --source build --full-refresh --limit 100 --pretty

    # 2) Read active portfolio from DB table watchlist
    python scripts/export_watchlist_output.py --source db --limit 200 --pretty

    # 3) Save to file
    python scripts/export_watchlist_output.py --source db --out watchlist_output.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.db import get_engine
from etl.watchlist import _build_rows, _load_config


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        aliases = row.get("aliases") or []
        if isinstance(aliases, tuple):
            aliases = list(aliases)
        normalized.append(
            {
                "ticker": row.get("ticker"),
                "name": row.get("name"),
                "is_public": bool(row.get("is_public", True)),
                "gics_sub_industry": row.get("gics_sub_industry"),
                "ai_segment": row.get("ai_segment"),
                "ai_exposure_level": row.get("ai_exposure_level"),
                "ai_high_relevance": row.get("ai_high_relevance"),
                "ai_relevance_tag": row.get("ai_relevance_tag"),
                "is_manual_override": bool(row.get("is_manual_override", False)),
                "active_flag": bool(row.get("active_flag", True)),
                "aliases": aliases,
            }
        )
    return normalized


def _from_db(limit: int | None = None) -> list[dict[str, Any]]:
    engine = get_engine()
    sql = """
        SELECT
            ticker,
            name,
            is_public,
            gics_sub_industry,
            ai_segment,
            ai_exposure_level,
            ai_high_relevance,
            ai_relevance_tag,
            is_manual_override,
            active_flag,
            aliases
        FROM watchlist
        WHERE active_flag = TRUE
        ORDER BY is_public DESC, ticker ASC
    """
    if limit:
        sql += "\nLIMIT :limit"

    with engine.connect() as conn:
        result = conn.execute(text(sql), {"limit": limit} if limit else {}).mappings().all()
    return [dict(r) for r in result]


def _from_builder(full_refresh: bool) -> list[dict[str, Any]]:
    cfg = _load_config()
    return _build_rows(cfg, full_refresh=full_refresh)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export watchlist as JSON")
    parser.add_argument("--source", choices=["build", "db"], default="db")
    parser.add_argument("--full-refresh", action="store_true", help="Only applies to --source build")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None, help="Optional output json file path")
    parser.add_argument("--pretty", action="store_true")

    args = parser.parse_args()

    rows = _from_builder(args.full_refresh) if args.source == "build" else _from_db(args.limit)
    rows = _normalize_rows(rows)

    if args.limit:
        rows = rows[: args.limit]

    payload = {
        "count": len(rows),
        "public_count": sum(1 for r in rows if r["is_public"]),
        "private_count": sum(1 for r in rows if not r["is_public"]),
        "items": rows,
    }

    text_out = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.out:
        args.out.write_text(text_out, encoding="utf-8")
        print(f"Saved: {args.out}")
    else:
        print(text_out)


if __name__ == "__main__":
    main()
