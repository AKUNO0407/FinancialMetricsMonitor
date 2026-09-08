import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from dashboard.components.market_pulse import render_market_pulse
from dashboard.components.index_trend import render_index_trend
from dashboard.components.treemap import render_treemap
from dashboard.components.prospective_events import render_prospective_events
from dashboard.components.news_summary import render_news_summary
from dashboard.utils.db_client import read_sql

from datetime import datetime
from zoneinfo import ZoneInfo

def get_pipeline_status():
    df = read_sql(
        """
        SELECT
            pipeline_run_id,
            MAX(finished_at) AS finished_at,
            COUNT(*) FILTER (
                WHERE status = 'FAILED'
            ) AS failed_jobs,
            COUNT(*) AS job_count
        FROM job_runs
        GROUP BY pipeline_run_id
        ORDER BY MAX(finished_at) DESC
        LIMIT 1
        """
    )

    if df.empty:
        return None

    row = df.iloc[0]

    return {
        "pipeline_run_id": row["pipeline_run_id"],
        "finished_at": row["finished_at"],
        "failed_jobs": int(row["failed_jobs"] or 0),
        "job_count": int(row["job_count"] or 0),
    }



st.set_page_config(
    page_title="AI Infrastructure Market Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

pipeline = get_pipeline_status()

toronto_now = datetime.now(
    ZoneInfo("America/Toronto")
)
today_display = toronto_now.strftime(
    "%B %d, %Y"
).replace(" 0", " ")

if pipeline is None:
    pipeline_status = "Data pipeline status unavailable"
    pipeline_class = "pipeline-warning"

elif pipeline["failed_jobs"] > 0:
    pipeline_status = "Data pipeline completed with warnings"
    pipeline_class = "pipeline-warning"

else:
    pipeline_status = "Data pipeline healthy"
    pipeline_class = "pipeline-success"

# ============================================================
# Global dashboard styling
# ============================================================

st.markdown(
    """
    <style>

    /* ---------- Overall page ---------- */

    .block-container {
        max-width: 1600px;
        padding-top: 1.25rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }

    /* Reduce Streamlit's default vertical spacing */
    div[data-testid="stVerticalBlock"] {
        gap: 0.45rem;
    }

    .fm-dashboard-meta {
        margin-top: 0.1rem;
        margin-bottom: 0.25rem;
    }

    .fm-dashboard-date {
        font-size: 0.85rem;
        color: rgba(128, 128, 128, 0.95);
    }

    .pipeline-success,
    .pipeline-warning {
        display: inline-block;
        font-size: 0.78rem;
        font-weight: 600;
        margin-bottom: 1.1rem;
    }

    .pipeline-success {
        color: #2e8b57;
    }

    .pipeline-warning {
        color: #c58a00;
    }

    /* ---------- Main title ---------- */

    .fm-dashboard-title {
        display: block;
        font-size: 2rem;
        font-weight: 700;
        line-height: 1.15;
        margin: 0 0 0.15rem 0;
        letter-spacing: -0.02em;
    }

    .fm-dashboard-subtitle {
        font-size: 0.95rem;
        color: rgba(128, 128, 128, 0.95);
        margin-bottom: 1.1rem;
    }

    /* ---------- Section headers ---------- */

    .section-header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-top: 0.75rem;
        margin-bottom: 0.45rem;
    }

    .section-title {
        font-size: 1.25rem;
        font-weight: 700;
        letter-spacing: -0.01em;
    }

    .section-subtitle {
        font-size: 0.82rem;
        color: rgba(128, 128, 128, 0.9);
        margin-left: 0.6rem;
    }

    /* ---------- Small spacing ---------- */

    .section-gap {
        height: 0.55rem;
    }

    /* ---------- Company detail ---------- */

    .company-detail-card {
        border: 1px solid rgba(128, 128, 128, 0.18);
        border-radius: 12px;
        padding: 1rem 1.2rem;
        margin-top: 0.2rem;
        margin-bottom: 0.5rem;
        background: rgba(128, 128, 128, 0.035);
    }

    .company-detail-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
    }

    .company-detail-name {
        font-size: 1.25rem;
        font-weight: 700;
        line-height: 1.2;
    }

    .company-detail-meta {
        margin-top: 0.2rem;
        font-size: 0.82rem;
        color: rgba(128, 128, 128, 0.9);
    }

    .company-detail-price {
        font-size: 1.45rem;
        font-weight: 700;
    }

    .detail-section-title {
        font-size: 1rem;
        font-weight: 650;
        margin-top: 0.45rem;
        margin-bottom: 0.15rem;
    }

    /* ---------- Remove excessive divider spacing ---------- */

    hr {
        margin-top: 0.65rem !important;
        margin-bottom: 0.65rem !important;
    }

    /* ---------- Radio buttons ---------- */

    div[data-testid="stRadio"] {
        margin-bottom: 0.2rem;
    }

    div[data-testid="stRadio"] label {
        font-size: 0.88rem;
    }

    /* ---------- Dataframe ---------- */

    div[data-testid="stDataFrame"] {
        border-radius: 10px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# Header
# ============================================================
st.title("AI Infrastructure Market Dashboard")

st.html(
    f"""

    <div class="fm-dashboard-subtitle">
        US Market · AI Infrastructure · Earnings · Macro · News
    </div>

    <div class="fm-dashboard-meta">
        <span class="fm-dashboard-date">
            {today_display}
        </span>
    </div>

    <div class="{pipeline_class}">
        ● {pipeline_status}
    </div>
    """,
)


# ============================================================
# Market Pulse
# ============================================================

# st.markdown(
#     """
#     <div class="section-header">
#         <div class="section-title">Market Pulse</div>
#         <div class="section-subtitle">AI infrastructure segment performance</div>
#     </div>
#     """,
#     unsafe_allow_html=True,
# )

render_market_pulse()


# ============================================================
# Market Overview
# ============================================================

st.markdown(
    """
    <div class="section-header">
        <div class="section-title">Market Overview</div>

    </div>
    """,
    unsafe_allow_html=True,
)

days = st.radio(
    "Lookback",
    [7, 14, 30, 60],
    index=1,
    format_func=lambda x: f"{x}D",
    horizontal=True,
    label_visibility="collapsed",
)

render_index_trend(days=days)


# ============================================================
# AI Infrastructure Map
# ============================================================

# st.markdown(
#     """
#     <div class="section-header">
#         <div class="section-title">AI Infrastructure Map</div>
#         <div class="section-subtitle">
#             Market cap × daily return · click a company for details
#         </div>
#     </div>
#     """,
#     unsafe_allow_html=True,
# )

render_treemap()


# ============================================================
# Upcoming Events
# ============================================================

# st.markdown(
#     """
#     <div class="section-header">
#         <div class="section-title">Upcoming Events</div>
#         <div class="section-subtitle">Next 7 days</div>
#     </div>
#     """,
#     unsafe_allow_html=True,
# )

render_prospective_events()


# ============================================================
# Key News
# ============================================================

# st.markdown(
#     """
#     <div class="section-header">
#         <div class="section-title">Key News</div>
#         <div class="section-subtitle">
#             Company-level news intelligence
#         </div>
#     </div>
#     """,
#     unsafe_allow_html=True,
# )

render_news_summary()

