from pathlib import Path

from etl import watchlist_manual


def test_build_rows_from_manual_yaml(tmp_path: Path):
    yaml_text = """
companies:
  - ticker: nvda
    name: NVIDIA Corporation
    ai_segment: AI Compute & Semiconductors
    ai_exposure_level: Core
    gics_sub_industry: Semiconductors
  - ticker: PRIV:OpenAI
    name: OpenAI
    ai_segment: AI Software & Platforms
    ai_exposure_level: Core
    aliases: [ChatGPT]
"""
    cfg = tmp_path / "manual.yaml"
    cfg.write_text(yaml_text, encoding="utf-8")

    rows = watchlist_manual._build_rows(config_path=cfg)
    by_ticker = {r["ticker"]: r for r in rows}

    assert "NVDA" in by_ticker
    assert by_ticker["NVDA"]["is_public"] is True
    assert by_ticker["NVDA"]["if_retrieve_price"] is True
    assert by_ticker["NVDA"]["ai_relevance_tag"] == "manual_curated"

    assert "PRIV:OPENAI" in by_ticker
    assert by_ticker["PRIV:OPENAI"]["is_public"] is False
    assert by_ticker["PRIV:OPENAI"]["if_retrieve_price"] is False
    assert "ChatGPT" in by_ticker["PRIV:OPENAI"]["aliases"]
