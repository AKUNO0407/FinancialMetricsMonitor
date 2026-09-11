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

    /* 🎯 锁定 Streamlit 的大卡片框线容器 */
    div[data-testid="stVerticalBlockBorderContainer"] {
        /* 1. 边框颜色与粗细 (Border Color & Width) */
        border: 1px solid #D9D9D9 !important; 
        
        /* 2. 圆角大小 (Border Radius) */
        border-radius: 12px !important; 
        
        /* 3. 卡片内部的留白大小/内边距 (Padding) */
        padding: 20px 24px !important; 
        
        /* 4. 卡片背景颜色 (Background Color) - 可以改成淡灰色 #F8F9FA 等 */
        background-color: #FFFFFF !important; 
        
        /* 5. 附加高级质感：卡片微阴影 (Box Shadow) */
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04) !important;
        
        /* 6. 卡片之间的外边距 (Margin) */
        margin-bottom: 16px !important;
    }
    
    /* 💡 鼠标悬停在大卡片上时的动态效果（可选，增加交互高级感） */
    div[data-testid="stVerticalBlockBorderContainer"]:hover {
        border-color: #A0A0A0 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
        transition: all 0.2s ease-in-out;
    }
    

        </style>
        """,
    )

st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 5px solid #B8B8B8 !important;
        border-radius: 12px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _get_article_data(
    ticker: str,
    source_articles=None,
    source_urls=None,
):
    """
    Retrieve only the articles that were actually used
    by the company-level daily summary.

    Priority:
    1. source_articles -> exact article_id match
    2. source_urls -> exact article_url fallback
    3. no lineage -> return empty result

    Never fall back to ticker/date-based broad retrieval.
    """

    # --------------------------------------------------
    # 1. Preferred: source_articles
    # --------------------------------------------------

    article_ids = []

    if source_articles:
        for item in source_articles:
            if isinstance(item, dict):
                article_id = item.get("article_id")
            else:
                article_id = item

            if article_id is not None:
                try:
                    article_ids.append(int(article_id))
                except (TypeError, ValueError):
                    continue

    article_ids = list(dict.fromkeys(article_ids))

    if article_ids:
        return read_sql(
            """
            SELECT
                na.ticker_or_entity AS ticker,
                na.sentiment AS overall_sentiment,
                na.summary,
                nr.headline AS title,
                nr.source_code AS source_name,
                nr.article_url,
                nr.published_date
            FROM news_analysis na
            JOIN news_raw nr
                ON na.article_id = nr.article_id
            WHERE na.ticker_or_entity = :ticker
              AND na.article_id = ANY(:article_ids)
            ORDER BY
                nr.published_date DESC NULLS LAST
            """,
            {
                "ticker": ticker,
                "article_ids": article_ids,
            },
        )

    # --------------------------------------------------
    # 2. Fallback: source_urls
    # --------------------------------------------------

    urls = []

    if source_urls:
        for url in source_urls:
            if url:
                urls.append(str(url))

    urls = list(dict.fromkeys(urls))

    if urls:
        return read_sql(
            """
            SELECT
                na.ticker_or_entity AS ticker,
                na.sentiment AS overall_sentiment,
                na.summary,
                nr.headline AS title,
                nr.source_code AS source_name,
                nr.article_url,
                nr.published_date
            FROM news_analysis na
            JOIN news_raw nr
                ON na.article_id = nr.article_id
            WHERE na.ticker_or_entity = :ticker
              AND nr.article_url = ANY(:source_urls)
            ORDER BY
                nr.published_date DESC NULLS LAST
            """,
            {
                "ticker": ticker,
                "source_urls": urls,
            },
        )

    # --------------------------------------------------
    # 3. No lineage available
    # --------------------------------------------------

    return read_sql(
        """
        SELECT
            NULL::TEXT AS ticker,
            NULL::TEXT AS overall_sentiment,
            NULL::TEXT AS summary,
            NULL::TEXT AS title,
            NULL::TEXT AS source_name,
            NULL::TEXT AS article_url,
            NULL::DATE AS published_date
        WHERE FALSE
        """
    )

def _render_articles(
    ticker: str,
    source_articles=None,
    source_urls=None,
):
    articles = _get_article_data(
        ticker=ticker,
        source_articles=source_articles,
        source_urls=source_urls,
    )

    if articles.empty:
        st.caption(
            "Article-level source lineage is not available for this summary."
        )
        return

    for _, article in articles.iterrows():

        title = article.get("title") or "Untitled article"
        source_name = article.get("source_name") or "Unknown source"
        article_url = article.get("article_url")
        published_date = article.get("published_date")
        sentiment = article.get("overall_sentiment") or "NEUTRAL"
        summary = article.get("summary")

        sentiment_config = _get_sentiment_config(sentiment)

        icon = sentiment_config["icon"]

        if published_date is not None:
            published_display = str(published_date)
        else:
            published_display = ""

        st.html(
            f"""
            <div class="fm-news-article">
                <div class="fm-news-article-title">
                    {icon} {html.escape(str(title))}
                </div>

                <div class="fm-news-article-meta">
                    {html.escape(str(source_name))}
                    {" · " + html.escape(published_display)
                     if published_display else ""}
                </div>
            </div>
            """,
        )

        if summary:
            st.caption(str(summary))

        if article_url:
            st.link_button(
                "Read Article ↗",
                article_url,
                key=(
                    f"news-{ticker}-"
                    f"{article_url}"
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
            nds.source_articles,
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
        with st.container(border=True):

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

                        <span>  📰 {article_count} articles </span>
                        <span class="news-stat-positive"> ↑ {bullish_count} Bullish</span>
                        <span class="news-stat-negative"> ↓ {bearish_count} Bearish</span>
                        <span class="news-stat-neutral"> → {neutral_count} Neutral</span>
                        <span class="news-stat-mixed"> ◆ {mixed_count} Mixed</span>

                    </div>
                </div>

                """,
            )

            # --------------------------------------------------------
            # Key points
            # --------------------------------------------------------

            key_points = row["key_points"]

            if key_points:
                if isinstance(key_points, str):
                    try:
                        import json
                        key_points = json.loads(key_points)
                    except Exception:
                        key_points = [key_points]

                if isinstance(key_points, list):
                        key_points_html = '<div class="news-section-title">KEY DEVELOPMENTS</div>'
                        for point in key_points:
                            point = _safe_text(point)
                            key_points_html += f'<div class="news-key-point">• {point}</div>'
                        
                        st.html(key_points_html)

            # 3. Nest the standard expander directly at the base of the container layout
            # It will safely open and close within the unified parent border boundary.
            with st.expander(f"View {article_count} articles"):
                
                # Runs your existing article loop smoothly with zero modifications!
                _render_articles(
                    ticker=ticker,
                    source_articles=row["source_articles"],
                    source_urls=row["source_urls"],
                )

        # --------------------------------------------------------
        # 🌟 4. Custom Gutter Separator Line (Placed Outside the Card Box)
        # --------------------------------------------------------
        st.html('<div class="news-separator" style="margin: 24px 0; border-bottom: 2px solid #D9D3D3; height: 0;"></div>')