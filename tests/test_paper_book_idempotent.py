# -*- coding: utf-8 -*-
"""Paper book: same-day refresh must not corrupt equity / positions."""
from __future__ import annotations

import json
from pathlib import Path

from paper_book import refresh_paper_book


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _minimal_report(*, asof: str = "20261113") -> dict:
    return {
        "asof": asof,
        "equity": 200000,
        "quality_ok": True,
        "signals": [
            {
                "code": "MA",
                "name": "甲醇",
                "bucket": "能化",
                "direction": "多",
                "selected": True,
                "close": 3000.0,
                "atr": 50.0,
                "stop": 2960.0,
                "target": 3080.0,
                "lots_l1": 1,
                "r20": 5.0,
                "r60": 8.0,
                "mult": 10,
            }
        ],
    }


def test_double_refresh_same_asof_is_noop(tmp_path: Path, monkeypatch):
    root = tmp_path
    _write(root / "universe.json", {"equity": 200000, "symbols": [{"code": "MA", "mult": 10}]})
    _write(root / "execution_rules.json", {"stop_atr_mult": 0.8, "reward_rr": 2.0})
    report = _minimal_report()
    _write(root / "l1_report.json", report)
    # Empty backtest seed
    _write(
        root / "historical_backtest_latest.json",
        {"final_positions": {}, "batch": "test"},
    )

    # Avoid minute I/O
    monkeypatch.setattr(
        "paper_book._intraday_stop_exit",
        lambda *a, **k: (None, None),
    )

    first = refresh_paper_book(root, report=report)
    assert first["ok"] is True
    assert first.get("noop") is not True
    assert first["held_n"] == 1
    equity1 = first["equity"]
    ledger_n1 = first["ledger_n"]

    second = refresh_paper_book(root, report=report)
    assert second["ok"] is True
    assert second.get("noop") is True
    assert second["equity"] == equity1
    assert second["ledger_n"] == ledger_n1
    assert second["held_n"] == 1
    assert "MA" in (second.get("positions") or {})


def test_reject_stale_asof(tmp_path: Path, monkeypatch):
    root = tmp_path
    _write(root / "universe.json", {"equity": 200000, "symbols": [{"code": "MA", "mult": 10}]})
    _write(root / "execution_rules.json", {"stop_atr_mult": 0.8, "reward_rr": 2.0})
    _write(root / "historical_backtest_latest.json", {"final_positions": {}})
    monkeypatch.setattr("paper_book._intraday_stop_exit", lambda *a, **k: (None, None))

    newer = _minimal_report(asof="20261113")
    _write(root / "l1_report.json", newer)
    assert refresh_paper_book(root, report=newer)["ok"] is True

    older = _minimal_report(asof="20261112")
    out = refresh_paper_book(root, report=older)
    assert out["ok"] is False
    assert "stale" in str(out.get("error") or "")


def test_corrupt_book_fails_loud(tmp_path: Path):
    root = tmp_path
    _write(root / "universe.json", {"equity": 200000, "symbols": []})
    _write(root / "execution_rules.json", {"stop_atr_mult": 0.8, "reward_rr": 2.0})
    (root / "paper_book_latest.json").write_text("{not-json", encoding="utf-8")
    _write(root / "l1_report.json", _minimal_report())
    out = refresh_paper_book(root, report=_minimal_report())
    assert out["ok"] is False
    assert "corrupt" in str(out.get("error") or "")


def test_entry_day_skips_intraday(monkeypatch, tmp_path: Path):
    """Same-day open must not be stopped by intraday helper even if it would fire."""
    from paper_book import _intraday_stop_exit

    pos = {
        "code": "MA",
        "direction": "多",
        "entry": 3000,
        "stop": 2960,
        "target": 3080,
        "entry_date": "2026-11-13",
    }
    # If skip fails, this would try to load minutes; ensure we never get a fake stop.
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not load minutes on entry day")

    monkeypatch.setattr("minute_data.load_minute_bars_on_date", boom, raising=False)
    reason, px = _intraday_stop_exit(pos, root=tmp_path, asof_iso="2026-11-13")
    assert reason is None and px is None
    assert called["n"] == 0
