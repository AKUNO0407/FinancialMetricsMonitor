import html

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.utils.db_client import read_sql


# ============================================================
# Helpers
# ============================================================


def _safe_text(value):
    if value is None:
        return ""
    return html.escape(str(value))


def _format_market_cap(value):
    if value is None:
        return "N/A"

    value = float(value)

    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"

    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"

    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"

    return f"${value:,.0f}"

def _format_market_cap_short(value):
    if value is None:
        return "N/A"

    value = float(value)

    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}T"

    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    return f"{value:,.0f}"


def _format_price(value):
    if value is None:
        return "N/A"

    return f"${float(value):,.2f}"


def _format_return(value):
    if value is None:
        return "N/A"

    value = float(value)

    if value > 0:
        return f"+{value:.2f}%"

    return f"{value:.2f}%"


# ============================================================
# Data
# ============================================================

def _get_treemap_data():
    query = """
        WITH ranked_prices AS (
            SELECT
                ticker,
                price_date,
                close,
                LAG(close) OVER (
                    PARTITION BY ticker
                    ORDER BY price_date
                ) AS previous_close
            FROM prices
        ),

        latest_price AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                price_date,
                close,
                previous_close
            FROM ranked_prices
            ORDER BY ticker, price_date DESC
        ),

        latest_metadata AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                snapshot_date,
                market_cap,
                logo_url
            FROM company_metadata
            ORDER BY ticker, snapshot_date DESC
        )

        SELECT
            w.ticker,
            w.name AS company_name,
            w.ai_segment,
            w.ai_relevance_tag,

            lp.price_date,
            lp.close,
            lp.previous_close,

            CASE
                WHEN lp.previous_close IS NOT NULL
                     AND lp.previous_close <> 0
                THEN
                    (lp.close - lp.previous_close)
                    / lp.previous_close * 100
                ELSE NULL
            END AS daily_return_pct,

            lm.snapshot_date AS market_cap_date,
            lm.market_cap,
            lm.logo_url

        FROM watchlist w

        LEFT JOIN latest_price lp
            ON w.ticker = lp.ticker

        LEFT JOIN latest_metadata lm
            ON w.ticker = lm.ticker

        WHERE w.active_flag = TRUE
          AND w.is_public = TRUE
          AND w.if_retrieve_price = TRUE
          AND lm.market_cap IS NOT NULL
          AND lm.market_cap > 0

        ORDER BY
            w.ai_segment,
            lm.market_cap DESC
    """

    return read_sql(query)


# ============================================================
# Segment Market Cap Overview
# ============================================================

def _render_segment_market_cap(df):
    segment_df = (
        df.groupby("ai_segment", dropna=False)
        .agg(
            market_cap=("market_cap", "sum"),
            daily_return_pct=("daily_return_pct", "mean"),
            company_count=("ticker", "count"),
        )
        .reset_index()
    )

    segment_df["ai_segment"] = (
        segment_df["ai_segment"]
        .fillna("Other")
        .astype(str)
    )

    segment_df["daily_return_pct"] = (
        segment_df["daily_return_pct"]
        .fillna(0)
        .astype(float)
    )

    segment_df["daily_return_display"] = (
        segment_df["daily_return_pct"].round(2)
    )

    # Largest segment at top
    segment_df = segment_df.sort_values(
        "market_cap",
        ascending=True,
    )

    segment_df["market_cap_display"] = segment_df[
        "market_cap"
    ].apply(_format_market_cap_short)

    fig = px.bar(
        segment_df,
        x="market_cap",
        y="ai_segment",
        orientation="h",
        color="daily_return_pct",
        color_continuous_scale=[
            "#d73027",
            "#f7f7f7",
            "#1a9850",
        ],
        color_continuous_midpoint=0,
        custom_data=[
            "ai_segment",
            "market_cap",
            "market_cap_display",
            "daily_return_display",
            "company_count",
        ],
    )

    fig.update_traces(
        texttemplate=(
            "%{customdata[2]}"
            " · %{customdata[3]:+.2f}%"
        ),
        textposition="inside",
        insidetextanchor="end",
        hovertemplate=(
            "<b>%{customdata[0]}</b>"
            "<br>Market Cap: %{customdata[2]}"
            "<br>Avg Daily Return: %{customdata[3]:+.2f}%"
            "<br>Companies: %{customdata[4]}"
            "<extra></extra>"
        ),
    )

    fig.update_layout(
        height=max(400, len(segment_df) * 4),
        margin=dict(
            l=100,
            r=7,
            t=7,
            b=7,
        ),
        xaxis=dict(
            title=None,
            showgrid=False,
            showticklabels=False,
        ),
        yaxis=dict(
            title=None,
            tickfont=dict(size=13),
        ),
        coloraxis_colorbar=dict(
            title="Daily Return",
            ticksuffix="%",
            x=-0.3,
            xanchor="right",
            y=0.5,
            yanchor="middle",
            len=0.75,
            thickness=12,
        ),
        showlegend=False,
    )

    st.plotly_chart(
        fig,
        width='stretch',
        config={"displayModeBar": False},
        key="segment_market_cap",
    )


# ============================================================
# Company Map
# ============================================================

def _render_company_map(df):
    map_df = df.copy()

    map_df["ai_segment"] = (
        map_df["ai_segment"]
        .fillna("Other")
        .astype(str)
    )

    map_df["daily_return_pct"] = (
        map_df["daily_return_pct"]
        .fillna(0)
        .astype(float)
    )

    map_df["daily_return_display"] = (
        map_df["daily_return_pct"].round(2)
    )

    map_df["market_cap"] = (
        map_df["market_cap"]
        .astype(float)
    )

    # --------------------------------------------------------
    # Company weight
    #
    # Each segment gets equal visual area.
    # Within each segment, company size = market cap.
    # --------------------------------------------------------

    segment_totals = (
        map_df.groupby("ai_segment")["market_cap"]
        .transform("sum")
    )

    map_df["company_weight"] = (
        map_df["market_cap"] / segment_totals
    )

    map_df["company_weight"] = (
        map_df["company_weight"]
        .clip(lower=0.0001)
    )

    map_df["company_weight"] = (
        map_df.groupby("ai_segment")["company_weight"]
        .transform(lambda x: x / x.sum())
    )

    # --------------------------------------------------------
    # Segment-level statistics
    # --------------------------------------------------------

    segment_df = (
        map_df.groupby("ai_segment")
        .agg(
            segment_market_cap=("market_cap", "sum"),
            segment_daily_return=("daily_return_pct", "mean"),
            company_count=("ticker", "count"),
        )
        .reset_index()
    )

    segment_df["segment_daily_return"] = (
        segment_df["segment_daily_return"]
        .round(2)
    )

    segment_lookup = (
        segment_df
        .set_index("ai_segment")
        .to_dict("index")
    )

    # --------------------------------------------------------
    # Create hierarchy-level custom data
    #
    # Company:
    #   ticker
    #   company name
    #   segment
    #   market cap
    #   daily return
    #   price
    #
    # Segment:
    #   segment name
    #   total market cap
    #   average daily return
    #   company count
    #
    # Root:
    #   total market cap
    #   total company count
    # --------------------------------------------------------

    root_market_cap = map_df["market_cap"].sum()
    root_company_count = len(map_df)

    # --------------------------------------------------------
    # Build explicit labels for hover.
    #
    # Plotly treemap creates additional rows internally for
    # parent/root nodes. We therefore provide safe values
    # for every company row and avoid referencing missing
    # customdata fields.
    # --------------------------------------------------------

    map_df["hover_company"] = map_df["company_name"].fillna(
        map_df["ticker"]
    )

    map_df["hover_segment"] = map_df["ai_segment"]

    map_df["hover_market_cap"] = map_df["market_cap"]

    map_df["hover_return"] = (
        map_df["daily_return_display"]
    )

    map_df["hover_price"] = (
        map_df["close"]
        .fillna(0)
        .astype(float)
    )

    # --------------------------------------------------------
    # Treemap
    # --------------------------------------------------------


    fig = px.treemap(
        map_df,
        path=[
            px.Constant("AI Infrastructure"),
            "ai_segment",
            "ticker",
        ],
        values="company_weight",
        color="daily_return_pct",
        color_continuous_scale=[
            "#d73027",
            "#f7f7f7",
            "#1a9850",
        ],
        color_continuous_midpoint=0,
        custom_data=[
            "ticker",
            "hover_company",
            "hover_segment",
            "hover_market_cap",
            "hover_return",
            "hover_price",
        ],
    )

    # --------------------------------------------------------
    # Company hover
    #
    # IMPORTANT:
    # We use label/currentPath to distinguish hierarchy.
    # --------------------------------------------------------

    company_hover = (
        "<b>%{customdata[1]}</b>"
        " (%{customdata[0]})"
        "<br>Segment: %{customdata[2]}"
        "<br>Market Cap: $%{customdata[3]:,.0f}"
        "<br>Daily Return: %{customdata[4]:+.2f}%"
        "<br>Price: $%{customdata[5]:,.2f}"
        "<extra></extra>"
    )

    # --------------------------------------------------------
    # Default trace styling
    # --------------------------------------------------------

    fig.update_traces(
        texttemplate=(
            "<b>%{label}</b>"
            "<br>"
            "<span style='font-size:14px'>"
            "%{customdata[4]}%"
            "</span>"
        ),

        hovertemplate=company_hover,

        root_color="rgba(0,0,0,0)",

        marker=dict(
            line=dict(
                width=1.2,
                color="rgba(255,255,255,0.75)",
            )
        ),
    )

    # --------------------------------------------------------
    # Add custom hover text directly to treemap nodes.
    #
    # Plotly's generated hierarchy contains:
    #
    # 0 = root
    # 1 = segment
    # 2 = company
    #
    # We replace hovertemplate node-by-node so parent nodes
    # never try to read company-level customdata.
    # --------------------------------------------------------

    labels = list(fig.data[0].labels)

    parents = list(fig.data[0].parents)

    hover_templates = []

    for label, parent in zip(labels, parents):

        # ----------------------------------------------------
        # Root
        # ----------------------------------------------------

        if parent == "":
            hover_templates.append(
                (
                    "<b>AI Infrastructure</b>"
                    f"<br>Market Cap: "
                    f"${root_market_cap:,.0f}"
                    f"<br>Companies: "
                    f"{root_company_count}"
                    "<extra></extra>"
                )
            )

            continue

        # ----------------------------------------------------
        # Segment
        #
        # Parent is the root.
        # ----------------------------------------------------

        if parent == "AI Infrastructure":

            stats = segment_lookup.get(
                label,
                {
                    "segment_market_cap": 0,
                    "segment_daily_return": 0,
                    "company_count": 0,
                },
            )

            hover_templates.append(
                (
                    f"<b>{_safe_text(label)}</b>"
                    f"<br>Market Cap: "
                    f"${stats['segment_market_cap']:,.0f}"
                    f"<br>Avg Daily Return: "
                    f"{stats['segment_daily_return']:+.2f}%"
                    f"<br>Companies: "
                    f"{stats['company_count']}"
                    "<extra></extra>"
                )
            )

            continue

        # ----------------------------------------------------
        # Company
        #
        # Find corresponding company row.
        # ----------------------------------------------------

        company_rows = map_df[
            map_df["ticker"].astype(str) == str(label)
        ]

        if not company_rows.empty:

            row = company_rows.iloc[0]

            company_name = _safe_text(
                row["company_name"]
            )

            ticker = _safe_text(
                row["ticker"]
            )

            segment = _safe_text(
                row["ai_segment"]
            )

            market_cap = float(
                row["market_cap"]
            )

            daily_return = float(
                row["daily_return_display"]
            )

            price = (
                float(row["close"])
                if row["close"] is not None
                else None
            )

            if price is not None:

                hover_templates.append(
                    (
                        f"<b>{company_name}</b>"
                        f" ({ticker})"
                        f"<br>Segment: {segment}"
                        f"<br>Market Cap: "
                        f"${market_cap:,.0f}"
                        f"<br>Daily Return: "
                        f"{daily_return:+.2f}%"
                        f"<br>Price: "
                        f"${price:,.2f}"
                        "<extra></extra>"
                    )
                )

            else:

                hover_templates.append(
                    (
                        f"<b>{company_name}</b>"
                        f" ({ticker})"
                        f"<br>Segment: {segment}"
                        f"<br>Market Cap: "
                        f"${market_cap:,.0f}"
                        f"<br>Daily Return: "
                        f"{daily_return:+.2f}%"
                        "<br>Price: N/A"
                        "<extra></extra>"
                    )
                )

        else:

            hover_templates.append(
                f"<b>{_safe_text(label)}</b>"
                "<extra></extra>"
            )

    fig.data[0].hovertemplate = hover_templates

    # --------------------------------------------------------
    # Layout
    # --------------------------------------------------------

    fig.update_layout(
        height=680,

        margin=dict(
            l=0,
            r=0,
            t=10,
            b=0,
        ),

        coloraxis_colorbar=dict(
            title="Daily Return",
            ticksuffix="%",
            x=1.02,
            xanchor="left",
            y=0.5,
            yanchor="middle",
            len=0.75,
            thickness=12,
        ),

        uniformtext=dict(
            minsize=13,
            mode="hide",
        ),
    )

    # --------------------------------------------------------
    # Render + click interaction
    # --------------------------------------------------------

    event = st.plotly_chart(
        fig,
        width='stretch',
        config={
            "displayModeBar": False,
        },
        on_select="rerun",
        selection_mode="points",
        key="ai_infra_company_map",
    )

    selected_ticker = None

    try:
        point_indices = event.selection.point_indices

        if point_indices:
            selected_index = point_indices[0]

            # Only allow actual company nodes to trigger
            # company detail.
            if 0 <= selected_index < len(labels):

                clicked_label = labels[selected_index]
                clicked_parent = parents[selected_index]

                if clicked_parent != "AI Infrastructure":

                    if clicked_label in map_df[
                        "ticker"
                    ].values:
                        selected_ticker = clicked_label

    except Exception:
        selected_ticker = None

    # --------------------------------------------------------
    # Company detail
    # --------------------------------------------------------

    if selected_ticker:

        selected_row = map_df[
            map_df["ticker"] == selected_ticker
        ]

        if not selected_row.empty:

            row = selected_row.iloc[0]

            st.html(
                "<div style='height:8px'></div>"
            )

            _render_company_detail(
                ticker=row["ticker"],
                company_name=row["company_name"],
                segment=row["ai_segment"],
            )

    else:

        st.caption(
            "Click a company in the map to view price details."
        )

# ============================================================
# Company Detail
# ============================================================

def _get_company_detail(ticker):
    query = """
        WITH ranked_prices AS (
            SELECT
                ticker,
                price_date,
                close,

                LAG(close) OVER (
                    PARTITION BY ticker
                    ORDER BY price_date
                ) AS previous_close

            FROM prices

            WHERE ticker = :ticker
        )

        SELECT
            ticker,
            price_date,
            close,
            previous_close,

            CASE
                WHEN previous_close IS NOT NULL
                     AND previous_close <> 0
                THEN
                    (close - previous_close)
                    / previous_close * 100
                ELSE NULL
            END AS daily_return_pct

        FROM ranked_prices

        ORDER BY price_date DESC

        LIMIT 60
    """

    return read_sql(
        query,
        {"ticker": ticker},
    )


def _render_company_detail(
    ticker,
    company_name,
    segment,
):
    df = _get_company_detail(ticker)

    if df.empty:
        st.info(
            f"No price history available for {ticker}."
        )
        return

    df = df.sort_values("price_date")

    latest = df.iloc[-1]

    latest_price = latest["close"]
    daily_return = latest["daily_return_pct"]

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    st.html(
        f"""
        <div class="company-detail-card">

            <div class="company-detail-header">

                <div>

                    <div class="company-detail-name">
                        {_safe_text(company_name)}
                    </div>

                    <div class="company-detail-meta">
                        {_safe_text(ticker)}
                        ·
                        {_safe_text(
                            segment or "AI Infrastructure"
                        )}
                    </div>

                </div>

                <div class="company-detail-price">
                    {_format_price(latest_price)}
                </div>

            </div>

        </div>
        """
    )

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    metric_col1, metric_col2, metric_col3 = st.columns(3)

    with metric_col1:
        st.metric(
            "Price",
            _format_price(latest_price),
        )

    with metric_col2:
        st.metric(
            "Daily Return",
            _format_return(daily_return),
        )

    market_cap_df = read_sql(
        """
        SELECT market_cap
        FROM company_metadata
        WHERE ticker = :ticker
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
        {"ticker": ticker},
    )

    with metric_col3:
        if not market_cap_df.empty:
            market_cap = market_cap_df.iloc[0][
                "market_cap"
            ]

            st.metric(
                "Market Cap",
                _format_market_cap(market_cap),
            )

        else:
            st.metric(
                "Market Cap",
                "N/A",
            )

    # --------------------------------------------------------
    # Price Performance
    # --------------------------------------------------------

    st.html(
        """
        <div class="detail-section-title">
            Price Performance
        </div>
        """
    )

    chart_df = df[
        [
            "price_date",
            "close",
        ]
    ].copy()

    chart_df["price_date"] = (
        chart_df["price_date"].astype(str)
    )

    fig = px.line(
        chart_df,
        x="price_date",
        y="close",
    )

    fig.update_traces(
        hovertemplate=(
            "%{x}"
            "<br>$%{y:.2f}"
            "<extra></extra>"
        )
    )

    fig.update_layout(
        height=260,
        margin=dict(
            l=0,
            r=0,
            t=10,
            b=0,
        ),
        xaxis_title=None,
        yaxis_title=None,
        hovermode="x unified",
    )

    st.plotly_chart(
        fig,
        width='stretch',
        config={"displayModeBar": False},
    )


# ============================================================
# Main renderer
# ============================================================

def render_treemap():
    df = _get_treemap_data()

    if df.empty:
        st.info(
            "No AI infrastructure map data available."
        )
        return

    df = df.dropna(
        subset=["market_cap"]
    ).copy()

    df["market_cap"] = (
        df["market_cap"].astype(float)
    )

    df["daily_return_pct"] = (
        df["daily_return_pct"]
        .fillna(0)
        .astype(float)
    )

    # --------------------------------------------------------
    # Section title
    # --------------------------------------------------------

    st.html(
        """
        <div class="section-header">

            <div>
                <div class="section-title">
                    AI Infrastructure Map
                </div>

                <div class="section-subtitle">
                    Segment market cap ·
                    Company market cap ·
                    Daily return
                </div>
            </div>

        </div>
        """
    )

    # --------------------------------------------------------
    # Two-column layout
    # --------------------------------------------------------

    left_col, right_col = st.columns(
        [0.8, 1.7],
        gap="small",
    )

    with left_col:

        st.html(
            """
            <div style="
                font-size:1.05rem;
                font-weight:700;
                margin-bottom:0.15rem;
            ">
                Segment Market Cap
            </div>

            <div style="
                font-size:0.78rem;
                color:rgba(128,128,128,.9);
                margin-bottom:0.35rem;
            ">
                Total market cap by AI infrastructure segment
            </div>
            """
        )

        _render_segment_market_cap(df)

    with right_col:

        st.html(
            """
            <div style="
                font-size:1.05rem;
                font-weight:700;
                margin-bottom:0.15rem;
            ">
                Company Map
            </div>

            <div style="
                font-size:0.78rem;
                color:rgba(128,128,128,.9);
                margin-bottom:0.35rem;
            ">
                Equal-weight segments ·
                company size = market cap
            </div>
            """
        )

        _render_company_map(df)