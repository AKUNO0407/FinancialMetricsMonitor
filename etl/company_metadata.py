"""
Daily company metadata snapshot loader.

This job retrieves dynamic company-level market metadata from yfinance
and stores a daily snapshot in the company_metadata table.

Current fields:
    - market_cap

Static company classification remains in the watchlist table.
Dynamic market information belongs here so historical snapshots are preserved.
"""

from __future__ import annotations

import logging
import os
from datetime import date

import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured.")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------

CREATE_TABLE_SQL = text("""
CREATE TABLE IF NOT EXISTS company_metadata (
    ticker TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    market_cap NUMERIC,
    logo_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (ticker, snapshot_date)
)
""")


GET_WATCHLIST_SQL = text("""
SELECT
    ticker
FROM watchlist
WHERE active_flag = TRUE
  AND is_public = TRUE
ORDER BY ticker
""")


UPSERT_METADATA_SQL = text("""
INSERT INTO company_metadata (
    ticker,
    snapshot_date,
    market_cap
)
VALUES (
    :ticker,
    :snapshot_date,
    :market_cap
)
ON CONFLICT (ticker, snapshot_date)
DO UPDATE SET
    market_cap = EXCLUDED.market_cap
""")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _to_float(value) -> float | None:
    """
    Safely convert a value to float.

    Returns None when the value cannot be converted.
    """
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_market_cap(ticker: str) -> float | None:
    """
    Retrieve market capitalization from Yahoo Finance.

    Primary source:
        Ticker.fast_info["market_cap"]

    Fallback:
        Ticker.info["marketCap"]

    Returns:
        Market cap as float, or None if unavailable.
    """

    stock = yf.Ticker(ticker)

    # -------------------------------------------------------------
    # Primary: fast_info
    # -------------------------------------------------------------
    try:
        fast_info = stock.fast_info

        if fast_info is not None:
            market_cap = fast_info.get("market_cap")

            market_cap = _to_float(market_cap)

            if market_cap is not None and market_cap > 0:
                return market_cap

    except Exception as exc:
        logger.warning(
            "%s | MARKET_CAP_FAST_INFO_FAILED | %s",
            ticker,
            exc,
        )

    # -------------------------------------------------------------
    # Fallback: info
    # -------------------------------------------------------------
    try:
        info = stock.info

        if info:
            market_cap = info.get("marketCap")

            market_cap = _to_float(market_cap)

            if market_cap is not None and market_cap > 0:
                return market_cap

    except Exception as exc:
        logger.warning(
            "%s | MARKET_CAP_INFO_FAILED | %s",
            ticker,
            exc,
        )

    return None


def _get_watchlist_tickers() -> list[str]:
    """
    Return active public watchlist tickers.

    Private/company placeholder entries such as PRIV:* are excluded
    through is_public = TRUE.
    """

    with engine.begin() as conn:
        rows = conn.execute(
            GET_WATCHLIST_SQL
        ).scalars().all()

    return list(rows)


def _store_metadata(
    ticker: str,
    snapshot_date: date,
    market_cap: float | None,
) -> None:
    """
    Upsert one company metadata snapshot.
    """

    with engine.begin() as conn:
        conn.execute(
            UPSERT_METADATA_SQL,
            {
                "ticker": ticker,
                "snapshot_date": snapshot_date,
                "market_cap": market_cap,
            },
        )


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def run() -> None:
    """
    Retrieve and store daily market-cap snapshots
    for all active public watchlist companies.
    """

    snapshot_date = date.today()

    logger.info(
        "COMPANY_METADATA | START | snapshot_date=%s",
        snapshot_date,
    )

    # -------------------------------------------------------------
    # Ensure table exists
    # -------------------------------------------------------------
    with engine.begin() as conn:
        conn.execute(CREATE_TABLE_SQL)

    # -------------------------------------------------------------
    # Get watchlist
    # -------------------------------------------------------------
    tickers = _get_watchlist_tickers()

    logger.info(
        "COMPANY_METADATA | WATCHLIST_COUNT | %d",
        len(tickers),
    )

    if not tickers:
        logger.warning(
            "COMPANY_METADATA | NO_TICKERS"
        )
        return

    success_count = 0
    no_data_count = 0
    failed_count = 0

    # -------------------------------------------------------------
    # Retrieve market cap
    # -------------------------------------------------------------
    for ticker in tickers:

        try:
            market_cap = _get_market_cap(ticker)

            if market_cap is None:
                logger.warning(
                    "%s | MARKET_CAP | NO_DATA",
                    ticker,
                )

                # Store NULL snapshot so the ETL state is explicit.
                _store_metadata(
                    ticker=ticker,
                    snapshot_date=snapshot_date,
                    market_cap=None,
                )

                no_data_count += 1
                continue

            _store_metadata(
                ticker=ticker,
                snapshot_date=snapshot_date,
                market_cap=market_cap,
            )

            logger.info(
                "%s | MARKET_CAP | SUCCESS | %.2fB",
                ticker,
                market_cap / 1e9,
            )

            success_count += 1

        except Exception:
            logger.exception(
                "%s | MARKET_CAP | FAILED",
                ticker,
            )

            failed_count += 1

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------
    logger.info(
        "COMPANY_METADATA | COMPLETE | "
        "success=%d | no_data=%d | failed=%d",
        success_count,
        no_data_count,
        failed_count,
    )
 

if __name__ == "__main__":
    run()