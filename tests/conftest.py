"""Shared pytest fixtures. Mock external API responses here to avoid live-network flakiness."""
import pytest


@pytest.fixture
def sample_headlines():
    return [
        {"headline": "NVIDIA unveils new GPU", "url": "https://example.com/1", "published_date": "2026-08-30"},
        {"headline": "Unrelated retail news", "url": "https://example.com/2", "published_date": "2026-08-30"},
    ]
