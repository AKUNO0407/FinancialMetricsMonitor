"""ETL package for the Sector Monitor Dashboard.

Modules:
    db.py               - shared SQLAlchemy engine/session helper
    prices.py            - yfinance price/index ETL job
    watchlist.py         - GICS pre-filter + manual override resolution job
    news_scraper.py      - sitemap/RSS scraper (ported from news_monitor.py)
    news_summary.py      - LLM/rule-based executive summary generation
    earnings_calendar.py - NASDAQ earnings calendar -> prospective_events
    notify.py            - SMTP failure alert helper
    run_all.py            - orchestrates all jobs with retry/backoff, used by GitHub Actions
"""
