# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iv_breakout import (  # noqa: E402
    annotate_breakouts_with_iv,
    classify_breakout_iv,
    detect_breakouts,
    iv_decision_gate,
    summarize_validation,
)


def _bars_breakout_up() -> list[dict]:
    """20-day flat range then close breakout; hold above level."""
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    out: list[dict] = []
    for i in range(30):
        day = (start + timedelta(days=i)).isoformat()
        if i < 20:
            out.append({"date": day, "high": 101.0, "low": 99.0, "close": 100.0})
        elif i == 20:
            out.append({"date": day, "high": 106.0, "low": 100.0, "close": 105.0})
        else:
            out.append(
                {
                    "date": day,
                    "high": 107.0,
                    "low": 103.0,
                    "close": 104.0 + (i - 20) * 0.2,
                }
            )
    return out


def test_detect_up_breakout():
    bars = _bars_breakout_up()
    events = detect_breakouts(bars, window=20)
    assert events
    assert events[0]["side"] == 1
    assert events[0]["close"] == 105.0


def test_classify_iv_tags():
    assert classify_breakout_iv(iv_today=0.26, iv_prev=0.24, delta_iv_min=0.005)[
        "tag"
    ] == "true_candidate"
    assert classify_breakout_iv(iv_today=0.23, iv_prev=0.24, delta_iv_min=0.005)[
        "tag"
    ] == "false_suspect"
    assert classify_breakout_iv(iv_today=0.241, iv_prev=0.24, delta_iv_min=0.005)[
        "tag"
    ] == "iv_flat"
    assert classify_breakout_iv(iv_today=None, iv_prev=0.2)["tag"] == "iv_missing"


def test_annotate_and_summary():
    bars = _bars_breakout_up()
    # Rising IV into breakout day (2026-02-21 is index 20)
    iv = {}
    for i, row in enumerate(bars):
        ymd = str(row["date"]).replace("-", "")
        iv[ymd] = 0.20 + (0.02 if i >= 20 else 0.0)
    # prev day lower
    rows = annotate_breakouts_with_iv(
        bars, iv, window=20, delta_iv_min=0.005, hold_days=5
    )
    assert rows
    assert rows[0]["tag"] == "true_candidate"
    assert rows[0]["ok"] is True
    assert rows[0]["held"] is True
    summary = summarize_validation(rows)
    assert summary["iv_confirmed"]["n"] >= 1
    assert summary["iv_confirmed"]["hold_rate"] == 1.0


def test_gate_observe_on_suspect():
    g = iv_decision_gate("false_suspect", enabled=True, action="observe")
    assert g["force_observe"] is True
    g2 = iv_decision_gate("true_candidate", enabled=True, action="observe")
    assert g2["force_observe"] is False


def test_fetch_day_iv_soft_empty_skips_poison_missing(tmp_path, monkeypatch):
    import iv_breakout as iv

    class _Empty:
        empty = True
        columns = []

    class _Ak:
        @staticmethod
        def option_hist_czce(**_kwargs):
            return _Empty()

    monkeypatch.setitem(__import__("sys").modules, "akshare", _Ak())
    out = iv.fetch_day_iv(
        tmp_path, "CF", "20261112", use_cache=False, refresh=True, cache_missing=False
    )
    assert out is None
    path = tmp_path / ".cache" / "akshare" / "option_iv" / "CF" / "20261112.json"
    assert not path.exists()


def test_refresh_option_iv_backfills_and_keeps_asof_soft(tmp_path, monkeypatch):
    import iv_breakout as iv

    calls: list[str] = []

    def _fake_fetch(root, code, trade_date, *, use_cache=True, refresh=False, cache_missing=True):
        ymd = str(trade_date).replace("-", "")[:8]
        calls.append(f"{code}:{ymd}:{cache_missing}")
        if ymd >= "20261112":
            return None  # asof not published yet
        path = iv._cache_dir(root) / code / f"{ymd}.json"
        payload = {
            "code": code,
            "date": ymd,
            "product": "棉花期权",
            "venue": "czce",
            "iv": 0.15,
            "series": "czce_vw",
            "volume": 1.0,
            "source": "czce",
        }
        iv._write_json(path, payload)
        return payload

    monkeypatch.setattr(iv, "fetch_day_iv", _fake_fetch)
    pack = iv.refresh_option_iv(
        tmp_path,
        asof="20261112",
        lookback_calendar_days=5,
        codes=["CF"],
    )
    assert pack["ok"] is True
    assert pack["asof"] == "20261112"
    assert pack["fetched"] >= 1
    assert pack["soft_empty"] >= 1
    assert "CF:20261112:False" in calls  # asof: do not poison-cache miss
    assert any(c.startswith("CF:") and c.endswith(":True") for c in calls)
    st = iv.iv_cache_status(tmp_path, codes=["CF"])
    assert st["newest_ok"] is not None
    assert st["newest_ok"] < "20261112"
