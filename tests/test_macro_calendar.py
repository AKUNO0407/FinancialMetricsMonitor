from datetime import date, datetime, timedelta

from etl.macro_calendar import (
    _get_fomc_events,
    _get_bea_events,
    _get_bls_events,
    ET,
)

def main():

    print("============================================")
    print("       MACRO CALENDAR INTEGRATION TEST")
    print("============================================")

    print("\n========== FOMC ==========")
    fomc_events = _get_fomc_events()

    for event in fomc_events:
        print(
            event["event_date"],
            "|",
            event["event_type"],
            "|",
            event["event_name"],
            "|",
            event["timing"],
            "|",
            event["source"],
        )

    print(f"FOMC events: {len(fomc_events)}")

    print("\n========== BEA ==========")
    bea_events = _get_bea_events()

    for event in bea_events:
        print(
            event["event_date"],
            "|",
            event["event_type"],
            "|",
            event["event_name"],
            "|",
            event["timing"],
            "|",
            event["source"],
        )

    print(f"BEA events: {len(bea_events)}")

    print("\n========== BLS ==========")
    bls_events = _get_bls_events()

    for event in bls_events:
        print(
            event["event_date"],
            "|",
            event["event_type"],
            "|",
            event["event_name"],
            "|",
            event["timing"],
            "|",
            event["source"],
        )

    print(f"BLS events: {len(bls_events)}")

    print("\n========== COMBINED ==========")

    events = (
        fomc_events
        + bea_events
        + bls_events
    )

    events.sort(
        key=lambda x: (
            x["event_date"],
            x["event_datetime"]
            or datetime.min.replace(
                tzinfo=ET
            ),
        )
    )

    for event in events:
        print(
            event["event_date"],
            "|",
            event["event_type"],
            "|",
            event["event_name"],
            "|",
            event["timing"],
            "|",
            event["source"],
        )

    print(
        f"\nTOTAL EVENTS: {len(events)}"
    )


if __name__ == "__main__":
    main()