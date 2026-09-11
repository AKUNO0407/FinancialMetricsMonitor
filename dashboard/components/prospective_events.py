import streamlit as st

from dashboard.utils.db_client import read_sql

EVENT_ICONS = {
    "FOMC": "🏦",
    "CPI": "🛒",
    "PPI": "🏭",
    "PCE": "🛍️",
    "NFP": "💼",
    "GDP": "📈",
    "ISM": "⚙️", 
}


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def format_earnings_timing(timing):
    """Convert earnings timing into a user-friendly label."""

    if not timing:
        return "Time TBD"

    timing = str(timing).upper().strip()

    timing_map = {
        "BMO": "Before Market Open",
        "AMC": "After Market Close",
        "DURING": "During Market Hours",
    }

    return timing_map.get(timing, str(timing))


def format_event_datetime(event_datetime, timing):
    """Format event datetime with ET timing when available."""

    if event_datetime is not None:
        try:
            return event_datetime.strftime("%b %d · %I:%M %p ET").lstrip("0")
        except (AttributeError, ValueError):
            pass

    return format_earnings_timing(timing)


def format_vs_consensus(value, consensus):
    """Return percentage difference between a value and consensus."""

    if value is None or consensus is None or consensus == 0:
        return None

    delta_pct = (value / consensus - 1) * 100

    if delta_pct > 0:
        return f"+{delta_pct:.1f}% ▲"
    elif delta_pct < 0:
        return f"{delta_pct:.1f}% ▼"
    else:
        return "0.0% —"
    
def get_consensus_status(value, consensus):
    if value is None or consensus is None:
        return None

    if value > consensus:
        return "beat"
    elif value < consensus:
        return "miss"
    return "inline"




def render_prospective_events():

    df = read_sql("""
        SELECT
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
            source
        FROM prospective_events
        WHERE event_date >= CURRENT_DATE
          AND event_date < (
              CURRENT_DATE + INTERVAL '7 days'
          )
        ORDER BY
            event_date,
            event_datetime NULLS LAST,
            ticker
    """)

    st.subheader("This Week's Important Events")

    if df.empty:
        st.info("No major events scheduled for the next 7 days.")
        return

    # ---------------------------------------------------------
    # Group by date
    # ---------------------------------------------------------
    for event_date, group in df.groupby(
        "event_date",
        sort=True,
    ):

        date_label = event_date.strftime(
            "%a · %b %d"
        ).upper()

        st.markdown(
            f"### {date_label}"
        )

        for _, row in group.iterrows():

            ticker = row["ticker"]
            event_type = row["event_type"]

            # -------------------------------------------------
            # Macro
            # -------------------------------------------------
            if ticker == "MACRO_EVENT":

                icon = EVENT_ICONS.get(
                    event_type,
                    "📅",
                )

                event_name = (
                    row["event_name"]
                    or event_type
                )

                timing = (
                    row["timing"]
                    or ""
                )

                source = (
                    row["source"]
                    or ""
                )

                st.markdown(
                    f"""
                    - {icon} **{event_name}**
                      <br>
                      <span style="color:gray">
                      {event_type} · {timing} · {source}
                      </span>
                    """,
                    unsafe_allow_html=True,
                )

            # -------------------------------------------------
            # Earnings
            # -------------------------------------------------
            elif event_type == "EARNINGS":

                company = (
                    row["company_name"]
                    or ticker
                )

                timing = (
                    row["timing"]
                    or ""
                )

                event_datetime = row["event_datetime"]

                time_label  = format_event_datetime(event_datetime, timing)
                timing_label = format_earnings_timing(timing)

                eps = row["eps_estimate"]
                revenue = row["revenue_estimate"]

                details = []

                if eps is not None:
                    details.append(
                        f"EPS ${float(eps):.2f}"
                    )

                if revenue is not None:
                    details.append(
                        f"Revenue "
                        f"${float(revenue) / 1e9:.2f}B"
                    )

                # -------------------------------------------------
                # Render
                # -------------------------------------------------

                with st.container(border=True):

                    st.html(
                        f"""
                        <div style="
                            font-size: 1.05rem;
                            font-weight: 600;
                            margin-bottom: 4px;
                        ">
                            💰 {company} ({ticker})
                        </div>

                        <div style="
                            color: #666;
                            font-size: 0.9rem;
                            margin-bottom: 10px;
                        ">
                            Earnings · {time_label}
                        </div>
                        """,
                    )

                    if details:
                        st.html(
                            f"""
                            <div style="
                                font-size: 0.9rem;
                                line-height: 1.6;
                            ">
                                {"<br>".join(details)}
                            </div>
                            """,
                        )