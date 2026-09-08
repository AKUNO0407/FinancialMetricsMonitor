# Sector Monitor Dashboard


This dashboard serves the purpose of sector monitoring. In particular, this dashboard focuses on the AI industry under the Information & Technology sector, providing daily-refreshed data at 18:00 Toronto time automatically. Notice that this dashboard is of standardized framework and can be used as a template, with easy transferability to other industries.

## Scope

This dashboard covers public equity under AI industry under the Information & Technology sector. More specificially, the scope is defined by a watchlist that limits by single name's GICS by default. However, it also supports mannually adding more single names into the watchlist with the acknowledgment that many AI-focus or AI-influential companies are not classified under AI or even IT sector by their GICS code.

This dashboard also tracks the most well-known indices of US market, including Dow & Jones, Nasdaq 100, S&P 500, PHLX Semiconductor Sector Index.

This dashboard also tracks the AI-related news and financial events (prosepectively at most seven calendar days) and provide a summary (as well as link) to AI-related news or financial events happened yesterday (retrospectively). 

## Structure

The dashboard mainly contains four different parts: 
1. Index Trend;
2. Watchlist treemap;
3. Propsective events (in a horizontal timeline style);
4. Retrspective news & financial events summary (in a horizontal list of executive summary format, with tile hyperlinked)

## Overall Workflow (pending)

config/ai_exposure.yaml ─┐
                          ├──▶ etl/watchlist.py ──▶ watchlist 表 ──┐
GICS 数据源(待定) ────────┘                                        │
                                                                    ▼
config/news_feed.json ──▶ etl/news_scraper.py ──▶ news_raw 表 ──▶ etl/news_summary.py ──▶ news_summary 表
                                                                    
etl/prices.py (yfinance) ──▶ prices 表
etl/earnings_calendar.py (NASDAQ API) ──▶ prospective_events 表

etl/run_all.py 编排以上所有 job（含重试+失败邮件告警 etl/notify.py）
        │
        ▼
.github/workflows/etl_daily.yml (每日定时触发 run_all.py)
        │
        ▼
dashboard/app.py 只读 Postgres，渲染 4 个组件
    - index_trend.py      ← prices
    - treemap.py           ← watchlist + prices
    - prospective_events.py ← prospective_events
    - news_summary.py      ← news_summary
  

文件依赖关系
所有 ETL job 共用 etl.db.get_engine
etl.run_all.run_job_with_retry 调用各 job 的 run()/入口函数，失败时用 etl.notify.send_alert
etl.news_scraper.scrape_headlines 依赖 watchlist 表（由 etl.watchlist.run 填充）才能做 alias 匹配，所以 watchlist job 必须先于 news_scraper 跑（JOBS 列表顺序已经是对的）
Schema 定义在 schema.sql，由 init_db.py 执行


   ### 数据流与文件关系

   #### ETL 执行顺序 (etl/run_all.py)
   1. watchlist.py   — 决定 underlying 组合 (ticker + aliases)
   2. prices.py      — 拉取行情
   3. news_scraper.py — 抓新闻并按 watchlist.aliases 匹配
   4. news_summary.py — 生成摘要
   5. earnings_calendar.py — 抓财报日历

   #### 关键点
   - news_scraper 强依赖 watchlist 表已有数据 (active_flag=TRUE)，否则直接跳过 (见 scrape_headlines 中的空 watchlist 检查)
   - 所有 job 失败重试 3 次 (5min 间隔)，最终失败发邮件告警并记录 job_runs
   - dashboard 只读 Postgres，不直接调用外部 API


## Technology involved

- **PostgreSQL** — persistent storage for prices, watchlist metadata, events, and news (hosted on a free-tier provider such as Supabase or Neon so both GitHub Actions ETL and Streamlit Cloud can reach it)
- **yfinance (Yahoo Finance)** — market data source for prices/indices
- **Streamlit** — visualization/dashboard front-end, deployed on **Streamlit Community Cloud** (free tier)
- **Python** — ETL/orchestration glue; scraper for feeds in `news_feed.json`, following the pattern proven in `news_monitor.py`:
  - `urllib`/`requests` with a browser-like `User-Agent` (`use_headers` flag) for sources that block default clients (WSJ, American Banker, etc.)
  - Google News sitemap XML parsing via **BeautifulSoup** (`<news:title>`, `<news:publication_date>`, `<loc>`), filtered by a lookback cutoff
  - Sitemap-index sources (`nested: True`, e.g. Reuters/BBC/American Banker) resolved by first extracting child sitemap URLs, then parsing each
  - **feedparser** as fallback for plain RSS/Atom feeds (MarketWatch, Yahoo, Substack) when sitemap parsing yields nothing
  - Per-source try/except so one broken feed doesn't kill the whole run (log + skip, don't crash)
  - gzip auto-decompression for `.gz` sitemap URLs (e.g. NYT)
- **NASDAQ earnings calendar API** (`api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`) — free, no key required; queried once per day for the next 7 days to build **Prospective Events** (resolves the earlier "no calendar API chosen" gap). Rows are tagged `watchlist=True/False` and can be sorted/filtered by market cap or watchlist membership.
- **GitHub Actions (scheduled workflow)** — since Streamlit Cloud can't run background cron jobs, ETL (prices + news scraping + earnings calendar) runs as a scheduled GitHub Actions job that writes to the hosted Postgres; retry logic (5 min, 5 min, then email alert) implemented in the workflow/script
- **SMTP / email service** (Gmail SMTP, as used in `news_monitor.py` via `smtplib.SMTP_SSL`) — failure alerting after 2 failed retries, and optionally reused for the daily digest email itself
- **LLM API (optional, for summary step)** — Claude/OpenAI/Ollama-swappable pattern from `news_monitor.py` (`_call_claude` / `_call_openai` / `_call_ollama`), used to turn matched headlines into the executive-summary tiles and a BULLISH/BEARISH/MIXED/NEUTRAL-style verdict; can start rule-based (headline + first paragraph) and upgrade later. Ollama option keeps this free if API cost is a concern.

---

## Open Questions / Gaps to Resolve First

Decisions settled:

1. **News & events sourcing**: Use custom crawlers/scrapers against the RSS/news-sitemap feeds defined in `news_feed.json` (Reuters, WSJ, NYT, FT, CNN, Axios, MarketWatch, Seeking Alpha, Yahoo Finance, IBD, Forbes, TechCrunch, Fortune, Business Insider, fintech/banking blogs, Guardian, BBC, SMH/AFR, Fox, USA Today). No third-party news API — the scraper (modeled directly on the working reference implementation in `news_monitor.py`) pulls each feed, filters for AI-industry relevance via alias/keyword matching against the watchlist, and stores results (headline, url, published_date, source) into `news_raw`; an LLM/rule-based step then produces the executive summary for `news_summary`. Since sitemap feeds only give headline+link (not full article body most times), the summarizer step should fetch the article page and extract text before summarizing — or, as a cheaper first pass, feed the LLM just the matched headline batch per company (as `news_monitor.py` does) rather than full article text.
   - **Prospective events — solved**: use the free **NASDAQ earnings calendar API** (`api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`, no key required), queried once per day for the next 7 calendar days. This directly replaces the earlier "derive from news mentions" fallback. Tag each row `watchlist=True/False` and sort watchlist-first, then by market cap, matching the pattern in `fetch_earnings_calendar()`.

2. **Watchlist / AI Exposure definition**: GICS sub-industry is only a coarse first filter, not the final AI classification. Use a two-step model:
   - **Step 1 (GICS pre-filter)** — pull candidate universe from GICS sub-industries:
     | AI Segment | Example companies/industry | GICS pre-filter |
     |---|---|---|
     | AI Compute & Semiconductors | GPU, CPU, ASIC, HBM, semi equipment | Semiconductors & Semiconductor Equipment |
     | AI Infrastructure | Cloud, data center, networking, power | IT Services / Communications Equipment / Electrical Equipment |
     | AI Software & Platforms | AI models, enterprise AI, AI applications | Software / IT Services |
   - **Step 2 (AI Exposure Level)** — every company in the watchlist (GICS-filtered + manually added) is tagged with an exposure level, stored in `watchlist.ai_exposure_level`:
     - `Core` — AI is the primary business driver (e.g., GPU makers, foundation-model companies)
     - `Significant` — AI is a major, disclosed growth segment but not the whole business
     - `Adjacent` — meaningful AI exposure/narrative but secondary to core business
     - `None` — included only for benchmarking; not really AI-driven (rarely used, mostly a placeholder for completeness)
   - This tagging is **manual/curated** initially (a config table `watchlist_ai_exposure` you maintain), with room to later semi-automate via keyword/segment-revenue heuristics from the scraped news.

3. **Timezone/refresh reliability**: On ETL job failure at the 18:00 Toronto run:
   - Retry after 5 minutes
   - If still failing, retry after another 5 minutes
   - If still failing after the 2nd retry, send an email alert (job name, error message, timestamp) and mark the run as `failed` in `job_runs`
   - Dashboard shows the last successful "data as of" timestamp regardless, so stale-but-valid data is never silently confused with fresh data

4. **Hosting**: **Streamlit Community Cloud** (free tier), since the goal is to eventually share the dashboard with others at no cost. Implication: Streamlit Cloud only hosts the app itself — the scheduled ETL (scraping + DB writes) needs to run elsewhere (e.g., GitHub Actions on a cron schedule, or a free-tier always-on Postgres like Supabase/Neon + a GitHub Actions job pushing data). Streamlit app will connect to that hosted Postgres as a read-only client.

---

## Proposed Architecture

```
┌─────────────┐      ┌──────────────┐      ┌────────────┐      ┌───────────────┐
│ Yahoo Finance│─────▶│  ETL Jobs    │─────▶│ PostgreSQL │◀────▶│ Streamlit App │
│ News/Events  │      │ (Python,     │      │ (prices,   │      │ (reads only,  │
│ APIs         │      │  scheduled   │      │  watchlist,│      │  no live pull)│
└─────────────┘      │  18:00 EST/  │      │  events,   │      └───────────────┘
                      │  Toronto)    │      │  news)     │
                      └──────────────┘      └────────────┘
```

Key principle: the Streamlit app should **only read from Postgres**, never call external APIs directly. This keeps the dashboard fast, avoids rate-limit issues on page refresh, and makes the "data as of" timestamp trustworthy.

---

## Data Pipeline (ETL) Design

Runs as a **GitHub Actions scheduled workflow** (cron trigger ≈18:00 America/Toronto, converted to UTC and adjusted for DST) since Streamlit Community Cloud cannot run background jobs itself. The workflow writes to the shared hosted Postgres instance; Streamlit only reads from it.

1. **Price/Index Job**
   - Pull daily OHLCV for watchlist tickers + 4 indices via `yfinance`
   - Upsert into `prices` table; compute daily % change, treemap sizing metric (e.g., market cap or volume)
2. **Watchlist Resolution Job**
   - Rebuild the active watchlist from GICS sub-industry pre-filter (Semiconductors / IT Services / Software / Communications & Electrical Equipment) + manual overrides
   - Apply/refresh `ai_segment` and `ai_exposure_level` (Core / Significant / Adjacent / None) from the curated `watchlist_ai_exposure` config
   - Refresh each ticker's `aliases` list (company name variants, product names, exec names — as seen in `news_monitor.py`'s `WATCHLIST`) used for headline matching
   - Flag newly added/removed names for auditability
3. **News Scraping Job** (ports the logic in `news_monitor.py`'s `scrape_headlines`)
   - Iterate feeds defined in `news_feed.json`, per source config (`url`, `use_headers`, `nested`, `xml_prefix`)
   - For `nested` sources: fetch the sitemap index first, extract child sitemap URLs (cap at ~10), then parse each child
   - Parse each feed via `_parse_news_sitemap` (BeautifulSoup, Google News sitemap schema) first; fall back to `feedparser` for plain RSS/Atom if sitemap parsing returns nothing
   - Apply a lookback-day cutoff (e.g., 1–3 days) to drop stale entries
   - Match headlines against watchlist `aliases` (case-insensitive substring match) → filters for AI-industry relevance → store into `news_raw`
   - Wrap each source fetch in try/except so one broken feed (paywall change, schema change, timeout) doesn't abort the whole job — log and continue
   - Generate a short executive summary per company (LLM call on the matched-headline batch, or full article text if fetched) into `news_summary`
4. **Prospective Events Job**
   - Call the NASDAQ earnings calendar API once per day for the next 7 calendar days, tag `watchlist=True/False`, upsert into `prospective_events`
5. **Retrospective Summary Job**
   - Select prior day's `news_summary` rows for the "yesterday" tile list

**Failure handling (applies to every job above):**
- On failure: wait 5 minutes, retry once
- If still failing: wait another 5 minutes, retry once more
- If still failing after the 2nd retry: send an email alert (job name, error, timestamp) via SMTP, and log the run as `failed` in `job_runs` with `attempt_number`
- The dashboard always shows the last **successful** run's timestamp, so a failed refresh never silently masquerades as fresh data

---

## Proposed Database Schema (draft)

- `watchlist` (ticker, name, aliases [text array — company/product/exec name variants for headline matching], gics_sub_industry, ai_segment, ai_exposure_level, is_manual_override, added_date, active_flag)
- `indices` (index_code, name)
- `prices` (ticker_or_index, trade_date, open, high, low, close, volume, pct_change)
- `news_raw` (article_id, source_code, headline, article_url, published_date, fetched_at, matched_tickers, ai_relevance_flag)
- `prospective_events` (event_id, event_date, ticker, entity_name, event_type [e.g. "earnings"], eps_forecast, market_cap, is_watchlist, source, description, source_url) — populated primarily from the NASDAQ earnings calendar API
- `news_summary` (news_id, article_id [FK → news_raw], ticker_or_entity, summary, source_url, fetched_at)
- `job_runs` (job_name, run_ts, status, attempt_number, rows_affected, error_message)

---

## Structure (dashboard layout)

The dashboard mainly contains four parts:
1. **Index Trend** — line/candlestick charts for Dow Jones, Nasdaq 100, S&P 500, PHLX Semiconductor Index, with % change vs prior close
2. **Watchlist Treemap** — sized by market cap/volume, colored by daily % change
3. **Prospective Events** — horizontal timeline, next 7 calendar days, hover/click for detail + source link
4. **Retrospective News & Events Summary** — horizontal list of executive-summary tiles, each hyperlinked to source

Additional UX suggestions:
- A persistent header showing **"Data as of: <timestamp>, Toronto time"** and a status icon if the last ETL run failed
- Sidebar filter to toggle GICS-only vs GICS+manual watchlist view
- Manual "Add ticker" form (writes to `watchlist_overrides`, picked up on next ETL run)

---

## Suggested Build Phases

- **Phase 0 — Setup**: hosted Postgres (Supabase/Neon free tier), repo structure, config for watchlist/GICS pre-filter + AI exposure levels
- **Phase 1 — Prices & Indices**: yfinance ETL + Streamlit price/treemap views (core value, no news dependency)
- **Phase 2 — Watchlist management**: GICS pre-filter + `ai_segment`/`ai_exposure_level` curation UI + manual override
- **Phase 3 — News scraping & summaries**: adapt the proven scraping/matching/summarization logic from `news_monitor.py` — sitemap+RSS scraper for `news_feed.json` sources, alias-based AI-relevance filter, LLM summary generation (Claude/OpenAI/Ollama-swappable) — plus NASDAQ earnings calendar integration for prospective events (this phase is now de-risked since a working reference implementation exists)
- **Phase 4 — Scheduling & reliability**: GitHub Actions cron workflow at 18:00 Toronto, 5-min/5-min retry logic, email alert on final failure, `job_runs` logging
- **Phase 5 — Deployment & polish**: deploy to Streamlit Community Cloud (free tier), caching, styling, "data as of" banner, documentation for sharing with others

---

## Testing & Reliability Notes

- Use `pytest` for ETL transform logic (percent-change calc, GICS filtering, summary formatting)
- Mock external API responses in tests to avoid live-network flakiness
- Handle market holidays / weekends gracefully (no new price row expected — don't flag as failure)
- Rate-limit-aware retry/backoff for Yahoo Finance and news APIs




## News data model:

WATCHLIST
    │
    ↓
news_scraper
    │
    ↓
┌─────────────────────────────────┐
│ news_raw                         │
│                                 │
│ article_id PK                   │
│ source_code                     │
│ headline                        │
│ article_url UNIQUE              │
│ published_date                  │
│ matched_tickers[]               │
│ ai_relevance_flag               │
└───────────────┬─────────────────┘
                │
                │ many articles
                ↓
      DeepSeek classification
                │
                ↓
┌─────────────────────────────────┐
│ news_summary                    │
│                                 │
│ summary_id PK                   │
│ ticker_or_entity                │
│ summary_date                    │
│ article_count                   │
│ sentiment                       │
│ summary                         │
│ key_points[]                    │
│ source_urls[]                   │
│ generated_at                    │
│ UNIQUE(ticker, date)            │
└───────────────┬─────────────────┘
                │
                │
                ↓
      news_summary_articles
                │
                ↓
             news_raw

             

## Earnings data:
                    Yahoo Finance
                         │
          ┌──────────────┴──────────────┐
          ↓                             ↓
   Future earnings                 Historical earnings
          │                             │
          ↓                             ↓
prospective_events              earnings_history
          │
          │ earnings date passes
          ↓
   snapshot estimate
          │
          └──────────────────────────→ earnings_history


                 YFinance
                    │
        ┌───────────┴────────────┐
        │                        │
 upcoming data             historical data
        │                        │
        ↓                        ↓
prospective_events       earnings_history
        │                        ↑
        │                        │
        └────── snapshot ────────┘

prospective_events 是当前未来事件的“动态状态”；earnings_history 是发生过的 earnings 的“历史快照”。







                    ┌──────────────────┐
                    │  GitHub Actions  │
                    │  Daily 4:30 PM   │
                    └────────┬─────────┘
                             │
                             ▼
                       run_all.py
                             │
             ┌───────────────┼────────────────┐
             ▼               ▼                ▼
          Prices          Earnings           News
             │               │                │
             ▼               ▼                ▼
       company_metadata  prospective_events  news_raw
                         earnings_history     news_articles
                                             news_analysis
                                             news_daily_summary
             │               │                │
             └───────────────┼────────────────┘
                             ▼
                         PostgreSQL
                             │
                             ▼
                     Streamlit Dashboard
                             │
                             ▼
                       Public / Private URL