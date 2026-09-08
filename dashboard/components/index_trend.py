import plotly.express as px
import streamlit as st

from dashboard.utils.db_client import read_sql


INDEX_MAP = {
    "^DJI": "Dow Jones Industrial Average",
    "^GSPC": "S&P 500 Index",
    "^NDX": "Nasdaq-100 Index",
    "^SOX": "PHLX Semiconductor Index",
}


def render_index_trend(
    days: int = 7,
):

    df = read_sql(
        """
        SELECT
            ticker,
            price_date,
            close
        FROM prices
        WHERE ticker IN (
            '^DJI',
            '^GSPC',
            '^NDX',
            '^SOX'
        )
        AND price_date >= (
            CURRENT_DATE - :days
        )
        ORDER BY price_date
        """,
        {"days": days},
    )

    if df.empty:
        st.warning(
            "No index price data available."
        )
        return

    df["index_name"] = (
        df["ticker"].map(INDEX_MAP)
    )

    # ---------------------------------------------------------
    # Standardized performance
    # ---------------------------------------------------------
    df["normalized"] = (
        df.groupby("ticker")["close"]
        .transform(
            lambda x: x / x.iloc[0] * 100
        )
    )
    st.markdown("### Relative Market Performance")

    fig = px.line(
        df,
        x="price_date",
        y="normalized",
        color="index_name",
        markers=True,
        title="Standardized Market Index Performance",
    )

    fig.update_layout(
        yaxis_title="Indexed Performance",
        xaxis_title=None,
        legend_title=None,
        height=400,
    )
    fig.add_hline(
        y=100,
        line_dash="dash",
        annotation_text="Start = 100",
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{fullData.name}</b><br>"
            "Date: %{x}<br>"
            "Indexed Price: %{y:.2f}<br>"
            "<extra></extra>"
        )
    )

    st.plotly_chart(
        fig,
        width='stretch',
    )
    st.caption(
        "Standardized formula: Indexed Price = "
        "Price ÷ first price in the selected lookback × 100. "
        "A value of 105 means the index is up 5% from the "
        "start of the selected period."
    )

    # ---------------------------------------------------------
    # Raw price charts
    # ---------------------------------------------------------
    st.markdown("### Major Market Indices")

    index_order = [
        "^DJI",
        "^GSPC",
        "^NDX",
        "^SOX",
    ]

    row1 = st.columns(2)

    for col, ticker in zip(row1, index_order[:2]):

        index_df = df[
            df["ticker"] == ticker
        ].copy()

        if index_df.empty:
            continue

        fig = px.line(
            index_df,
            x="price_date",
            y="close",
            markers=True,
            title=INDEX_MAP[ticker],
        )

        fig.update_layout(
            xaxis_title=None,
            yaxis_title="Index Level",
            height=300,
        )

        fig.update_traces(
            hovertemplate=(
                f"<b>{INDEX_MAP[ticker]}</b><br>"
                "Date: %{x}<br>"
                "Close: %{y:,.2f}"
                "<extra></extra>"
            )
        )

        col.plotly_chart(
            fig,
            width='stretch',
        )

    row2 = st.columns(2)

    for col, ticker in zip(row2, index_order[2:]):

        index_df = df[
            df["ticker"] == ticker
        ].copy()

        if index_df.empty:
            continue

        fig = px.line(
            index_df,
            x="price_date",
            y="close",
            markers=True,
            title=INDEX_MAP[ticker],
        )

        fig.update_layout(
            xaxis_title=None,
            yaxis_title="Index Level",
            height=300,
        )

        fig.update_traces(
            hovertemplate=(
                f"<b>{INDEX_MAP[ticker]}</b><br>"
                "Date: %{x}<br>"
                "Close: %{y:,.2f}"
                "<extra></extra>"
            )
        )

        col.plotly_chart(
            fig,
            width='stretch',
        )