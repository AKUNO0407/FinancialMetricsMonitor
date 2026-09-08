"""
News scraping job — ported from the reference implementation in news_monitor.py
(originally at C:\\Users\\desmo\\Downloads\\news_monitor\\news_monitor\\news_monitor.py).

Iterates feeds defined in config/news_feed.json, per-source config
(url, use_headers, nested, xml_prefix):
    - nested sources (sitemap-index, e.g. Reuters/BBC/American Banker):
      fetch the index first, extract child sitemap URLs (cap ~10), parse each
    - parse via BeautifulSoup Google News sitemap schema
      (<news:title>, <news:publication_date>, <loc>) first
    - fall back to feedparser for plain RSS/Atom if sitemap parsing yields nothing
    - gzip auto-decompression for .gz sitemap URLs (e.g. NYT)
    - apply a lookback-day cutoff (ETL_LOOKBACK_DAYS env var) to drop stale entries
    - match headlines against watchlist `aliases` (case-insensitive substring match)
    - wrap each source fetch in try/except - log and continue, never crash the whole job
    - store matches into `news_raw`
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import urllib.request
from pathlib import Path
from typing import Optional

import feedparser
from bs4 import BeautifulSoup
from psycopg import logger
from sqlalchemy import text

from etl.db import get_engine

from langdetect import detect, LangDetectException

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FEEDS_PATH = Path(__file__).resolve().parent.parent / "config" / "news_feed.json"


HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

TRACKING_QUERY_PARAMS = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}


def _load_feeds() -> dict:
    return json.loads(FEEDS_PATH.read_text(encoding="utf-8"))


def _fetch_raw(url: str, use_headers: bool = False) -> bytes:
    headers = HTTP_HEADERS if use_headers else {"User-Agent": "python-feedparser/6.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    if url.endswith(".gz"):
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    return raw


def _parse_news_sitemap(raw: bytes, source: str, cutoff: dt.datetime, xml_prefix: str = "news") -> list[dict]:
    """Parse a Google News sitemap XML and return headline dicts."""
    soup = BeautifulSoup(raw, features="xml")
    results = []
    for url_tag in soup.find_all("url"):
        news_tag = url_tag.find(f"{xml_prefix}:news") or url_tag.find("news")
        if not news_tag:
            continue
        title_tag = news_tag.find(f"{xml_prefix}:title") or news_tag.find("title")
        date_tag = news_tag.find(f"{xml_prefix}:publication_date") or news_tag.find("publication_date")
        loc_tag = url_tag.find("loc")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            continue
        pub_date = None
        if date_tag and date_tag.text:
            try:
                pub_date = dt.datetime.fromisoformat(date_tag.text.strip().replace("Z", "+00:00"))
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=dt.timezone.utc)
            except Exception:
                pass
        if pub_date and pub_date < cutoff:
            continue
        results.append({
            "headline": title,
            "url": loc_tag.get_text(strip=True) if loc_tag else "",
            "source": source,
            "date": pub_date,
        })
    return results


def _get_nested_urls(raw: bytes) -> list[str]:
    """Extract sub-sitemap URLs from a sitemap index."""
    soup = BeautifulSoup(raw, features="xml")
    return [loc.get_text(strip=True) for loc in soup.find_all("loc")]


def _parse_date(entry) -> Optional[dt.datetime]:
    """Try to extract a timezone-aware datetime from a feed entry."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return dt.datetime(*parsed[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
    return None


def _normalize_article_url(url: str) -> str:
    """Normalize article URL to improve dedupe hit-rate.

    Keeps path and non-tracking query params, strips fragments and common tracking keys.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if not parts.scheme or not parts.netloc:
            return raw

        query_items = []
        for key, value in parse_qsl(parts.query, keep_blank_values=False):
            lower_key = key.lower()
            if lower_key.startswith("utm_") or lower_key in TRACKING_QUERY_PARAMS:
                continue
            query_items.append((key, value))

        normalized_query = urlencode(query_items, doseq=True)
        normalized_path = parts.path or "/"
        if normalized_path != "/" and normalized_path.endswith("/"):
            normalized_path = normalized_path[:-1]

        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                normalized_path,
                normalized_query,
                "",  # strip fragment
            )
        )
    except Exception:
        return raw
    
REUTERS_NON_EN_PREFIXES = (
    "/pt/",
    "/es/",
    "/fr/",
    "/de/",
    "/it/",
    "/jp/",
    "/cn/",
)

def _is_reuters_english_url(url: str) -> bool:
    if not url:
        return False

    path = urlsplit(url).path.lower()

    return not path.startswith(REUTERS_NON_EN_PREFIXES)


def _is_english_or_chinese(text: str) -> bool:
    if not text:
        return False

    # Strong Chinese signal
    chinese_chars = sum(
        "\u4e00" <= c <= "\u9fff"
        for c in text
    )

    if chinese_chars >= 2:
        return True

    # Language detection
    try:
        lang = detect(text)
        return lang in {"en", "zh-cn", "zh-tw"}
    except LangDetectException:
        return False
    

def scrape_all_headlines(lookback_days: int = 3) -> list[dict]:
    """Fetch recent headlines from all RSS/sitemap feeds in config/news_feed.json."""
    feeds = _load_feeds()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)
    all_headlines: list[dict] = []

    for source, cfg in feeds.items():
        url = cfg["url"]
        use_headers = cfg.get("use_headers", False)
        nested = cfg.get("nested", False)
        xml_prefix = cfg.get("xml_prefix", "news")

        try:
            raw = _fetch_raw(url, use_headers=use_headers)

            if nested:
                child_urls = _get_nested_urls(raw)
                for child_url in child_urls[:10]:  # cap at 10 sub-sitemaps
                    try:
                        child_raw = _fetch_raw(child_url, use_headers=use_headers)
                        parsed = _parse_news_sitemap(child_raw, source, cutoff, xml_prefix)
                        if parsed:
                            all_headlines.extend(parsed)
                            continue
                        feed = feedparser.parse(child_raw)
                        for entry in feed.entries:
                            title = entry.get("title", "").strip()
                            if not title:
                                continue
                            pub_date = _parse_date(entry)
                            if pub_date and pub_date < cutoff:
                                continue
                            all_headlines.append({
                                "headline": title, "url": entry.get("link", ""),
                                "source": source, "date": pub_date,
                            })
                    except Exception as e:
                        log.debug("Failed sub-sitemap %s: %s", child_url, e)
                continue

            parsed = _parse_news_sitemap(raw, source, cutoff, xml_prefix)
            if parsed:
                all_headlines.extend(parsed)
                continue

            feed = feedparser.parse(raw)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                pub_date = _parse_date(entry)
                if pub_date and pub_date < cutoff:
                    continue
                all_headlines.append({
                    "headline": title, "url": entry.get("link", ""),
                    "source": source, "date": pub_date,
                })

        except Exception as e:
            log.warning("Failed to fetch %s (%s): %s", source, url, e)

    log.info("Scraped %d headlines from %d sources", len(all_headlines), len(feeds))
    filtered_headlines = [
        hl for hl in all_headlines
        if _is_english_or_chinese(hl.get("headline", ""))
        and (
            hl.get("source") != "REUT"
            or _is_reuters_english_url(hl.get("url", ""))
        )
    ]
    log.info("Scraped %d English or Chinese headlines from %d sources", len(filtered_headlines), len(feeds))
    return filtered_headlines



AMBIGUOUS_TICKERS = {
    "TT",
    "MU",
    "NOW",
    "ARM",
    "TER",
    "FORM",
    "ASX",
}


def _contains_term(text: str, term: str) -> bool:
    """Match a whole word / phrase instead of raw substring."""
    term = (term or "").strip()

    if not term:
        return False

    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"

    return re.search(
        pattern,
        text,
        flags=re.IGNORECASE,
    ) is not None


def match_headlines(headlines: list[dict], watchlist: list[dict]) -> dict[str, list[dict]]:
    """Case-insensitive alias matching of headlines to watchlist tickers.

    `watchlist` rows must have keys: ticker, aliases (list[str]).
    """
    matched = {w["ticker"]: [] for w in watchlist}

    for hl in headlines:
        headline = hl["headline"]

        for company in watchlist:
            ticker = company["ticker"].upper()
            name = company.get("name") or ""
            aliases = company.get("aliases") or []

            # --------------------------------------------------
            # 1. Strong match: company name
            # --------------------------------------------------
            if _contains_term(headline, name):
                matched[ticker].append(hl)
                continue

            # --------------------------------------------------
            # 2. Strong match: aliases
            # --------------------------------------------------
            alias_match = False

            for alias in aliases:
                if _contains_term(headline, alias):
                    matched[ticker].append(hl)
                    alias_match = True
                    break

            if alias_match:
                continue

            # --------------------------------------------------
            # 3. Ticker match
            # --------------------------------------------------
            # Do NOT rely on ambiguous short/common tickers.
            if ticker in AMBIGUOUS_TICKERS:
                continue

            if _contains_term(headline, ticker):
                matched[ticker].append(hl)

    for ticker, hls in matched.items():
        if hls:
            log.info("  %s: %d headlines matched", ticker, len(hls))
    log.info("Total headlines matched: %d", sum(len(hls) for hls in matched.values()))
    return matched




def _load_active_watchlist(engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT ticker, name, aliases FROM watchlist WHERE active_flag = TRUE")
        ).mappings().all()
    return [dict(r) for r in rows]


def _store_news_raw(engine, matched: dict[str, list[dict]]) -> int:
    inserted = 0
    with engine.begin() as conn:
        for ticker, headlines in matched.items():
            for hl in headlines:
                normalized_url = _normalize_article_url(hl.get("url", ""))
                if not normalized_url:
                    continue
                result = conn.execute(
                    text(
                        """
                        INSERT INTO news_raw (source_code, headline, article_url, published_date, matched_tickers, ai_relevance_flag)
                        VALUES (:source, :headline, :url, :published_date, ARRAY[:ticker], NULL)
                        ON CONFLICT (article_url) DO UPDATE
                            SET matched_tickers = array_append(
                                array_remove(news_raw.matched_tickers, :ticker), :ticker
                            )
                        """
                    ),
                    {
                        "source": hl["source"],
                        "headline": hl["headline"],
                        "url": normalized_url,
                        "published_date": hl.get("date"),
                        "ticker": ticker,
                    },
                )
                inserted += result.rowcount
    return inserted


def scrape_headlines(lookback_days: Optional[int] = None) -> int:
    """Entry point used by etl/run_all.py. Returns rows_affected."""
    lookback_days = lookback_days or int(os.environ.get("ETL_LOOKBACK_DAYS", "3"))
    engine = get_engine()
    watchlist = _load_active_watchlist(engine)
    if not watchlist:
        log.warning("Watchlist is empty - run etl.watchlist first. Skipping news scrape.")
        return 0

    headlines = scrape_all_headlines(lookback_days=lookback_days)
    matched = match_headlines(headlines, watchlist)
    for ticker, items in matched.items():
        logger.info("Matched %s: %d", ticker, len(items))
    return _store_news_raw(engine, matched)


if __name__ == "__main__":
    scrape_headlines()
