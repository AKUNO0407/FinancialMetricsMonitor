import plotly.graph_objects as go
import streamlit as st

from dashboard.utils.db_client import read_sql

import plotly.graph_objects as go
import streamlit as st

from dashboard.utils.db_client import read_sql


INDEX_NAMES = {
    "^DJI": "DJI",
    "^GSPC": "S&P 500",
    "^NDX": "NASDAQ 100",
    "^SOX": "SOX",
}


def _format_market_cap(value) -> str:
    """
    Format market cap for display.
    """
    if value is None:
        return "N/A"

    value = float(value)

    if value >= 1e12:
        return f"${value / 1e12:.2f}T"

    if value >= 1e9:
        return f"${value / 1e9:.1f}B"

    if value >= 1e6:
        return f"${value / 1e6:.0f}M"

    return f"${value:,.0f}"


def render_market_pulse():
    st.subheader("Market Pulse")

    # =============================================================
    # 1. Major Market Indices
    # =============================================================

    index_df = read_sql("""
        WITH ranked AS (
            SELECT
                ticker,
                price_date,
                close,
                LAG(close) OVER (
                    PARTITION BY ticker
                    ORDER BY price_date
                ) AS previous_close
            FROM prices
            WHERE ticker IN (
                'DJI',
                'SP500',
                'NASDAQ100',
                'SOX'
            )
        )
        SELECT
            ticker,
            price_date,
            close,
            previous_close,
            (
                close / NULLIF(previous_close, 0) - 1
            ) AS daily_return
        FROM ranked
        WHERE price_date = (
            SELECT MAX(price_date)
            FROM prices
            WHERE ticker IN (
                'DJI',
                'SP500',
                'NASDAQ100',
                'SOX'
            )
        )
        ORDER BY ticker
    """)

    cols = st.columns(4)

    for i, ticker in enumerate(INDEX_NAMES):

        row = index_df[
            index_df["ticker"] == ticker
        ]

        if row.empty:
            continue

        value = row["daily_return"].iloc[0]

        if value is None:
            display_value = "N/A"
        else:
            display_value = (
                f"{float(value) * 100:+.2f}%"
            )

        cols[i].metric(
            INDEX_NAMES[ticker],
            display_value,
        )

    # =============================================================
    # 2. Watchlist / AI Infrastructure
    # =============================================================

    watchlist_df = read_sql("""
        WITH ranked_prices AS (
            SELECT
                p.ticker,
                p.price_date,
                p.close,
                LAG(p.close) OVER (
                    PARTITION BY p.ticker
                    ORDER BY p.price_date
                ) AS previous_close
            FROM prices p
            JOIN watchlist w
                ON p.ticker = w.ticker
            WHERE w.active_flag = TRUE
              AND w.if_retrieve_price = TRUE
        ),

        latest_prices AS (
            SELECT
                ticker,
                price_date,
                close,
                previous_close
            FROM ranked_prices
            WHERE price_date = (
                SELECT MAX(price_date)
                FROM prices
            )
        ),

        latest_metadata AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                market_cap
            FROM company_metadata
            ORDER BY
                ticker,
                snapshot_date DESC
        )

        SELECT
            p.ticker,
            w.ai_segment,
            p.price_date,
            p.close,
            p.previous_close,
            m.market_cap,
            (
                p.close /
                NULLIF(p.previous_close, 0) - 1
            ) AS daily_return
        FROM latest_prices p

        JOIN watchlist w
            ON p.ticker = w.ticker

        LEFT JOIN latest_metadata m
            ON p.ticker = m.ticker

        WHERE w.active_flag = TRUE
          AND w.if_retrieve_price = TRUE
          AND w.ai_segment IS NOT NULL
    """)

    if watchlist_df.empty:
        st.info(
            "No AI infrastructure price data available."
        )
        return

    # =============================================================
    # 3. Segment Aggregation
    # =============================================================

    segment_df = (
        watchlist_df
        .groupby("ai_segment")
        .agg(
            market_cap=(
                "market_cap",
                "sum",
            ),
            daily_return=(
                "daily_return",
                "mean",
            ),
            stocks=(
                "ticker",
                "count",
            ),
            up=(
                "daily_return",
                lambda x: (x > 0).sum(),
            ),
            flat=(
                "daily_return",
                lambda x: (x == 0).sum(),
            ),
            down=(
                "daily_return",
                lambda x: (x < 0).sum(),
            ),
        )
        .reset_index()
    )

    segment_df["daily_return_pct"] = (
        segment_df["daily_return"] * 100
    )

    segment_df["market_cap_display"] = (
        segment_df["market_cap"]
        .apply(_format_market_cap)
    )

    segment_df["breadth"] = (
        "↑ "
        + segment_df["up"].astype(str)
        + " / → "
        + segment_df["flat"].astype(str)
        + " / ↓ "
        + segment_df["down"].astype(str)
    )

    segment_df = segment_df.sort_values(
        "daily_return_pct",
        ascending=False,
    )

    # =============================================================
    # 4. Heatmap
    # =============================================================

    st.markdown(
        "### AI Infrastructure Segment Performance"
    )

    heatmap = go.Figure(
        data=go.Heatmap(
            z=[
                segment_df[
                    "daily_return_pct"
                ].tolist()
            ],
            x=segment_df[
                "ai_segment"
            ].tolist(),
            y=["Daily Return"],
            text=[
                [
                    f"{value:+.2f}%"
                    for value
                    in segment_df[
                        "daily_return_pct"
                    ]
                ]
            ],
            texttemplate="%{text}",
            customdata=[
                [
                    [
                        row["market_cap_display"],
                        int(row["stocks"]),
                        int(row["up"]),
                        int(row["flat"]),
                        int(row["down"]),
                    ]
                    for _, row
                    in segment_df.iterrows()
                ]
            ],
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Daily Return: %{z:+.2f}%<br>"
                "Market Cap: %{customdata[0]}<br>"
                "Stocks: %{customdata[1]}<br>"
                "Up: %{customdata[2]}<br>"
                "Flat: %{customdata[3]}<br>"
                "Down: %{customdata[4]}"
                "<extra></extra>"
            ),
            colorscale=[
                [0.0, "red"],
                [0.5, "white"],
                [1.0, "green"],
            ],
            zmid=0,
        )
    )

    heatmap.update_layout(
        height=170,
        margin=dict(
            t=10,
            l=10,
            r=10,
            b=10,
        ),
        xaxis=dict(
            title=None,
            tickangle=-35,
        ),
        yaxis=dict(
            title=None,
            showticklabels=False,
        ),
    )

    st.plotly_chart(
        heatmap,
        width='stretch',
    )

    # =============================================================
    # 5. Detailed Table
    # =============================================================

    display_df = segment_df[
        [
            "ai_segment",
            "market_cap_display",
            "daily_return_pct",
            "stocks",
            "up",
            "flat",
            "down",
        ]
    ].copy()

    display_df.columns = [
        "Segment",
        "Market Cap",
        "Daily Return",
        "Stocks",
        "Up",
        "Flat",
        "Down",
    ]

    st.dataframe(
        display_df.style.format(
            {
                "Daily Return": "{:+.2f}%",
            }
        ),
        width='stretch',
        hide_index=True,
        column_config={
            col: st.column_config.Column(
                alignment="left"
            )
            for col in display_df.columns
        },
    )

    st.caption(
        "Segment daily return = equal-weight average of "
        "constituent stock daily returns. Market Cap = "
        "sum of available constituent market caps. "
        "Breadth shows the number of stocks that rose, "
        "were unchanged, or declined."
    )