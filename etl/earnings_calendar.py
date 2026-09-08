"""Earnings calendar loader.

Loads upcoming earnings events for active watchlist companies
and recent historical earnings performance.

Primary data source:
    yfinance

Upcoming window:
    Today -> next 7 calendar days
"""

from __future__ import annotations

import logging
import os
from datetime import date, time, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
import numpy as np
from dotenv import load_dotenv
from sqlalchemy import text

from etl.db import get_engine

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

load_dotenv(override=True)

future_count = int(os.getenv("EARNINGS_FUTURE_COUNT", "2"))
history_limit = int(os.getenv("EARNINGS_HISTORY_LIMIT", "8"))

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _to_float(value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
    
def _classify_timing(
    earnings_datetime: pd.Timestamp | None,
) -> str | None:
    """Classify earnings timing from timestamp."""

    if earnings_datetime is None:
        return None
    
    dt = pd.Timestamp(earnings_datetime)
    if dt.tzinfo is None:
        # 如果没有 timezone，要根据实际数据源约定处理
        dt = dt.tz_localize("America/New_York")
    else:
        dt = dt.tz_convert("America/New_York")

    local_time = dt.time()

    if local_time < time(9, 30):
        timing = "BMO"
    elif local_time >= time(16, 0):
        timing = "AMC"
    else:
        timing = "DURING_MARKET"
    return timing



def _infer_next_fiscal_period_end(
    fiscal_periods: list[date],
) -> date | None:
    """
    Infer the next fiscal period end based on the company's
    historical fiscal-period cadence.
    """

    if len(fiscal_periods) < 2:
        return None

    periods = sorted(set(fiscal_periods))

    month_diffs = []

    for prev, curr in zip(periods[:-1], periods[1:]):
        diff = (
            (curr.year - prev.year) * 12
            + curr.month
            - prev.month
        )

        if 2 <= diff <= 4:
            month_diffs.append(diff)

    if not month_diffs:
        return None

    # Normally 3 months
    month_step = int(round(float(np.median(month_diffs))))

    latest = pd.Timestamp(periods[-1])

    candidate = latest + pd.DateOffset(months=month_step)

    # Preserve month-end behavior
    if all(
        d.day == pd.Timestamp(d).days_in_month
        for d in periods[-min(4, len(periods)):]
    ):
        candidate = candidate + pd.offsets.MonthEnd(0)

    return candidate.date()


def _infer_future_fiscal_periods(
    fiscal_periods: list[date],
    count: int = 2,
) -> list[date]:

    periods = sorted(set(fiscal_periods))

    if not periods:
        return []

    result = []

    working_periods = periods.copy()

    for _ in range(count):

        next_period = _infer_next_fiscal_period_end(
            working_periods
        )

        if next_period is None:
            break

        result.append(next_period)
        working_periods.append(next_period)

    return result



def _map_earnings_to_fiscal_period(
    earnings_date: date,
    fiscal_periods: list[date],
) -> date | None:
    """
    Map an earnings event to the fiscal period it reports.

    Rules:
    1. Exact fiscal-period date match wins.
    2. Otherwise choose the latest fiscal period end
       that is <= the earnings date.
    3. Never map to a future fiscal period.
    """

    if not fiscal_periods:
        return None

    periods = sorted(set(fiscal_periods))

    # ---------------------------------------------------------
    # Rule 1: exact match
    # ---------------------------------------------------------
    if earnings_date in periods:
        return earnings_date

    # ---------------------------------------------------------
    # Rule 2: latest fiscal period before earnings date
    # ---------------------------------------------------------
    eligible = [
        period
        for period in periods
        if period <= earnings_date
    ]

    if not eligible:
        return None

    return max(eligible)



def _get_revenue_history(
    ticker_obj: yf.Ticker,
) -> dict[date, float]:
    """
    Return historical quarterly revenue keyed by fiscal period end date.
    """
    income_stmt = ticker_obj.quarterly_income_stmt

    if income_stmt is None or income_stmt.empty:
        return {}
    revenue_row = None

    if "Total Revenue" in income_stmt.index:
        revenue_row = income_stmt.loc["Total Revenue"]
    elif "Operating Revenue" in income_stmt.index:
        revenue_row = income_stmt.loc["Operating Revenue"]

    if revenue_row is None:
        return {}

    result = {}

    for period_end, value in revenue_row.items():

        revenue = _to_float(value)

        if revenue is None:
            continue

        period_date = pd.Timestamp(period_end).date()
        result[period_date] = revenue

    return result



def _get_consensus_estimates(
    ticker: str,
) -> dict[str, dict[str, float]]:
    """
    Get current analyst consensus EPS and revenue estimates.

    Returns:
        {
            "0q": {
                "eps": ...,
                "revenue": ...,
            },
            "+1q": {
                "eps": ...,
                "revenue": ...,
            },
        }
    """

    stock = yf.Ticker(ticker)

    eps_df = stock.get_earnings_estimate()
    revenue_df = stock.get_revenue_estimate()

    result = {}

    for period in ("0q", "+1q"):

        eps = None
        revenue = None

        if (
            eps_df is not None
            and not eps_df.empty
            and period in eps_df.index
        ):
            eps = _to_float(
                eps_df.loc[period, "avg"]
            )

        if (
            revenue_df is not None
            and not revenue_df.empty
            and period in revenue_df.index
        ):
            revenue = _to_float(
                revenue_df.loc[period, "avg"]
            )

        result[period] = {
            "eps": eps,
            "revenue": revenue,
        }

    return result


# ---------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------

def _load_watchlist() -> list[dict]:
    """Load active public watchlist companies."""

    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    ticker, name
                FROM watchlist
                WHERE active_flag = TRUE
                  AND if_retrieve_price = TRUE
                  AND is_public = TRUE
                ORDER BY ticker
                """
            )
        ).mappings().all()

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------
# Upcoming earnings
# ---------------------------------------------------------------------

def _safe_get_earnings_dates(stock, limit):
    """
    Safely retrieve earnings dates from yfinance.

    yfinance returns "Earnings Date" as the DataFrame index,
    not as a regular column.
    """
    try:
        df = stock.get_earnings_dates(
            limit=limit
        )

    except Exception as exc:
        logger.warning(
            "%s | UPCOMING_FETCH_FAILED | "
            "yfinance get_earnings_dates failed: %s",
            stock.ticker,
            exc,
        )
        return None

    if df is None:
        logger.warning(
            "%s | UPCOMING_NO_DATA | "
            "yfinance returned None",
            stock.ticker,
        )
        return None

    if df.empty:
        logger.warning(
            "%s | UPCOMING_NO_DATA | "
            "yfinance returned empty dataframe",
            stock.ticker,
        )
        return None

    # yfinance exposes earnings dates as the DataFrame index.
    if df.index.name != "Earnings Date":
        logger.warning(
            "%s | UPCOMING_BAD_RESPONSE | "
            "unexpected index name=%s | columns=%s",
            stock.ticker,
            df.index.name,
            list(df.columns),
        )
        return None

    return df


def _get_upcoming_earnings(ticker: str, future_count: int = 2) -> list[dict] | None:
    """
    Get the next N upcoming earnings events for a ticker.

    We do not use a fixed lookahead window.
    Instead, we retrieve several earnings dates from Yahoo Finance
    and keep the next `future_count` future events.
    """
    try:
        stock = yf.Ticker(ticker)

        df = _safe_get_earnings_dates(stock, limit=max(8, future_count + 4))

        if df is None:
            logger.warning(
                "%s | UPCOMING_FETCH_UNAVAILABLE | "
                "unable to retrieve earnings dates; "
                "existing future events will be preserved",
                ticker,
            )
            return None
        # get_earnings_dates() returns a DatetimeIndex named "Earnings Date"

        today = pd.Timestamp.now(tz="America/New_York").normalize()
        upcoming = []

        for earnings_dt in df.index:
            if earnings_dt is None:
                continue

            # Normalize timezone
            ts = pd.Timestamp(earnings_dt)

            if ts.tzinfo is None:
                ts = ts.tz_localize("America/New_York")
            else:
                ts = ts.tz_convert("America/New_York")

            # Ignore events that already happened
            if ts.normalize() < today:
                continue

            upcoming.append(
                {
                    "event_date": ts.date(),
                    "event_datetime": ts.to_pydatetime(),
                    "timing": _classify_timing(ts),
                }
            )

            if len(upcoming) >= future_count:
                break

        if not upcoming: return []

        # ---------------------------------------------------------
        # Fiscal periods
        # ---------------------------------------------------------

        revenue_history = _get_revenue_history(stock)
        fiscal_periods = sorted(
            revenue_history.keys()
        )
        future_fiscal_periods = (
            _infer_future_fiscal_periods(
                fiscal_periods,
                count=len(upcoming),
            )
        )

        # ---------------------------------------------------------
        # Consensus EPS + Revenue
        # ---------------------------------------------------------

        consensus = _get_consensus_estimates(ticker)

        # ---------------------------------------------------------
        # Attach fiscal + estimates
        # ---------------------------------------------------------

        for i, event in enumerate(upcoming):

            period_key = (
                "0q"
                if i == 0
                else "+1q"
            )

            event["fiscal_period_end_date"] = (
                future_fiscal_periods[i]
                if i < len(future_fiscal_periods)
                else None
            )

            event["eps_estimate"] = (
                consensus
                .get(period_key, {})
                .get("eps")
            )

            event["revenue_estimate"] = (
                consensus
                .get(period_key, {})
                .get("revenue")
            )

        return upcoming

    except Exception:
        logger.exception(
            "%s | UPCOMING_FAILED | failed to retrieve upcoming earnings",
            ticker,
        )
        return None

# ---------------------------------------------------------------------
# Store upcoming events
# ---------------------------------------------------------------------

def _store_upcoming_events(
    ticker: str,
    company_name: str,
    events: list[dict],
) -> int:
    """
    Replace the current future earnings events for a ticker
    with the latest upcoming earnings dates.
    """
    engine = get_engine()

    delete_sql = text(
        """
        DELETE FROM prospective_events
        WHERE ticker = :ticker
          AND upper(event_type) = 'EARNINGS'
          AND event_date > CURRENT_DATE
        """
    )

    insert_sql = text(
        """
        INSERT INTO prospective_events (
            ticker,
            company_name,
            event_type,
            event_date,
            event_datetime,
            timing,
            fiscal_period_end_date,
            eps_estimate,
            revenue_estimate,
            is_watchlist,
            source,
            source_url,
            updated_at
        )
        VALUES (
            :ticker,
            :company_name,
            'EARNINGS',
            :event_date,
            :event_datetime,
            :timing,
            :fiscal_period_end_date,
            :eps_estimate,
            :revenue_estimate,
            TRUE,
            :source,
            :source_url,
            now()
        )
        ON CONFLICT (ticker, event_type, event_date)
        DO UPDATE SET
            company_name = EXCLUDED.company_name,
            event_datetime = EXCLUDED.event_datetime,
            timing = EXCLUDED.timing,
            fiscal_period_end_date = EXCLUDED.fiscal_period_end_date,
            eps_estimate = EXCLUDED.eps_estimate,
            revenue_estimate = EXCLUDED.revenue_estimate,
            is_watchlist = EXCLUDED.is_watchlist,
            source = EXCLUDED.source,
            source_url = EXCLUDED.source_url,
            updated_at = now()
        """
    )

    stored_count = 0
    with engine.begin() as conn:
        # Remove stale future earnings for this ticker.
        conn.execute(
            delete_sql,
            {"ticker": ticker},
        )
        # Insert the latest upcoming earnings.
        for event in events:
            conn.execute(
                insert_sql,
                {
                    "ticker": ticker,
                    "company_name": company_name,
                    "event_date": event["event_date"],
                    "event_datetime": event.get("event_datetime"),
                    "timing": event.get("timing"),
                    "fiscal_period_end_date": event.get("fiscal_period_end_date"),
                    "eps_estimate": event.get("eps_estimate"),
                    "revenue_estimate": event.get("revenue_estimate"),
                    "source": event.get("source", "yfinance"),
                    "source_url": event.get("source_url"),
                },
            )
            stored_count += 1

    logger.info(
        "%s | UPCOMING_STORE | stored %d events",
        ticker,
        stored_count,
    )
    return stored_count


# ---------------------------------------------------------------------
# Historical earnings
# ---------------------------------------------------------------------

def _get_earnings_history(
    ticker: str,
    limit: int = 8,
) -> list[dict]:
    """Get recent historical earnings."""

    yf_ticker = yf.Ticker(ticker)

    df = yf_ticker.get_earnings_history()

    if df is None or df.empty:
        logger.warning(
            "%s | HISTORY_NO_DATA | no earnings history returned",
            ticker,
        )
        return []

    history  = []
    revenue_history = _get_revenue_history(yf_ticker)
    fiscal_periods = sorted( revenue_history.keys())
    df = df.sort_index(ascending=False).head(limit)

    for earnings_dt, row in df.iterrows():

        if pd.isna(earnings_dt):
            continue

        timestamp = pd.Timestamp(earnings_dt)

        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("America/New_York")
        else:
            timestamp = timestamp.tz_convert("America/New_York")

        revenue_actual = None
        fiscal_period_end_date = (
            _map_earnings_to_fiscal_period(
                timestamp.date(),
                fiscal_periods,
            )
        )
        if fiscal_period_end_date is not None:
            revenue_actual = revenue_history.get(
                fiscal_period_end_date
            )

        history.append(
            {
                "earnings_datetime": timestamp.to_pydatetime(),
                "earnings_date": timestamp.date(),
                "fiscal_period_end_date": fiscal_period_end_date,
                "eps_estimate": _to_float(
                    row.get("epsEstimate")
                ),
                "eps_actual": _to_float(
                    row.get("epsActual")
                ),
                "eps_difference": _to_float(
                    row.get("epsDifference")
                ),
                "eps_surprise_pct": _to_float(
                    row.get("surprisePercent")
                ),
                "revenue_actual": revenue_actual,
            }
        )

    logger.info(
        "%s | HISTORY | found %d historical earnings events",
        ticker,
        len(history),
    )

    return history


# ---------------------------------------------------------------------
# Store historical earnings
# ---------------------------------------------------------------------

def _finalize_completed_earnings(
    ticker: str,
    history: list[dict],
) -> list[dict]:
    """
    Merge historical earnings actuals with the pre-earnings
    consensus snapshot stored in prospective_events.

    The estimate in prospective_events is treated as the
    historical consensus that was known before the earnings event.
    """

    select_sql = text("""
        SELECT
            event_date,
            fiscal_period_end_date,
            eps_estimate,
            revenue_estimate
        FROM prospective_events
        WHERE ticker = :ticker
          AND event_type = 'EARNINGS'
          AND event_date <= CURRENT_DATE
        ORDER BY event_date
    """)

    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            select_sql,
            {"ticker": ticker},
        ).mappings().all()

    snapshots = {
        row["event_date"]: row
        for row in rows
    }

    finalized = []

    for event in history:
        earnings_date = event["earnings_date"]

        snapshot = snapshots.get(earnings_date)

        if snapshot:
            # IMPORTANT:
            # Prefer the snapshot captured before earnings.
            if snapshot["eps_estimate"] is not None:
                event["eps_estimate"] = snapshot["eps_estimate"]

            if event.get("revenue_estimate") is not None:
                event["revenue_estimate"] = snapshot["revenue_estimate"]

            if snapshot["fiscal_period_end_date"] is not None:
                event["fiscal_period_end_date"] = (
                    snapshot["fiscal_period_end_date"]
                )

        # Recalculate EPS difference using the historical snapshot.
        if (
            event.get("eps_actual") is not None
            and event.get("eps_estimate") is not None
        ):
            event["eps_difference"] = (
                event.get("eps_actual")
                - event.get("eps_estimate")
            )

            if event.get("eps_estimate") != 0:
                event["eps_surprise_pct"] = (
                    event.get("eps_difference")
                    / event.get("eps_estimate")
                )

        # Revenue surprise
        if (
            event.get("eps_estimate") is not None
            and event.get("revenue_estimate") is not None
        ):
            event["revenue_difference"] = (
                event.get("revenue_actual")
                - event.get("revenue_estimate")
            )

            if event.get("revenue_estimate") != 0:
                event["revenue_surprise_pct"] = (
                    event.get("revenue_difference")
                    / event.get("revenue_estimate")
                )

        finalized.append(event)

    return finalized


def _store_earnings_history(
    ticker: str,
    company_name: str,
    history: list[dict],
) -> int:
    """
    Store historical earnings results.
    """

    engine = get_engine()

    insert_sql = text("""
        INSERT INTO earnings_history (
            ticker,
            company_name,
            earnings_datetime,
            earnings_date,
            fiscal_period_end_date,
            eps_estimate,
            eps_actual,
            eps_difference,
            eps_surprise_pct,
            revenue_actual,
            source,
            updated_at
        )
        VALUES (
            :ticker,
            :company_name,
            :earnings_datetime,
            :earnings_date,
            :fiscal_period_end_date,
            :eps_estimate,
            :eps_actual,
            :eps_difference,
            :eps_surprise_pct,
            :revenue_actual,
            'yfinance',
            now()
        )
        ON CONFLICT (ticker, earnings_datetime)
        DO UPDATE SET
            company_name = EXCLUDED.company_name,
            earnings_date = EXCLUDED.earnings_date,
            fiscal_period_end_date = EXCLUDED.fiscal_period_end_date,
            eps_estimate = EXCLUDED.eps_estimate,
            eps_actual = EXCLUDED.eps_actual,
            eps_difference = EXCLUDED.eps_difference,
            eps_surprise_pct = EXCLUDED.eps_surprise_pct,
            revenue_actual = EXCLUDED.revenue_actual,
            source = EXCLUDED.source,
            updated_at = now()
    """)
    stored_count = 0

    with engine.begin() as conn:

        for event in history:
            conn.execute(
                insert_sql,
                {
                    "ticker": ticker,
                    "company_name": company_name,
                    "earnings_datetime": event["earnings_datetime"],
                    "earnings_date": event["earnings_date"],
                    "fiscal_period_end_date": event["fiscal_period_end_date"],
                    "eps_estimate": event["eps_estimate"],
                    "eps_actual": event["eps_actual"],
                    "eps_difference": event["eps_difference"],
                    "eps_surprise_pct": event["eps_surprise_pct"],
                    "revenue_actual": event["revenue_actual"],
                },
            )

            stored_count += 1

    logger.info(
        "%s | HISTORY_STORED | %d events",
        ticker,
        stored_count,
    )

    return stored_count


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:

    watchlist = _load_watchlist()

    logger.info(
        "Loaded %d active public watchlist companies",
        len(watchlist),
    )

    upcoming_count = 0
    history_count = 0
    no_data_count = 0
    failed_count = 0

    for company in watchlist:

        ticker = company["ticker"]
        company_name = company["name"]

        try:
            upcoming = _get_upcoming_earnings(ticker, future_count)
            history = _get_earnings_history(ticker, history_limit)
            # Merge pre-earnings consensus snapshot from prospective_events
            if history:
                history = _finalize_completed_earnings(
                    ticker,
                    history,
                )
            # IMPORTANT:
            # None = provider/fetch failure.
            # Preserve existing future earnings events.
            #
            # [] = successful fetch but no future events.
            # Safe to replace/delete existing future events.
            if upcoming is None:
                logger.warning(
                    "%s | UPCOMING_PRESERVED | "
                    "unable to retrieve upcoming earnings; "
                    "existing future events preserved",
                    ticker,
                )
            else:
                upcoming_count += _store_upcoming_events(
                    ticker=ticker,
                    company_name=company_name,
                    events=upcoming,
                )

            history_count += _store_earnings_history(
                ticker=ticker,
                company_name=company_name,
                history=history,
            )

            if not upcoming and not history:
                no_data_count += 1

                logger.warning(
                    "%s | NO_DATA | no earnings data",
                    ticker,
                )
            else:
                upcoming_display_count = (
                    len(upcoming)
                    if upcoming is not None
                    else 0
                )

                history_display_count = (
                    len(history)
                    if history
                    else 0
                )

                logger.info(
                    "%s | upcoming=%d | history=%d",
                    ticker,
                    upcoming_display_count,
                    history_display_count,
                )

        except Exception:
            failed_count += 1

            logger.exception(
                "%s | FAILED | earnings processing error",
                ticker,
            )

    logger.info(
        "Earnings job completed | "
        "upcoming=%d | history=%d | "
        "no_data=%d | failed=%d",
        upcoming_count,
        history_count,
        no_data_count,
        failed_count,
    )


if __name__ == "__main__":
    main()

# if __name__ == "__main__":
#     ticker = "MSFT"

#     print("\n========== REVENUE HISTORY ==========")
#     revenue_history = _get_revenue_history(yf.Ticker(ticker))

#     for fiscal_date, revenue in revenue_history.items():
#         print(fiscal_date, revenue)

#     print("\n========== FUTURE FISCAL PERIODS ==========")
#     fiscal_periods = sorted(revenue_history.keys())

#     future_periods = _infer_future_fiscal_periods(
#         fiscal_periods,
#         count=2,
#     )

#     for period in future_periods:
#         print(period)

#     print("\n========== CONSENSUS ESTIMATES ==========")
#     consensus = _get_consensus_estimates(ticker)

#     for period, values in consensus.items():
#         print(period, values)

#     print("\n========== UPCOMING ==========")
#     upcoming = _get_upcoming_earnings(
#         ticker,
#         future_count=2,
#     )

#     for event in upcoming:
#         print(event)

#     print("\n========== HISTORY ==========")
#     history = _get_earnings_history(
#         ticker,
#         limit=8,
#     )

#     for event in history:
#         print(event)