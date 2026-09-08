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

                detail_text = " · ".join(
                    details
                )

                st.markdown(
                    f"""
                    - 💰 **{company} ({ticker})**
                      <br>
                      <span style="color:gray">
                      Earnings · {timing}
                      </span>
                    """,
                    unsafe_allow_html=True,
                )

                if detail_text:
                    st.caption(
                        detail_text
                    )