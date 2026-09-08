"""Tests for etl.news_scraper."""

from etl.news_scraper import _normalize_article_url, match_headlines


def test_normalize_article_url_strips_tracking_query_and_fragment():
    url = "https://Example.com/path/to/article/?utm_source=x&ref=abc&id=42#section"
    assert _normalize_article_url(url) == "https://example.com/path/to/article?id=42"


def test_match_headlines_matches_alias_case_insensitive(sample_headlines):
    watchlist = [
        {"ticker": "NVDA", "aliases": ["NVIDIA", "Jensen Huang"]},
        {"ticker": "MSFT", "aliases": ["Microsoft"]},
    ]

    matched = match_headlines(sample_headlines, watchlist)
    assert len(matched["NVDA"]) == 1
    assert matched["NVDA"][0]["headline"] == "NVIDIA unveils new GPU"
    assert matched["MSFT"] == []
