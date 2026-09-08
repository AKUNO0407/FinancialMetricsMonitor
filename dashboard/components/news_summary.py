import streamlit as st

from dashboard.utils.db_client import read_sql

import html
import textwrap



# ============================================================
# Visual configuration
# ============================================================

SENTIMENT_CONFIG = {
    "BULLISH": {
        "icon": "🟢",
        "label": "BULLISH",
        "class_name": "sentiment-bullish",
    },
    "POSITIVE": {
        "icon": "🟢",
        "label": "POSITIVE",
        "class_name": "sentiment-bullish",
    },
    "BEARISH": {
        "icon": "🔴",
        "label": "BEARISH",
        "class_name": "sentiment-bearish",
    },
    "NEGATIVE": {
        "icon": "🔴",
        "label": "NEGATIVE",
        "class_name": "sentiment-bearish",
    },
    "MIXED": {
        "icon": "🟡",
        "label": "MIXED",
        "class_name": "sentiment-mixed",
    },
    "NEUTRAL": {
        "icon": "⚪",
        "label": "NEUTRAL",
        "class_name": "sentiment-neutral",
    },
}


def _get_sentiment_config(sentiment) -> dict:
    """
    Return visual configuration for a sentiment value.
    """

    if sentiment is None:
        sentiment = "NEUTRAL"

    sentiment = str(sentiment).upper()

    return SENTIMENT_CONFIG.get(
        sentiment,
        SENTIMENT_CONFIG["NEUTRAL"],
    )


def _format_count(value) -> int:
    """
    Safely convert a count to int.
    """

    if value is None:
        return 0

    return int(value)


def _safe_text(value) -> str:
    """
    Escape text before rendering inside HTML.
    """

    if value is None:
        return ""

    return html.escape(str(value))


def _render_styles():
    """
    Dashboard-specific CSS for the news section.
    """

    st.html(
        """
        <style>

        /* =====================================================
           News section
           ===================================================== */

        .news-card {
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 14px;
            padding: 20px 22px;
            margin-bottom: 18px;
            background: rgba(128, 128, 128, 0.035);
        }

        .news-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }

        .news-company {
            font-size: 1.3rem;
            font-weight: 700;
            line-height: 1.3;
        }

        .news-ticker {
            color: rgba(128, 128, 128, 0.95);
            font-size: 1rem;
            font-weight: 500;
        }

        .news-sentiment {
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            padding: 5px 9px;
            border-radius: 999px;
            white-space: nowrap;
        }

        .sentiment-bullish {
            background: rgba(34, 197, 94, 0.12);
        }

        .sentiment-bearish {
            background: rgba(239, 68, 68, 0.12);
        }

        .sentiment-mixed {
            background: rgba(234, 179, 8, 0.14);
        }

        .sentiment-neutral {
            background: rgba(128, 128, 128, 0.12);
        }

        .news-summary {
            font-size: 1.1rem;
            line-height: 1.65;
            margin: 8px 0 14px 0;
        }

        .news-stats {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin: 8px 0 16px 0;
            font-size: 0.84rem;
        }

        .news-stat-positive {
            color: #16a34a;
            font-weight: 600;
        }

        .news-stat-negative {
            color: #dc2626;
            font-weight: 600;
        }

        .news-stat-neutral {
            color: #737373;
            font-weight: 600;
        }

        .news-stat-mixed {
            color: #ca8a04;
            font-weight: 600;
        }

        .news-section-title {
            font-size: 0.9rem;
            font-weight: 700;
            letter-spacing: 0.09em;
            margin-top: 12px;
            margin-bottom: 8px;
            color: rgba(128, 128, 128, 0.95);
        }

        .news-key-point {
            font-size: 1.15rem;
            line-height: 1.5;
            margin: 5px 0;
        }

        .news-article {
            padding: 11px 0;
            border-top: 1px solid rgba(128, 128, 128, 0.16);
        }

        .news-article-title {
            font-size: 1rem;
            font-weight: 600;
            line-height: 1.45;
        }

        .news-article-meta {
            color: rgba(128, 128, 128, 0.95);
            font-size: 0.9rem;
            margin-top: 3px;
        }

        .news-article-summary {
            font-size: 1rem;
            line-height: 1.5;
            margin-top: 5px;
        }

        .news-period {
            color: rgba(128, 128, 128, 0.9);
            font-size: 0.82rem;
            margin-top: -8px;
            margin-bottom: 14px;
        }

        </style>
        """,
    )


def _get_article_data(ticker: str, summary_date):
    """
    Retrieve article-level news for one company.

    The company-level summary remains the primary source.
    Articles are only loaded when the user expands the company.
    """

    return read_sql(
        """
        SELECT
            na.ticker_or_entity as ticker,
            na.sentiment as overall_sentiment,
            na.summary,
            nr.headline as title,
            nr.source_code as source_name,
            nr.article_url,
            nr.published_date
        FROM news_analysis na
        JOIN news_raw nr
            ON na.article_id = nr.article_id
        WHERE na.ticker_or_entity = :ticker
          AND na.news_date <= :summary_date
          AND na.news_date >= (
              :summary_date - INTERVAL '3 days'
          )
        ORDER BY
            nr.published_date DESC NULLS LAST
        """,
        {
            "ticker": ticker,
            "summary_date": summary_date,
        },
    )


def _render_articles(
    ticker: str,
    summary_date,
):
    """
    Render article-level breakdown for one company.
    """

    articles = _get_article_data(
        ticker,
        summary_date,
    )

    if articles.empty:
        st.info(
            "No article-level details available."
        )
        return

    for _, article in articles.iterrows():

        sentiment = _get_sentiment_config(
            article["overall_sentiment"]
        )

        icon = sentiment["icon"]

        title = _safe_text(
            article["title"]
        )

        source = _safe_text(
            article["source_name"]
            or "Unknown source"
        )

        article_summary = _safe_text(
            article["summary"]
        )

        published_date = article[
            "published_date"
        ]

        if published_date is not None:
            try:
                published_text = published_date.strftime(
                    "%b %d"
                )
            except AttributeError:
                published_text = str(
                    published_date
                )
        else:
            published_text = ""

        st.html(
            f"""
            <div class="news-article">

                <div class="news-article-title">
                    {icon} {title}
                </div>

                <div class="news-article-meta">
                    {source}
                    {" · " if published_text else ""}
                    {published_text}
                </div>

                <div class="news-article-summary">
                    {article_summary}
                </div>

            </div>
            """,
        )

        article_url = article[
            "article_url"
        ]

        if article_url:
            st.link_button(
                "Read Article ↗",
                article_url,
                key=(
                    f"news-{ticker}-"
                    f"{article['article_url']}"
                ),
            )


def render_news_summary():
    """
    Render company-level daily news intelligence.

    Primary source:
        news_daily_summary

    Drill-down source:
        news_analysis + news_raw
    """

    _render_styles()

    # ============================================================
    # Load latest company-level summaries
    # ============================================================

    df = read_sql(
        """
        SELECT
            nds.ticker_or_entity as ticker,
            w.name AS company_name,

            nds.summary_date,
            nds.period_start_date,
            nds.period_end_date,

            nds.article_count,
            nds.bullish_count,
            nds.bearish_count,
            nds.neutral_count,
            nds.mixed_count,

            nds.overall_sentiment,
            nds.summary,
            nds.key_points,
            nds.source_urls

        FROM news_daily_summary nds

        LEFT JOIN watchlist w
            ON nds.ticker_or_entity = w.ticker

        WHERE nds.summary_date = (
            SELECT MAX(summary_date)
            FROM news_daily_summary
        )

        ORDER BY
            CASE nds.overall_sentiment
                WHEN 'BULLISH' THEN 1
                WHEN 'POSITIVE' THEN 2
                WHEN 'MIXED' THEN 3
                WHEN 'NEUTRAL' THEN 4
                WHEN 'BEARISH' THEN 5
                WHEN 'NEGATIVE' THEN 6
                ELSE 7
            END,
            nds.article_count DESC,
            nds.ticker_or_entity
        """
    )

    st.subheader("Key News")

    if df.empty:
        st.info(
            "No company-level news summary available."
        )
        return

    # ============================================================
    # Header
    # ============================================================

    latest_date = df[
        "summary_date"
    ].iloc[0]

    period_start = df[
        "period_start_date"
    ].iloc[0]

    period_end = df[
        "period_end_date"
    ].iloc[0]

    try:
        period_text = (
            f"{period_start.strftime('%b %d')}"
            f" – "
            f"{period_end.strftime('%b %d, %Y')}"
        )
    except AttributeError:
        period_text = (
            f"{period_start} – {period_end}"
        )

    st.html(
        f"""
        <div class="news-period">
            Company-level news intelligence · {period_text}
        </div>
        """,
    )

    # ============================================================
    # Sentiment filter
    # ============================================================

    filter_option = st.radio(
        "News Filter",
        [
            "All",
            "Bullish",
            "Bearish",
            "Mixed",
            "Neutral",
        ],
        horizontal=True,
        label_visibility="collapsed",
    )

    if filter_option != "All":
        target = filter_option.upper()

        if target == "BULLISH":
            target_values = [
                "BULLISH",
                "POSITIVE",
            ]
        elif target == "BEARISH":
            target_values = [
                "BEARISH",
                "NEGATIVE",
            ]
        else:
            target_values = [target]

        df = df[
            df["overall_sentiment"]
            .str.upper()
            .isin(target_values)
        ]

    if df.empty:
        st.info(
            f"No {filter_option.lower()} company news."
        )
        return

    # ============================================================
    # Company cards
    # ============================================================

    for _, row in df.iterrows():

        ticker = str(
            row["ticker"]
        )

        sentiment = _get_sentiment_config(
            row["overall_sentiment"]
        )

        icon = sentiment["icon"]
        sentiment_label = sentiment["label"]
        sentiment_class = sentiment[
            "class_name"
        ]

        # --------------------------------------------------------
        # Company
        # --------------------------------------------------------

        company = ticker

        # We can derive company name from watchlist.
        company = (
            row["company_name"]
            or ticker
        )

        company = _safe_text(company)

        # --------------------------------------------------------
        # Counts
        # --------------------------------------------------------

        article_count = _format_count(
            row["article_count"]
        )

        bullish_count = _format_count(
            row["bullish_count"]
        )

        bearish_count = _format_count(
            row["bearish_count"]
        )

        neutral_count = _format_count(
            row["neutral_count"]
        )

        mixed_count = _format_count(
            row["mixed_count"]
        )

        # --------------------------------------------------------
        # Summary
        # --------------------------------------------------------

        summary = _safe_text(
            row["summary"]
        )

        # --------------------------------------------------------
        # Card header
        # --------------------------------------------------------

        st.html(
            f"""
            <div class="news-card">

                <div class="news-card-header">

                    <div class="news-company">
                        {icon}
                        {company}
                        <span class="news-ticker">
                            ({ticker})
                        </span>
                    </div>

                    <div class="
                        news-sentiment
                        {sentiment_class}
                    ">
                        {sentiment_label}
                    </div>

                </div>

                <div class="news-summary">
                    {summary}
                </div>

                <div class="news-stats">

                    <span>
                        📰 {article_count} articles
                    </span>

                    <span class="
                        news-stat-positive
                    ">
                        ↑ {bullish_count} Bullish
                    </span>

                    <span class="
                        news-stat-negative
                    ">
                        ↓ {bearish_count} Bearish
                    </span>

                    <span class="
                        news-stat-neutral
                    ">
                        → {neutral_count} Neutral
                    </span>

                    <span class="
                        news-stat-mixed
                    ">
                        ◆ {mixed_count} Mixed
                    </span>

                </div>

            """,
        )

        # --------------------------------------------------------
        # Key points
        # --------------------------------------------------------

        key_points = row[
            "key_points"
        ]

        if key_points:

            st.html(
                """
                <div class="news-section-title">
                    KEY DEVELOPMENTS
                </div>
                """,
            )

            # PostgreSQL JSONB may already arrive as a Python list.
            if isinstance(
                key_points,
                str,
            ):
                try:
                    import json

                    key_points = json.loads(
                        key_points
                    )
                except Exception:
                    key_points = [
                        key_points
                    ]

            if isinstance(
                key_points,
                list,
            ):

                for point in key_points:

                    point = _safe_text(
                        point
                    )

                    st.html(
                        f"""
                        <div class="news-key-point">
                            • {point}
                        </div>
                        """,
                    )

        st.html(
            "</div>",
        )

        # --------------------------------------------------------
        # Article drill-down
        # --------------------------------------------------------

        with st.expander(
            f"View {article_count} articles"
        ):
            _render_articles(
                ticker=ticker,
                summary_date=latest_date,
            )

        st.divider()