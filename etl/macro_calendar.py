from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from etl.db import get_engine



logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

LOOKAHEAD_DAYS = int(
    os.getenv("MACRO_LOOKAHEAD_DAYS", "120")
)

engine = get_engine()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140 Safari/537.36"
    )
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]

BLS_CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "macro_calendar.yaml"
)

BEA_RELEASE_DATES_URL = (
    "https://apps.bea.gov/API/signup/release_dates.json"
)

FOMC_URL = (
    "https://www.federalreserve.gov/"
    "monetarypolicy/fomccalendars.htm"
)


# ============================================================
# Common helpers
# ============================================================

def _get(
    url: str,
) -> requests.Response:

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response


def _is_within_lookahead(
    event_date: date,
) -> bool:

    today = datetime.now(ET).date()

    end_date = (
        today
        + timedelta(days=LOOKAHEAD_DAYS)
    )

    return today <= event_date <= end_date


# ============================================================
# FOMC
# ============================================================

def _get_fomc_events() -> list[dict]:

    response = _get(FOMC_URL)

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    current_year = datetime.now(ET).year

    year_heading = soup.find(
        "div",
        class_="panel-heading",
        string=lambda s: (
            s
            and f"{current_year} FOMC Meetings" in s
        ),
    )

    if year_heading is None:
        logger.warning(
            "FOMC | YEAR_HEADING_NOT_FOUND | %s",
            current_year,
        )
        return []

    panel = year_heading.find_parent(
        "div",
        class_="panel",
    )

    if panel is None:
        logger.warning(
            "FOMC | PANEL_NOT_FOUND | %s",
            current_year,
        )
        return []

    meetings = panel.find_all(
        "div",
        class_=lambda classes: (
            classes
            and "fomc-meeting" in classes
        ),
    )

    events = []

    current_month = None

    for meeting in meetings:
        text_value = " ".join(
            meeting.get_text(
                " ",
                strip=True,
            ).split()
        )

        if not text_value:
            continue

        # Case 1:
        # "September"
        month_match = re.fullmatch(
            r"(January|February|March|April|May|June|"
            r"July|August|September|October|November|December)",
            text_value,
            flags=re.IGNORECASE,
        )

        if month_match:
            current_month = month_match.group(1)
            continue

        # Case 2:
        # "15-16*" / "27-28"
        date_match = re.fullmatch(
            r"(\d{1,2})(?:-(\d{1,2}))?(\*)?",
            text_value,
        )

        if date_match and current_month:
            start_day = int(date_match.group(1))

            end_day = (
                int(date_match.group(2))
                if date_match.group(2)
                else start_day
            )

            is_sep = bool(date_match.group(3))

            try:
                month_number = datetime.strptime(
                    current_month,
                    "%B",
                ).month

                start_date = date(
                    current_year,
                    month_number,
                    start_day,
                )

            except ValueError:
                logger.warning(
                    "FOMC | INVALID_DATE | %s %s",
                    current_month,
                    text_value,
                )
                continue

            if not _is_within_lookahead(start_date):
                continue

            event_name = (
                "FOMC Meeting (SEP)"
                if is_sep
                else "FOMC Meeting"
            )

            events.append(
                {
                    "ticker": "MACRO_EVENT",
                    "company_name": "Federal Reserve",
                    "event_type": "FOMC",
                    "event_name": event_name,
                    "event_date": start_date,
                    "event_datetime": None,
                    "timing": (
                        f"Meeting: "
                        f"{current_month} "
                        f"{start_day}-{end_day}"
                    ),
                    "fiscal_period_end_date": None,
                    "eps_estimate": None,
                    "revenue_estimate": None,
                    "is_watchlist": False,
                    "source": "Federal Reserve",
                    "source_url": FOMC_URL,
                }
            )

            continue

    events.sort(
        key=lambda x: x["event_date"]
    )

    logger.info(
        "FOMC | PARSED | %d future meetings",
        len(events),
    )

    return events


# ============================================================
# BEA
# ============================================================

def _get_bea_events() -> list[dict]:

    response = _get(
        BEA_RELEASE_DATES_URL
    )

    data = response.json()

    event_map = {
        "Gross Domestic Product": {
            "event_type": "GDP",
            "event_name": "Gross Domestic Product",
        },
        "Personal Income and Outlays": {
            "event_type": "PCE",
            "event_name": "Personal Income and Outlays",
        },
    }

    events = []

    for release_name, metadata in event_map.items():

        release_info = data.get(
            release_name
        )

        if not release_info:
            logger.warning(
                "BEA | RELEASE_NOT_FOUND | %s",
                release_name,
            )
            continue

        release_dates = (
            release_info.get(
                "release_dates",
                [],
            )
        )

        for release_date_string in release_dates:

            parsed = pd.to_datetime(
                release_date_string,
                errors="coerce",
                utc=True,
            )

            if pd.isna(parsed):
                continue

            event_datetime = (
                parsed
                .to_pydatetime()
                .astimezone(ET)
            )

            event_date = (
                event_datetime.date()
            )

            if not _is_within_lookahead(
                event_date
            ):
                continue

            events.append(
                {
                    "ticker": "MACRO_EVENT",
                    "company_name": "U.S. Bureau of Economic Analysis",
                    "event_type": metadata["event_type"],
                    "event_name": metadata["event_name"],
                    "event_date": event_date,
                    "event_datetime": event_datetime,
                    "timing": event_datetime.strftime(
                        "%I:%M %p ET"
                    ),
                    "fiscal_period_end_date": None,
                    "eps_estimate": None,
                    "revenue_estimate": None,
                    "is_watchlist": False,
                    "source": "BEA",
                    "source_url": BEA_RELEASE_DATES_URL,
                }
            )

    unique = {}

    for event in events:

        key = (
            event["event_type"],
            event["event_date"],
            event["event_datetime"],
        )

        unique[key] = event

    events = list(
        unique.values()
    )

    events.sort(
        key=lambda x: (
            x["event_date"],
            x["event_datetime"],
            x["event_type"],
        )
    )

    logger.info(
        "BEA | PARSED | %d events",
        len(events),
    )

    return events


# ============================================================
# BLS YAML
# ============================================================

def _get_bls_events() -> list[dict]:

    if not BLS_CONFIG_PATH.exists():

        logger.warning(
            "BLS | CONFIG_NOT_FOUND | %s",
            BLS_CONFIG_PATH,
        )

        return []

    with BLS_CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        config = yaml.safe_load(file) or {}

    events = []

    for item in config.get(
        "events",
        [],
    ):

        event_date = pd.to_datetime(
            item["event_date"],
            errors="coerce",
        )

        if pd.isna(event_date):
            logger.warning(
                "BLS | INVALID_DATE | %s",
                item,
            )
            continue

        event_date = event_date.date()

        if not _is_within_lookahead(
            event_date
        ):
            continue

        event_time = item.get(
            "event_time"
        )

        event_datetime = None

        if event_time:
            hour, minute = map(
                int,
                event_time.split(":"),
            )

            event_datetime = datetime(
                event_date.year,
                event_date.month,
                event_date.day,
                hour,
                minute,
                tzinfo=ET,
            )

        events.append(
            {
                "ticker": "MACRO_EVENT",
                "company_name": (
                    "U.S. Bureau of Labor Statistics"
                ),
                "event_type": item["event_type"],
                "event_name": item["event_name"],
                "event_date": event_date,
                "event_datetime": event_datetime,
                "timing": (
                    event_datetime.strftime(
                        "%I:%M %p ET"
                    )
                    if event_datetime
                    else None
                ),
                "fiscal_period_end_date": None,
                "eps_estimate": None,
                "revenue_estimate": None,
                "is_watchlist": False,
                "source": item.get(
                    "source",
                    "BLS",
                ),
                "source_url": item.get(
                    "source_url"
                ),
            }
        )

    events.sort(
        key=lambda x: (
            x["event_date"],
            x["event_datetime"]
            or datetime.min.replace(
                tzinfo=ET
            ),
            x["event_type"],
        )
    )

    logger.info(
        "BLS | PARSED | %d events",
        len(events),
    )

    return events


# ============================================================
# Combine
# ============================================================

def _get_macro_events() -> list[dict]:

    events = []

    events.extend(
        _get_fomc_events()
    )

    events.extend(
        _get_bea_events()
    )

    events.extend(
        _get_bls_events()
    )

    unique = {}

    for event in events:

        key = (
            event["ticker"],
            event["event_type"],
            event["event_date"],
        )

        unique[key] = event

    events = list(
        unique.values()
    )

    events.sort(
        key=lambda x: (
            x["event_date"],
            x["event_datetime"]
            or datetime.min.replace(
                tzinfo=ET
            ),
            x["event_type"],
        )
    )

    logger.info(
        "MACRO | TOTAL | %d events",
        len(events),
    )

    return events


def _store_macro_events(
    events: list[dict],
) -> int:

    if not events:
        logger.info(
            "MACRO | NO_EVENTS_TO_STORE"
        )
        return 0

    upsert_sql = text("""
        INSERT INTO prospective_events (
            ticker,
            company_name,
            event_type,
            event_name,
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
            :event_type,
            :event_name,
            :event_date,
            :event_datetime,
            :timing,
            :fiscal_period_end_date,
            :eps_estimate,
            :revenue_estimate,
            :is_watchlist,
            :source,
            :source_url,
            now()
        )
        ON CONFLICT (
            ticker,
            event_type,
            event_date
        )
        DO UPDATE SET
            company_name = EXCLUDED.company_name,
            event_name = EXCLUDED.event_name,
            event_datetime = EXCLUDED.event_datetime,
            timing = EXCLUDED.timing,
            fiscal_period_end_date =
                EXCLUDED.fiscal_period_end_date,
            eps_estimate = EXCLUDED.eps_estimate,
            revenue_estimate = EXCLUDED.revenue_estimate,
            is_watchlist = EXCLUDED.is_watchlist,
            source = EXCLUDED.source,
            source_url = EXCLUDED.source_url,
            updated_at = now()
    """)

    with engine.begin() as conn:

        for event in events:

            conn.execute(
                upsert_sql,
                event,
            )

    logger.info(
        "MACRO | STORED | %d events",
        len(events),
    )

    return len(events)


def _cleanup_macro_events() -> int:

    sql = text("""
        DELETE FROM prospective_events
        WHERE ticker = 'MACRO_EVENT'
          AND event_date < CURRENT_DATE
    """)

    with engine.begin() as conn:

        result = conn.execute(sql)

    logger.info(
        "MACRO | CLEANUP | %d rows",
        result.rowcount,
    )

    return result.rowcount


def main():

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    logger.info(
        "MACRO | START"
    )

    _cleanup_macro_events()

    events = _get_macro_events()

    for event in events:
        logger.info(
            "%s | %s | %s | %s | %s",
            event["event_date"],
            event["event_type"],
            event["event_name"],
            event["timing"],
            event["source"],
        )

    _store_macro_events(events)

    logger.info(
        "MACRO | COMPLETE"
    )


if __name__ == "__main__":
    main()