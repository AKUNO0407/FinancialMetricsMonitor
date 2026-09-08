from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from openai import OpenAI
from sqlalchemy import text

from etl.db import get_engine
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)


MODEL = os.environ.get(
    "DEEPSEEK_MODEL",
    "deepseek-v4-flash",
)

API_KEY = os.environ.get(
    "DEEPSEEK_API_KEY"
)

LOOKBACK_DAYS = int(
    os.environ.get(
        "SUMMARY_LOOKBACK_DAYS",
        "1",
    )
)

MAX_ARTICLES_PER_COMPANY = int(
    os.environ.get(
        "MAX_ARTICLES_PER_COMPANY",
        "20",
    )
)

PROMPT_VERSION = "2.0-full-content"


if not API_KEY:
    raise RuntimeError(
        "DEEPSEEK_API_KEY is not configured"
    )


client = OpenAI(
    api_key=API_KEY,
    base_url="https://api.deepseek.com",
)

def _get_reporting_window():
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS - 1)

    return start_date, end_date

# ============================================================
# Prompt: article-level analysis
# ============================================================

def _build_article_prompt(
    ticker: str,
    company_name: str,
    article: dict,
) -> str:
    article_text = article.get(
        "article_text"
    )
    input_mode = (
        "FULL_CONTENT"
        if article_text
        else "HEADLINE"
    )
    content = (
        article_text
        if article_text
        else article["headline"]
    )

    return f"""
You are a financial news analyst covering AI infrastructure,
semiconductors, cloud computing, data centers, networking,
power infrastructure, and enterprise AI.

Analyze the following news article in relation to:

Company: {company_name}
Ticker: {ticker}

INPUT MODE:
{input_mode}

EVIDENCE POLICY

Use ONLY the information contained in the supplied article.

Do NOT use:
- pretrained knowledge
- external web searches
- information from other articles
- assumptions about facts not stated in the article

Do NOT invent:
- financial results
- customers
- partnerships
- product specifications
- market share
- revenue impact
- causal relationships
- management intentions

If the evidence is insufficient, use NEUTRAL
rather than guessing.

TASK

1. Determine whether this article contains meaningful
   information about the company.
2. Classify the relevance.
3. Assess materiality.
4. Determine the directional sentiment for the company.
5. Summarize the most important information for an investor
   or risk analyst.

RELEVANCE TYPES

COMPANY_SPECIFIC:
Material information directly concerning the company.

INDUSTRY:
Relevant to the company's industry or competitive environment,
but not primarily about the company.

MARKET_CONTEXT:
Broader macroeconomic, regulatory, market, or sector context.

IRRELEVANT:
The company is mentioned incidentally or the article provides
no meaningful information about the company.

MATERIALITY

HIGH:
Potentially significant strategic, operational, financial,
regulatory, product, customer, M&A, earnings, or competitive
development.

MEDIUM:
Meaningful development with a more limited potential impact.

LOW:
Minor, repetitive, generic, or low-information development.

SENTIMENT

BULLISH:
Predominantly positive for the company's business,
competitive position, strategic position, or outlook.

BEARISH:
Predominantly negative.

MIXED:
Material positive and negative developments coexist.

NEUTRAL:
Factual, ambiguous, generic, low-materiality, or insufficient
for a directional conclusion.

IMPORTANT:

Sentiment refers to the company, NOT the overall market.

Do not treat a positive development for the broader AI industry
as automatically positive for the company.

If the article describes a stock-price movement, distinguish
the stock-price reaction from the underlying fundamental
implication for the company.

OUTPUT

Return valid JSON with EXACTLY these fields:

{{
  "relevant": true,
  "relevance_type": "COMPANY_SPECIFIC",
  "materiality": "HIGH",
  "sentiment": "BULLISH",
  "summary": "2-4 concise sentences.",
  "key_points": [
    "Key development 1",
    "Key development 2",
    "Key development 3"
  ]
}}

OUTPUT RULES

- If relevance_type is IRRELEVANT:
  relevant = false
  materiality = LOW
  sentiment = NEUTRAL

- key_points should contain 2-4 items when meaningful
  information exists.

- Do not repeat the same development.

- Do not use promotional or sensational language.

- Do not infer unsupported facts.

- Keep the summary concise and executive-friendly.

ARTICLE

Headline:
{article["headline"]}

Published:
{article["published_date"]}

Source:
{article["source_code"]}

Article content:
{content}
""".strip()


# ============================================================
# DeepSeek call
# ============================================================

def _call_deepseek(
    prompt: str,
) -> tuple[dict, int | None, int | None]:

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise financial "
                    "news analysis engine."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={
            "type": "json_object"
        },
        temperature=0,
    )

    content = response.choices[0].message.content
    result = json.loads(content)
    usage = response.usage

    input_tokens = (
        usage.prompt_tokens
        if usage
        else None
    )
    output_tokens = (
        usage.completion_tokens
        if usage
        else None
    )
    return (
        result,
        input_tokens,
        output_tokens,
    )


# ============================================================
# Load recent articles
# ============================================================

def _load_recent_articles() -> list[dict]:

    start_date, end_date = _get_reporting_window()
    #cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS))

    engine = get_engine()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    nr.article_id,
                    nr.headline,
                    nr.article_url,
                    nr.published_date,
                    nr.source_code,
                    nr.matched_tickers,

                    na.title,
                    na.author,
                    na.article_text,
                    na.fetch_status

                FROM news_raw nr

                LEFT JOIN news_articles na
                    ON nr.article_id =
                       na.article_id

                WHERE nr.published_date >= :start_date
                  AND nr.published_date < :end_date + INTERVAL '1 day'

                  AND nr.matched_tickers IS NOT NULL

                  AND cardinality(
                      nr.matched_tickers
                  ) > 0

                ORDER BY
                    nr.published_date DESC
                """
            ),
            {#"cutoff": cutoff,
             "start_date": start_date,
             "end_date": end_date},
        ).mappings().all()

    return [dict(row) for row in rows]


# ============================================================
# Load watchlist
# ============================================================

def _load_watchlist() -> dict[str, dict]:

    engine = get_engine()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    ticker,
                    name
                FROM watchlist
                WHERE active_flag = TRUE
                """
            )
        ).mappings().all()
    return {
        row["ticker"]: dict(row)
        for row in rows
    }


# ============================================================
# Group articles by ticker
# ============================================================

def _group_articles(
    articles: list[dict],
    watchlist: dict[str, dict],
) -> dict[str, list[dict]]:

    grouped = defaultdict(list)

    for article in articles:
        for ticker in (
            article["matched_tickers"] or []
        ):
            if ticker not in watchlist:
                continue
            grouped[ticker].append(
                article
            )

    for ticker in grouped:
        grouped[ticker] = (
            grouped[ticker]
            [:MAX_ARTICLES_PER_COMPANY]
        )

    return dict(grouped)


# ============================================================
# Store article-level analysis
# ============================================================

def _store_article_analysis(
    article: dict,
    ticker: str,
    result: dict,
    input_tokens: int | None,
    output_tokens: int | None,
):

    engine = get_engine()

    input_mode = (
        "FULL_CONTENT"
        if article.get("article_text")
        else "HEADLINE"
    )
    news_date = (
        article["published_date"].date()
        if article.get("published_date")
        else None
    )

    with engine.begin() as conn:

        conn.execute(
            text(
                """
                INSERT INTO news_analysis (
                    article_id,
                    ticker_or_entity,
                    news_date,
                    relevant,
                    relevance_type,
                    materiality,
                    sentiment,
                    summary,
                    key_points,
                    analysis_date,
                    model_name,
                    prompt_version,
                    input_mode,
                    input_tokens,
                    output_tokens
                )
                VALUES (
                    :article_id,
                    :ticker,
                    :news_date,
                    :relevant,
                    :relevance_type,
                    :materiality,
                    :sentiment,
                    :summary,
                    CAST(:key_points AS JSONB),
                    CURRENT_DATE,
                    :model_name,
                    :prompt_version,
                    :input_mode,
                    :input_tokens,
                    :output_tokens
                )
                ON CONFLICT (
                    article_id,
                    ticker_or_entity
                )
                DO UPDATE SET
                    news_date =
                        EXCLUDED.news_date,
                    relevant =
                        EXCLUDED.relevant,
                    relevance_type =
                        EXCLUDED.relevance_type,
                    materiality =
                        EXCLUDED.materiality,
                    sentiment =
                        EXCLUDED.sentiment,
                    summary =
                        EXCLUDED.summary,
                    key_points =
                        EXCLUDED.key_points,
                    analysis_date =
                        EXCLUDED.analysis_date,
                    model_name =
                        EXCLUDED.model_name,
                    prompt_version =
                        EXCLUDED.prompt_version,
                    input_mode =
                        EXCLUDED.input_mode,
                    input_tokens =
                        EXCLUDED.input_tokens,
                    output_tokens =
                        EXCLUDED.output_tokens
                """
            ),
            {
                "article_id":
                    article["article_id"],

                "ticker":
                    ticker,
                "news_date":
                    news_date,

                "relevant":
                    bool(
                        result.get(
                            "relevant",
                            False,
                        )
                    ),

                "relevance_type":
                    result.get(
                        "relevance_type",
                        "IRRELEVANT",
                    ),

                "materiality":
                    result.get(
                        "materiality",
                        "LOW",
                    ),

                "sentiment":
                    result.get(
                        "sentiment",
                        "NEUTRAL",
                    ),

                "summary":
                    result.get(
                        "summary",
                        "",
                    ),

                "key_points":
                    json.dumps(
                        result.get(
                            "key_points",
                            [],
                        )
                    ),

                "model_name": MODEL,

                "prompt_version":
                    PROMPT_VERSION,

                "input_mode":
                    input_mode,

                "input_tokens":
                    input_tokens,

                "output_tokens":
                    output_tokens,
            },
        )

        conn.execute(
            text(
                """
                UPDATE news_raw
                SET ai_relevance_flag = :relevant
                WHERE article_id = :article_id
                """
            ),
            {
                "relevant":
                    bool(
                        result.get(
                            "relevant",
                            False,
                        )
                    ),
                "article_id":
                    article["article_id"],
            },
        )


# ============================================================
# Build daily summary
# ============================================================

def _build_daily_summary_prompt(
    ticker: str,
    company_name: str,
    analyses: list[dict],
) -> str:

    analysis_block = json.dumps(
        analyses,
        ensure_ascii=False,
        indent=2,
    )

    return f"""
You are a financial news analyst.

Prepare a daily news summary for:

Company: {company_name}
Ticker: {ticker}

The following are article-level analyses generated from
news observed during the current observation window.

Use ONLY the supplied analyses.

Do NOT introduce information from your pretrained knowledge,
external web searches, or other sources.

Your task is to identify the most important developments and
produce an executive-friendly daily summary.

Consider:

- number of material developments
- HIGH materiality developments
- consistency of sentiment
- contradictory positive and negative developments
- company-specific developments versus generic industry news

Do not allow a large number of low-quality articles to outweigh
a small number of highly material developments.

SENTIMENT

BULLISH:
Overall evidence is predominantly positive.

BEARISH:
Overall evidence is predominantly negative.

MIXED:
Material positive and negative developments coexist.

NEUTRAL:
No clear directional conclusion is supported.

OUTPUT

Return valid JSON with EXACTLY:

{{
  "overall_sentiment": "BULLISH",
  "summary": "3-5 concise sentences.",
  "key_points": [
    "Most important development",
    "Second important development",
    "Third important development"
  ]
}}

Rules:

- Prioritize HIGH materiality.
- Deduplicate overlapping reports of the same event.
- Do not exaggerate.
- Do not introduce unsupported information.
- If there is insufficient evidence for a directional view,
  use NEUTRAL.

ARTICLE-LEVEL ANALYSES

{analysis_block}
""".strip()


# ============================================================
# Store daily summary
# ============================================================

def _store_daily_summary(
    ticker: str,
    result: dict,
    analyses: list[dict],
    input_tokens: int | None,
    output_tokens: int | None,
):
    start_date, end_date = _get_reporting_window()
    period_start_date = start_date
    period_end_date = end_date

    sentiment_counts = {
        "BULLISH": 0,
        "BEARISH": 0,
        "MIXED": 0,
        "NEUTRAL": 0,
    }

    high_materiality_count = 0

    source_urls = []
    source_articles  = []

    for analysis in analyses:

        sentiment = analysis.get(
            "sentiment"
        )

        if sentiment in sentiment_counts:
            sentiment_counts[
                sentiment
            ] += 1

        if (
            analysis.get("materiality")
            == "HIGH"
        ):
            high_materiality_count += 1

        if analysis.get("article_url"):
            source_urls.append(
                analysis["article_url"]
            )
        source_articles.append(
            {
                "article_id": analysis["article_id"],
                "title": analysis["headline"],
                "published_date": analysis["news_date"],
                "url": analysis["article_url"],
            }
        )

    source_urls = list(
        dict.fromkeys(source_urls)
    )

    engine = get_engine()

    with engine.begin() as conn:

        conn.execute(
            text(
                """
                INSERT INTO news_daily_summary (
                    ticker_or_entity,
                    summary_date,
                    period_start_date,
                    period_end_date,
                    article_count,
                    high_materiality_count,
                    bullish_count,
                    bearish_count,
                    mixed_count,
                    neutral_count,
                    overall_sentiment,
                    summary,
                    key_points,
                    source_articles,
                    source_urls,
                    model_name,
                    prompt_version,
                    input_tokens,
                    output_tokens
                )
                VALUES (
                    :ticker,
                    :summary_date,
                    :period_start_date,
                    :period_end_date,
                    :article_count,
                    :high_materiality_count,
                    :bullish_count,
                    :bearish_count,
                    :mixed_count,
                    :neutral_count,
                    :overall_sentiment,
                    :summary,
                    CAST(:key_points AS JSONB),
                    CAST(:source_articles AS JSONB),
                    :source_urls,
                    :model_name,
                    :prompt_version,
                    :input_tokens,
                    :output_tokens
                )
                ON CONFLICT (
                    ticker_or_entity,
                    summary_date
                )
                DO UPDATE SET
                    period_start_date =
                        EXCLUDED.period_start_date,
                    period_end_date =
                        EXCLUDED.period_end_date,
                    article_count =
                        EXCLUDED.article_count,
                    high_materiality_count =
                        EXCLUDED.high_materiality_count,
                    bullish_count =
                        EXCLUDED.bullish_count,
                    bearish_count =
                        EXCLUDED.bearish_count,
                    mixed_count =
                        EXCLUDED.mixed_count,
                    neutral_count =
                        EXCLUDED.neutral_count,
                    overall_sentiment =
                        EXCLUDED.overall_sentiment,
                    summary =
                        EXCLUDED.summary,
                    key_points =
                        EXCLUDED.key_points,
                    source_urls =
                        EXCLUDED.source_urls,
                    source_articles =
                        EXCLUDED.source_articles,
                    model_name =
                        EXCLUDED.model_name,
                    prompt_version =
                        EXCLUDED.prompt_version,
                    input_tokens =
                        EXCLUDED.input_tokens,
                    output_tokens =
                        EXCLUDED.output_tokens
                """
            ),
            {
                "ticker":
                    ticker,

                "summary_date":
                    end_date,
                "period_start_date":
                    period_start_date,
                "period_end_date":
                    period_end_date,
                "article_count":
                    len(analyses),

                "high_materiality_count":
                    high_materiality_count,

                "bullish_count":
                    sentiment_counts[
                        "BULLISH"
                    ],

                "bearish_count":
                    sentiment_counts[
                        "BEARISH"
                    ],

                "mixed_count":
                    sentiment_counts[
                        "MIXED"
                    ],

                "neutral_count":
                    sentiment_counts[
                        "NEUTRAL"
                    ],

                "overall_sentiment":
                    result.get(
                        "overall_sentiment",
                        "NEUTRAL",
                    ),

                "summary":
                    result.get(
                        "summary",
                        "",
                    ),

                "key_points":
                    json.dumps(
                        result.get(
                            "key_points",
                            [],
                        )
                    ),

                "source_articles":
                    json.dumps(source_articles),
                "source_urls":
                    source_urls,

                "model_name":
                    MODEL,

                "prompt_version":
                    PROMPT_VERSION,

                "input_tokens":
                    input_tokens,

                "output_tokens":
                    output_tokens,
            },
        )


# ============================================================
# Main
# ============================================================

def main():

    logger.info(
        "Starting news AI analysis"
    )

    watchlist = _load_watchlist()

    articles = _load_recent_articles()

    logger.info(
        "Loaded %s recent articles",
        len(articles),
    )

    grouped = _group_articles(
        articles,
        watchlist,
    )

    article_analysis_count = 0

    for ticker, ticker_articles in (
        grouped.items()
    ):

        company_name = watchlist[
            ticker
        ]["name"]

        logger.info(
            "Processing %s (%s) - %s articles",
            ticker,
            company_name,
            len(ticker_articles),
        )

        analyses_for_company = []

        for article in ticker_articles:

            try:

                prompt = _build_article_prompt(
                    ticker=ticker,
                    company_name=company_name,
                    article=article,
                )

                (
                    result,
                    input_tokens,
                    output_tokens,
                ) = _call_deepseek(prompt)

                _store_article_analysis(
                    article=article,
                    ticker=ticker,
                    result=result,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

                analyses_for_company.append(
                    {
                        "article_id": article["article_id"],
                        "ticker_or_entity": ticker,
                        "news_date": (
                            article["published_date"].date().isoformat()
                            if article["published_date"]
                            else None
                        ),
                        "headline": article["headline"],
                        "article_url": article["article_url"],
                        "relevant": result.get("relevant", False),
                        "relevance_type": result.get("relevance_type", "IRRELEVANT"),
                        "materiality": result.get("materiality", "LOW"),
                        "sentiment": result.get("sentiment", "NEUTRAL"),
                        "summary": result.get("summary", ""),
                        "key_points": result.get("key_points", []),
                    }
                )

                article_analysis_count += 1

            except Exception:
                logger.exception(
                    "AI analysis failed for "
                    "article_id=%s ticker=%s",
                    article["article_id"],
                    ticker,
                )

        relevant_analyses = [
            item
            for item in analyses_for_company
            if item["relevant"]
        ]

        if not relevant_analyses:
            logger.info(
                "No relevant news for %s",
                ticker,
            )
            continue

        try:

            prompt = (
                _build_daily_summary_prompt(
                    ticker=ticker,
                    company_name=company_name,
                    analyses=relevant_analyses,
                )
            )
            (
                result,
                input_tokens,
                output_tokens,
            ) = _call_deepseek(prompt)

            _store_daily_summary(
                ticker=ticker,
                result=result,
                analyses=relevant_analyses,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        except Exception:
            logger.exception(
                "Daily summary failed for %s",
                ticker,
            )

    logger.info(
        "News AI analysis completed. "
        "Article analyses=%s",
        article_analysis_count,
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(message)s"
        ),
    )

    main()