"""Daily price loader for watchlist equities and market indices.

Behavior:
- If a ticker has no existing price history:
    -> backfill PRICE_LOOKBACK_DAYS
- If a ticker already has price history:
    -> refresh PRICE_REFRESH_DAYS
- Data is upserted into the prices table.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import text

from etl.db import get_engine


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

load_dotenv(override=True)

PRICE_LOOKBACK_DAYS = int(
    os.getenv("PRICE_LOOKBACK_DAYS", "60")
)
PRICE_REFRESH_DAYS = int(
    os.getenv("PRICE_REFRESH_DAYS", "5")
)

# ---------------------------------------------------------------------
# Market indices
# ---------------------------------------------------------------------

MARKET_INDICES = {
    "DJI": "^DJI",          # Dow Jones Industrial Average
    "SP500": "^GSPC",       # S&P 500
    "NASDAQ100": "^NDX",    # Nasdaq 100
    "SOX": "^SOX",          # Philadelphia Semiconductor Index
}

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------

def _load_watchlist_tickers() -> list[str]:
    """Load active watchlist tickers from Postgres."""

    engine = get_engine()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ticker
                FROM watchlist
                WHERE active_flag = TRUE
                ORDER BY ticker
                """
            )
        ).scalars().all()

    return [ticker.upper() for ticker in rows]


# ---------------------------------------------------------------------
# Existing price history
# ---------------------------------------------------------------------

def _has_price_history(ticker: str) -> bool:
    """Return True if the ticker already has price data."""

    engine = get_engine()

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM prices
                    WHERE ticker = :ticker
                )
                """
            ),
            {"ticker": ticker},
        ).scalar()

    return bool(result)


# ---------------------------------------------------------------------
# Date window
# ---------------------------------------------------------------------

def _get_price_window(ticker: str) -> tuple[str, str, str]:
    """Determine whether to backfill or refresh."""

    today = datetime.now(timezone.utc).date()

    if _has_price_history(ticker):
        mode = "REFRESH"
        start_date = today - timedelta(
            days=PRICE_REFRESH_DAYS
        )
    else:
        mode = "BACKFILL"
        start_date = today - timedelta(
            days=PRICE_LOOKBACK_DAYS
        )

    # yfinance's end date is exclusive.
    # Use tomorrow so today's completed session is included.
    end_date = today + timedelta(days=1)

    return (
        mode,
        start_date.isoformat(),
        end_date.isoformat(),
    )


# ---------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------

def _fetch_prices(
    ticker: str,
    start_date: str,
    end_date: str,
):
    """Download daily OHLCV data from Yahoo Finance."""

    logger.info(
        "Downloading %s | %s -> %s",
        ticker,
        start_date,
        end_date,
    )

    df = yf.download(
        ticker,
        start=start_date,
        end=end_date,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if df.empty:
        return df

    # yfinance may return MultiIndex columns even for one ticker.
    if hasattr(df.columns, "levels"):
        df.columns = [
            column[0] if isinstance(column, tuple) else column
            for column in df.columns
        ]

    df = df.reset_index()

    # Normalize column names.
    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    required_columns = [
        "Date",
        "Open",
        "High",
        "Low",
        "Close",
        "Adj Close",
        "Volume",
    ]

    missing = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"{ticker}: missing columns: {missing}"
        )

    df = df[required_columns].copy()

    df["Date"] = df["Date"].dt.date

    return df


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------

def _store_prices(
    ticker: str,
    df,
) -> int:
    """Upsert price records into Postgres."""

    if df.empty:
        return 0

    records = []

    for _, row in df.iterrows():
        records.append(
            {
                "ticker": ticker,
                "price_date": row["Date"],
                "open": (
                    float(row["Open"])
                    if row["Open"] is not None
                    else None
                ),
                "high": (
                    float(row["High"])
                    if row["High"] is not None
                    else None
                ),
                "low": (
                    float(row["Low"])
                    if row["Low"] is not None
                    else None
                ),
                "close": (
                    float(row["Close"])
                    if row["Close"] is not None
                    else None
                ),
                "adj_close": (
                    float(row["Adj Close"])
                    if row["Adj Close"] is not None
                    else None
                ),
                "volume": (
                    int(row["Volume"])
                    if row["Volume"] is not None
                    else None
                ),
            }
        )

    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO prices (
                    ticker,
                    price_date,
                    open,
                    high,
                    low,
                    close,
                    adj_close,
                    volume
                )
                VALUES (
                    :ticker,
                    :price_date,
                    :open,
                    :high,
                    :low,
                    :close,
                    :adj_close,
                    :volume
                )
                ON CONFLICT (
                    ticker,
                    price_date
                )
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    adj_close = EXCLUDED.adj_close,
                    volume = EXCLUDED.volume
                """
            ),
            records,
        )

    return len(records)


# ---------------------------------------------------------------------
# Single ticker
# ---------------------------------------------------------------------

def _process_ticker(ticker: str) -> None:
    """Process one ticker and return SUCCESS / NO_DATA."""

    mode, start_date, end_date = _get_price_window(
        ticker
    )

    logger.info(
        "%s | mode=%s | window=%s -> %s",
        ticker,
        mode,
        start_date,
        end_date,
    )

    df = _fetch_prices(
        ticker,
        start_date,
        end_date,
    )

    if df.empty:
        logger.warning(
            "%s | NO_DATA | no price data returned",
            ticker,
        )
        return "NO_DATA"

    inserted = _store_prices(
        ticker,
        df,
    )

    logger.info(
        "%s | %s | %s rows upserted",
        ticker,
        mode,
        inserted,
    )
    
    return "SUCCESS"


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:

    watchlist_tickers = (
        _load_watchlist_tickers()
    )

    # Exclude private-company placeholders.
    tickers = [
        ticker
        for ticker in watchlist_tickers
        if not ticker.startswith("PRIV:")
    ]

    # Market indices
    index_tickers = list(
        MARKET_INDICES.values()
    )

    all_tickers = (
        tickers + index_tickers
    )

    # Remove duplicates while preserving order.
    all_tickers = list(
        dict.fromkeys(all_tickers)
    )

    logger.info(
        "Watchlist equities: %d",
        len(watchlist_tickers),
    )

    logger.info(
        "Market indices: %d",
        len(index_tickers),
    )

    logger.info(
        "Total tickers to process: %d",
        len(all_tickers),
    )

    success_count = 0
    no_data_count = 0
    failure_count = 0

    for ticker in all_tickers:
        try:
            status = _process_ticker(ticker)

            if status == "SUCCESS":
                success_count += 1

            elif status == "NO_DATA":
                no_data_count += 1

        except Exception:
            failure_count += 1

            logger.exception(
                "%s | FAILED | unexpected error",
                ticker,
            )

    logger.info(
        "Price job completed | success=%d | no_data=%d | failed=%d",
        success_count,
        no_data_count,
        failure_count,
    )


if __name__ == "__main__":
    main()