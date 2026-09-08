"""Tests for watchlist resolution in etl/watchlist.py."""

from etl import watchlist


def test_build_rows_full_refresh_outputs_portfolio_with_public_private_flags(monkeypatch):
    """Portfolio rows should include public + private entities with explicit flags."""
    cfg = {
        "yahoo_industries": ["Semiconductors"],
        "screener_region": "us",
        "screener_min_market_cap": 0,
        "manual_overrides": [
            {
                "ticker": "NVDA",
                "aliases": ["NVIDIA", "Jensen Huang"],
                "ai_segment": "AI Compute & Semiconductors",
                "ai_exposure_level": "Core",
            }
        ],
        "private_companies": [
            {
                "name": "OpenAI",
                "aliases": ["OpenAI", "ChatGPT"],
                "ai_segment": "AI Software & Platforms",
                "ai_exposure_level": "Core",
            }
        ],
    }

    def _fake_screen_industry(industry, region, min_mcap):
        assert industry == "Semiconductors"
        assert region == "us"
        assert min_mcap == 0
        return [
            {
                "ticker": "NVDA",
                "name": "NVIDIA Corporation",
                "aliases": ["NVIDIA Corporation", "NVDA"],
                "gics_sub_industry": industry,
                "is_public": True,
            },
            {
                "ticker": "AMD",
                "name": "Advanced Micro Devices, Inc.",
                "aliases": ["AMD", "Advanced Micro Devices, Inc."],
                "gics_sub_industry": industry,
                "is_public": True,
            },
        ]

    monkeypatch.setattr(watchlist, "_screen_industry", _fake_screen_industry)

    rows = watchlist._build_rows(cfg, full_refresh=True)
    by_ticker = {row["ticker"]: row for row in rows}

    # public rows from screener
    assert by_ticker["NVDA"]["is_public"] is True
    assert by_ticker["AMD"]["is_public"] is True

    # manual override should be merged into existing public ticker
    assert by_ticker["NVDA"]["is_manual_override"] is True
    assert by_ticker["NVDA"]["ai_exposure_level"] == "Core"
    assert "Jensen Huang" in by_ticker["NVDA"]["aliases"]

    # private company should be added with pseudo ticker and is_public=False
    private_ticker = "PRIV:OPENAI"
    assert private_ticker in by_ticker
    assert by_ticker[private_ticker]["name"] == "OpenAI"
    assert by_ticker[private_ticker]["is_public"] is False
    assert "ChatGPT" in by_ticker[private_ticker]["aliases"]


def test_build_rows_portfolio_can_be_split_by_public_flag(monkeypatch):
    """Output rows should support straightforward public/private portfolio filtering."""
    cfg = {
        "yahoo_industries": ["Software - Infrastructure"],
        "screener_region": "us",
        "screener_min_market_cap": 0,
        "manual_overrides": [],
        "private_companies": [{"name": "Anthropic", "aliases": ["Anthropic", "Claude"]}],
    }

    monkeypatch.setattr(
        watchlist,
        "_screen_industry",
        lambda *args, **kwargs: [
            {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "aliases": ["MSFT", "Microsoft"],
                "gics_sub_industry": "Software - Infrastructure",
                "is_public": True,
            }
        ],
    )

    rows = watchlist._build_rows(cfg, full_refresh=True)
    public_portfolio = [r for r in rows if r["is_public"]]
    private_portfolio = [r for r in rows if not r["is_public"]]

    assert [r["ticker"] for r in public_portfolio] == ["MSFT"]
    assert [r["ticker"] for r in private_portfolio] == ["PRIV:ANTHROPIC"]


def test_downstream_deep_clean_tags_without_excluding_companies(monkeypatch):
    cfg = {
        "yahoo_industries": ["Biotechnology", "Semiconductors"],
        "downstream_industries": ["Biotechnology"],
        "ai_keywords": ["artificial intelligence", "machine learning", "llm"],
        "summary_filter_top_n": 1,
        "screener_region": "us",
        "screener_min_market_cap": 0,
        "manual_overrides": [],
        "private_companies": [],
    }

    def _fake_screen(industry, *_args, **_kwargs):
        if industry == "Biotechnology":
            return [
                {
                    "ticker": "BIO1",
                    "name": "Bio One",
                    "aliases": ["BIO1", "Bio One"],
                    "gics_sub_industry": "Biotechnology",
                    "is_public": True,
                    "market_cap": 100,
                    "screen_rank": 1,
                },
                {
                    "ticker": "BIO2",
                    "name": "Bio Two",
                    "aliases": ["BIO2", "Bio Two"],
                    "gics_sub_industry": "Biotechnology",
                    "is_public": True,
                    "market_cap": 50,
                    "screen_rank": 2,
                },
            ]
        return [
            {
                "ticker": "NVDA",
                "name": "NVIDIA Corporation",
                "aliases": ["NVDA", "NVIDIA"],
                "gics_sub_industry": "Semiconductors",
                "is_public": True,
                "market_cap": 999,
                "screen_rank": 1,
            }
        ]

    monkeypatch.setattr(watchlist, "_screen_industry", _fake_screen)
    monkeypatch.setattr(
        watchlist,
        "_fetch_business_summary",
        lambda ticker: "we provide artificial intelligence tools" if ticker == "BIO1" else "",
    )

    rows = watchlist._build_rows(cfg, full_refresh=True)
    by_ticker = {row["ticker"]: row for row in rows}

    # downstream top-1 evaluated
    assert by_ticker["BIO1"]["ai_high_relevance"] is True
    assert by_ticker["BIO1"]["ai_relevance_tag"] == "downstream_keyword_match"

    # downstream beyond top-N kept but not evaluated
    assert by_ticker["BIO2"]["ai_high_relevance"] is None
    assert by_ticker["BIO2"]["ai_relevance_tag"] == "downstream_not_evaluated_rate_limit"

    # upstream/midstream included directly
    assert by_ticker["NVDA"]["ai_high_relevance"] is True
    assert by_ticker["NVDA"]["ai_relevance_tag"] == "upstream_midstream_in_scope"
