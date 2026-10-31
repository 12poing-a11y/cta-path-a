# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from regime_enable import enabled_sleeves, normalize_regime  # noqa: E402


def test_chop_disables_donchian_strong():
    ids = {r["sleeve"] for r in enabled_sleeves("chop_strong")}
    assert "sleeve_donchian" not in ids
    assert "sleeve_mr" in ids
    assert "sentiment_mds" in ids


def test_strong_trend_disables_mr():
    ids = {r["sleeve"] for r in enabled_sleeves("strong_trend")}
    assert "sleeve_mr" not in ids
    assert "sleeve_donchian" in ids
    assert "path_a" in ids


def test_label_map_zh():
    assert normalize_regime("震荡") == "chop"
    assert normalize_regime("偏多") == "trend"
