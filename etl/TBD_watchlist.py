"""
Watchlist Resolution job.

Rebuilds the active watchlist from the GICS sub-industry pre-filter
(config/ai_exposure.yaml -> gics_sub_industries) plus manual_overrides,
refreshes ai_segment / ai_exposure_level, and refreshes each ticker's
`aliases` list used for headline matching in news_scraper.py.

TODO:
    - load config/ai_exposure.yaml
    - query GICS sub-industry membership (external data source TBD - e.g.
      a static universe file, or a paid/free reference data API)
    - merge with manual_overrides
    - upsert into `watchlist` table
    - flag newly added/removed names for auditability (diff vs previous run)

2026-08-31: 
    Implement watchlist ETL job; sector/industry from yfinance
    Public universe: yfinance Equity Screener 按 Yahoo industry 全市场筛选
    （不限指数成分股），region + min_market_cap 可控。
    Private companies: config/ai_exposure.yaml -> private_companies（仅新闻匹配用）。

    注意：screener 有 rate limit，全量刷新建议每周一次（WATCHLIST_FULL_REFRESH=1
    或距上次刷新 >7 天时才跑 screener，否则只应用 manual_overrides/private）。
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
from pathlib import Path

import yaml
import yfinance as yf
from sqlalchemy import text
from yfinance import EquityQuery

from etl.db import get_engine


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "ai_exposure.yaml"
PAGE_SIZE = 250  # yahoo screener 单页上限

# yfinance 1.x screener often accepts broad sector labels but may reject detailed industry labels.
SCOPE_TO_SECTOR_FALLBACK = {
    "Software - Application": "Technology",
    "Software - Infrastructure": "Technology",
    "Information Technology Services": "Technology",
    "Communication Equipment": "Technology",
    "Computer Hardware": "Technology",
    "Electronic Components": "Technology",
    "Internet Content & Information": "Communication Services",
    "Scientific & Technical Instruments": "Technology",
    "Electronics & Computer Distribution": "Technology",
    "Specialty Industrial Machinery": "Industrials",
}


def _normalize_label(label: str) -> str:
    """Normalize scope labels so YAML variants can still match.

    Handles em/en dash vs hyphen and inconsistent spacing/casing.
    """
    raw = (label or "").strip().lower()
    raw = raw.replace("—", "-").replace("–", "-")
    raw = raw.replace("_", " ")
    raw = re.sub(r"\s*-\s*", " - ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw


def _canonical_scope(industry: str) -> str:
    mapping = {
        "software—infrastructure": "Software—Infrastructure",
        "software - infrastructure": "Software—Infrastructure",
        "software—application": "Software—Application",
        "software - application": "Software—Application",
        "specialty industrial": "Specialty Industrial Machinery",
        "machinery": "Specialty Industrial Machinery",
    }
    norm = _normalize_label(industry)
    return mapping.get(norm, industry.replace("—", "-").replace("–", "-").strip())


def _is_downstream_scope(scope_label: str, downstream_labels: set[str]) -> bool:
    scope_norm = _normalize_label(scope_label)
    for label_norm in downstream_labels:
        if label_norm in scope_norm or scope_norm in label_norm:
            return True
    return False


def _fetch_business_summary(symbol: str) -> str:
    try:
        info = yf.Ticker(symbol).info or {}
        return str(info.get("longBusinessSummary") or "").lower()
    except Exception:
        return ""


def _apply_ai_relevance_tags(rows: list[dict], cfg: dict) -> None:
    """Tag rows by AI high-relevance, without removing any in-scope company.

    Rule:
      - upstream/midstream scopes: include directly, mark high relevance.
      - downstream scopes: run summary keyword checks for top-N only.
      - downstream beyond top-N: keep and mark not_evaluated_rate_limit.
      - private companies: keep and mark curated.
    """
    downstream_labels = {
        _normalize_label(_canonical_scope(s))
        for s in (cfg.get("downstream_industries") or [])
    }
    ai_keywords = [str(k).lower() for k in (cfg.get("ai_keywords") or [])]
    raw_top_n = cfg.get("summary_filter_top_n", 60)
    top_n = int(raw_top_n) if raw_top_n is not None else 60

    downstream_public = [
        r for r in rows
        if r.get("is_public", True)
        and _is_downstream_scope(r.get("gics_sub_industry", ""), downstream_labels)
    ]
    downstream_public.sort(
        key=lambda r: (
            -(float(r.get("market_cap")) if r.get("market_cap") else 0.0),
            int(r.get("screen_rank") or 10**9),
        )
    )
    evaluate_all_downstream = top_n <= 0
    if evaluate_all_downstream:
        evaluated_tickers = {r["ticker"] for r in downstream_public}
        log.info(
            "Downstream deep-eval running in full mode (all %d companies).",
            len(downstream_public),
        )
    else:
        evaluated_tickers = {r["ticker"] for r in downstream_public[:top_n]}
        log.info(
            "Downstream deep-eval running in capped mode (top %d of %d).",
            top_n,
            len(downstream_public),
        )

    for row in rows:
        if not row.get("is_public", True):
            row["ai_high_relevance"] = True
            row["ai_relevance_tag"] = "private_curated"
            continue

        scope_label = row.get("gics_sub_industry", "")
        if not _is_downstream_scope(scope_label, downstream_labels):
            row["ai_high_relevance"] = True
            row["ai_relevance_tag"] = "upstream_midstream_in_scope"
            continue

        if row.get("ticker") not in evaluated_tickers:
            row["ai_high_relevance"] = None
            row["ai_relevance_tag"] = "downstream_not_evaluated_rate_limit"
            continue

        summary = _fetch_business_summary(row["ticker"])
        if not summary:
            row["ai_high_relevance"] = None
            row["ai_relevance_tag"] = "downstream_summary_fetch_failed"
            continue

        has_ai_tech = any(kw in summary for kw in ai_keywords)
        row["ai_high_relevance"] = has_ai_tech
        row["ai_relevance_tag"] = (
            "downstream_keyword_match" if has_ai_tech else "downstream_keyword_no_match"
        )


def _load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _screen_industry(industry: str, region: str, min_mcap: int, max_pages: int = 4) -> list[dict]:
    """按 Yahoo industry 全市场筛选 public 公司（分页拉取）。"""
    rows: list[dict] = []

    # yfinance 1.x exposes top-level `yf.screen`; older builds used `yf.Screener().screen`
    if hasattr(yf, "screen"):
        screen_fn = yf.screen
    elif hasattr(yf, "Screener"):
        screener = yf.Screener()
        screen_fn = screener.screen
    else:
        raise RuntimeError("yfinance screener API is unavailable in current version")

    canonical_industry = _canonical_scope(industry)

    for page in range(max_pages):
        query_field = "industry"
        query_value = canonical_industry

        try:
            query = EquityQuery("and", [
                EquityQuery("eq", ["region", region]),
                EquityQuery("eq", [query_field, query_value]),
                EquityQuery("gt", ["intradaymarketcap", min_mcap]),
            ])
        except ValueError:
            fallback_sector = SCOPE_TO_SECTOR_FALLBACK.get(canonical_industry)
            if not fallback_sector:
                log.warning("Skipping unsupported scope filter: %s", canonical_industry)
                break
            query_field = "sector"
            query_value = fallback_sector
            log.info("Scope '%s' not accepted as industry; fallback to sector='%s'", canonical_industry, fallback_sector)
            query = EquityQuery("and", [
                EquityQuery("eq", ["region", region]),
                EquityQuery("eq", [query_field, query_value]),
                EquityQuery("gt", ["intradaymarketcap", min_mcap]),
            ])

        try:
            resp = screen_fn(
                query,
                size=PAGE_SIZE,
                offset=page * PAGE_SIZE,
                sortField="intradaymarketcap",
                sortAsc=False,
            )
        except Exception as e:
            log.warning("Screener failed for %s page %d: %s", industry, page, e)
            break
        quotes = resp.get("quotes", [])
        if not quotes:
            break
        for idx, qt in enumerate(quotes):
            symbol = qt.get("symbol")
            if not symbol:
                continue
            name = qt.get("longName") or qt.get("shortName") or symbol
            market_cap = (
                qt.get("marketCap")
                or qt.get("intradaymarketcap")
                or qt.get("lastclosemarketcap.lasttwelvemonths")
            )
            rows.append({
                "ticker": symbol,
                "name": name,
                "aliases": list({name, symbol}),
                "gics_sub_industry": canonical_industry,  # scope label from config (may map to sector fallback)
                "is_public": True,
                "market_cap": market_cap,
                "screen_rank": page * PAGE_SIZE + idx,
            })
        if len(quotes) < PAGE_SIZE:
            break
    log.info("Industry %-40s -> %d tickers", canonical_industry, len(rows))
    return rows


def _build_rows(cfg: dict, full_refresh: bool) -> list[dict]:
    by_ticker: dict[str, dict] = {}

    if full_refresh:
        for ind in cfg.get("yahoo_industries", []):
            for r in _screen_industry(ind, cfg.get("screener_region", "us"),
                                      cfg.get("screener_min_market_cap", 0)):
                by_ticker.setdefault(r["ticker"], r)
    else:
        # 非全量刷新：以库内现有 public 行为基础
        engine = get_engine()
        with engine.connect() as conn:
            existing = conn.execute(text(
                "SELECT ticker, name, aliases, gics_sub_industry FROM watchlist "
                "WHERE is_public = TRUE AND active_flag = TRUE"
            )).mappings().all()
        for r in existing:
            by_ticker[r["ticker"]] = {**dict(r), "is_public": True}

    # manual overrides（public，修正/补充分类与 exposure）
    for ov in cfg.get("manual_overrides", []):
        r = by_ticker.setdefault(ov["ticker"], {
            "ticker": ov["ticker"], "name": ov["ticker"],
            "aliases": [ov["ticker"]], "gics_sub_industry": None, "is_public": True,
        })
        r["ai_segment"] = ov.get("ai_segment")
        r["ai_exposure_level"] = ov.get("ai_exposure_level")
        r["is_manual_override"] = True
        if ov.get("aliases"):
            r["aliases"] = list(set(r["aliases"]) | set(ov["aliases"]))

    # private companies（伪 ticker，仅新闻匹配）
    for pc in cfg.get("private_companies", []):
        pseudo = f"PRIV:{pc['name'].upper().replace(' ', '_')}"
        by_ticker[pseudo] = {
            "ticker": pseudo,
            "name": pc["name"],
            "aliases": pc.get("aliases", [pc["name"]]),
            "gics_sub_industry": None,
            "ai_segment": pc.get("ai_segment"),
            "ai_exposure_level": pc.get("ai_exposure_level"),
            "is_manual_override": True,
            "is_public": False,
        }

    rows = list(by_ticker.values())
    _apply_ai_relevance_tags(rows, cfg)

    return rows


def run() -> int:
    cfg = _load_config()
    full_refresh = os.environ.get("WATCHLIST_FULL_REFRESH", "0") == "1"
    rows = _build_rows(cfg, full_refresh)

    engine = get_engine()
    upserted = 0
    with engine.begin() as conn:
        for r in rows:
            result = conn.execute(
                text(
                    """
                    INSERT INTO watchlist (ticker, name, aliases, gics_sub_industry,
                        ai_segment, ai_exposure_level, ai_high_relevance, ai_relevance_tag,
                        is_manual_override, is_public, active_flag)
                    VALUES (:ticker, :name, :aliases, :gics_sub_industry,
                        :ai_segment, :ai_exposure_level, :ai_high_relevance, :ai_relevance_tag,
                        :is_manual_override, :is_public, TRUE)
                    ON CONFLICT (ticker) DO UPDATE SET
                        name = EXCLUDED.name,
                        aliases = EXCLUDED.aliases,
                        gics_sub_industry = EXCLUDED.gics_sub_industry,
                        ai_segment = COALESCE(EXCLUDED.ai_segment, watchlist.ai_segment),
                        ai_exposure_level = COALESCE(EXCLUDED.ai_exposure_level, watchlist.ai_exposure_level),
                        ai_high_relevance = EXCLUDED.ai_high_relevance,
                        ai_relevance_tag = EXCLUDED.ai_relevance_tag,
                        is_manual_override = EXCLUDED.is_manual_override,
                        is_public = EXCLUDED.is_public,
                        active_flag = TRUE
                    """
                ),
                {
                    "ticker": r["ticker"], "name": r["name"],
                    "aliases": r.get("aliases", [r["ticker"]]),
                    "gics_sub_industry": r.get("gics_sub_industry"),
                    "ai_segment": r.get("ai_segment"),
                    "ai_exposure_level": r.get("ai_exposure_level"),
                    "ai_high_relevance": r.get("ai_high_relevance"),
                    "ai_relevance_tag": r.get("ai_relevance_tag"),
                    "is_manual_override": r.get("is_manual_override", False),
                    "is_public": r.get("is_public", True),
                },
            )
            upserted += result.rowcount

        # 全量刷新时，把本次没出现的 public ticker 标记 inactive（可审计）
        if full_refresh:
            conn.execute(
                text(
                    "UPDATE watchlist SET active_flag = FALSE "
                    "WHERE is_public = TRUE AND is_manual_override = FALSE "
                    "AND ticker <> ALL(:kept)"
                ),
                {"kept": [r["ticker"] for r in rows if r["is_public"]]},
            )

    log.info("Watchlist upserted %d rows (full_refresh=%s)", upserted, full_refresh)
    return upserted


if __name__ == "__main__":
    run()