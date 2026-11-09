# -*- coding: utf-8 -*-
from desk.sentiment_panel import sentiment_score_from_p3, stance_to_direction


def test_sentiment_score_mapping():
    assert sentiment_score_from_p3(0.0) == 50.0
    assert sentiment_score_from_p3(1.0) == 100.0
    assert sentiment_score_from_p3(-1.0) == 0.0
    assert sentiment_score_from_p3(0.316) == 65.8


def test_stance_direction():
    assert stance_to_direction("risk_on") == "多"
    assert stance_to_direction("risk_off") == "空"
    assert stance_to_direction("neutral") == "震荡"


def test_sentiment_verdict_conviction():
    from desk.sentiment_panel import sentiment_verdict

    v = sentiment_verdict(
        {
            "stance": "risk_on",
            "portfolio_p3": 0.316,
            "longs": ["MA", "AU"],
            "shorts": ["CF"],
        }
    )
    assert v["direction"] == "多"
    assert 0 <= v["conviction_pct"] <= 100
    assert v["conviction_pct"] >= 45
