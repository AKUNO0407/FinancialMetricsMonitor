"""Manual AI infrastructure watchlist loader.

This job uses a curated YAML source-of-truth instead of screeners.
It keeps `etl/TBD_watchlist.py` untouched and provides a deterministic
manual portfolio pipeline.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy import text

from etl.db import get_engine


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "manual_ai_infra_watchlist.yaml"
ALLOWED_EXPOSURE = {"Core", "Significant", "Adjacent", "None"}


def _load_manual_companies(config_path: Path = CONFIG_PATH) -> list[dict]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    companies = payload.get("companies") or []
    if not isinstance(companies, list):
        raise ValueError("manual_ai_infra_watchlist.yaml -> companies must be a list")
    return companies


def _normalize_company(row: dict) -> dict:
    ticker = str(row.get("ticker", "")).strip().upper()
    name = str(row.get("name", "")).strip()
    if not ticker or not name:
        raise ValueError(f"Invalid company row (ticker/name required): {row}")

    ai_exposure_level = row.get("ai_exposure_level")
    if ai_exposure_level not in ALLOWED_EXPOSURE:
        raise ValueError(
            f"Invalid ai_exposure_level '{ai_exposure_level}' for {ticker}; "
            f"must be one of {sorted(ALLOWED_EXPOSURE)}"
        )

    aliases = [
    alias
    for alias in (row.get("aliases") or [])
    if alias
    and alias.strip().upper() != row["ticker"].strip().upper()
    and alias.strip().casefold() != row["name"].strip().casefold()
    ] #list(dict.fromkeys([name, ticker, *(row.get("aliases") or [])]))
    is_public = bool(row.get("is_public", not ticker.startswith("PRIV:")))
    if_retrieve_price = bool(row.get("if_retrieve_price", is_public))
    if_retrieve_news = bool(row.get("if_retrieve_news", True))
    active_flag = bool(
        row.get("active_flag", True)
    )

    return {
        "ticker": ticker,
        "name": name,
        "aliases": aliases,
        "gics_code": row.get("gics_code"),
        "gics_sub_industry": row.get("gics_sub_industry"),
        "ai_segment": row.get("ai_segment"),
        "ai_exposure_level": ai_exposure_level,
        "ai_high_relevance": row.get("ai_high_relevance", True),
        "ai_relevance_tag": row.get("ai_relevance_tag", "manual_curated"),
        "is_manual_override": True,
        "is_public": is_public,
        "if_retrieve_price": if_retrieve_price,
        "if_retrieve_news": if_retrieve_news,
        "active_flag": active_flag,
    }


def _build_rows(config_path: Path = CONFIG_PATH) -> list[dict]:
    raw = _load_manual_companies(config_path=config_path)
    rows = [_normalize_company(r) for r in raw]
    dedup = {}
    for row in rows:
        dedup[row["ticker"]] = row
    return list(dedup.values())


def run() -> int:
    rows = _build_rows()
    keep_tickers = [r["ticker"] for r in rows]

    engine = get_engine()
    upserted = 0
    with engine.begin() as conn:
        for r in rows:
            result = conn.execute(
                text(
                    """
                    INSERT INTO watchlist (
                        ticker, name, aliases, gics_code, gics_sub_industry,
                        ai_segment, ai_exposure_level, ai_high_relevance, ai_relevance_tag,
                        is_manual_override, is_public, if_retrieve_price, if_retrieve_news, active_flag
                    )
                    VALUES (
                        :ticker, :name, :aliases, :gics_code, :gics_sub_industry,
                        :ai_segment, :ai_exposure_level, :ai_high_relevance, :ai_relevance_tag,
                        :is_manual_override, :is_public, :if_retrieve_price, :if_retrieve_news, :active_flag
                    )
                    ON CONFLICT (ticker) DO UPDATE SET
                        name = EXCLUDED.name,
                        aliases = EXCLUDED.aliases,
                        gics_code = EXCLUDED.gics_code,
                        gics_sub_industry = EXCLUDED.gics_sub_industry,
                        ai_segment = EXCLUDED.ai_segment,
                        ai_exposure_level = EXCLUDED.ai_exposure_level,
                        ai_high_relevance = EXCLUDED.ai_high_relevance,
                        ai_relevance_tag = EXCLUDED.ai_relevance_tag,
                        is_manual_override = EXCLUDED.is_manual_override,
                        is_public = EXCLUDED.is_public,
                        if_retrieve_price = EXCLUDED.if_retrieve_price,
                        if_retrieve_news = EXCLUDED.if_retrieve_news,
                        active_flag = EXCLUDED.active_flag
                    """
                ),
                r,
            )
            upserted += result.rowcount

        conn.execute(
            text(
                """
                UPDATE watchlist
                SET active_flag = FALSE
                WHERE ticker <> ALL(:keep_tickers)
                """
            ),
            {"keep_tickers": keep_tickers},
        )

    log.info("Manual watchlist loaded: %d rows (source=%s)", len(rows), CONFIG_PATH.name)
    return upserted


if __name__ == "__main__":
    run()
