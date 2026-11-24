# -*- coding: utf-8 -*-
"""R5a: ``ensure_contract_bars`` reads the cache first and fetches only what is missing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.data_quality.contract_cache import (  # noqa: E402
    ensure_contract_bars,
    nearest_listed_contracts,
    recent_expired_contracts,
)


def _bars(*days):
    return [{"date": d, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10} for d in days]


def test_nearest_listed_contracts_are_not_expired():
    got = nearest_listed_contracts("RB", "2026-11-23", 3)
    assert len(got) == 3
    assert got[0] >= "RB2611"  # ordered, YYMM
    assert got == sorted(got)


def test_cache_first_then_fetch_only_missing(tmp_path):
    calls = []

    def fetcher(contract):
        calls.append(contract)
        return _bars("2026-11-20", "2026-11-23")

    rep = ensure_contract_bars("RB", "2026-11-23", tmp_path, prev_main="RB2701", fetcher=fetcher)
    assert rep["requests"] == len(calls) == len(rep["fetched"]) >= 1
    assert not rep["failed"]
    for c in rep["fetched"]:
        data = json.loads((tmp_path / ".cache" / "contracts" / f"{c}.json").read_text(encoding="utf-8"))
        assert data["bars"][-1]["date"] == "2026-11-23"
    calls.clear()
    rep2 = ensure_contract_bars("RB", "2026-11-23", tmp_path, prev_main="RB2701", fetcher=fetcher)
    assert rep2["requests"] == 0 and not calls  # everything is cached now
    assert set(rep2["cached"]) == set(rep["fetched"])


def test_stale_cache_is_extended_and_merged(tmp_path):
    p = tmp_path / ".cache" / "contracts"
    p.mkdir(parents=True)
    (p / "RB2701.json").write_text(
        json.dumps({"contract": "RB2701", "bars": _bars("2026-11-18", "2026-11-19")}), encoding="utf-8"
    )
    rep = ensure_contract_bars(
        "RB", "2026-11-23", tmp_path, prev_main="RB2701", fetcher=lambda c: _bars("2026-11-19", "2026-11-23")
    )
    assert "RB2701" in rep["fetched"]
    data = json.loads((p / "RB2701.json").read_text(encoding="utf-8"))
    assert [b["date"] for b in data["bars"]] == ["2026-11-18", "2026-11-19", "2026-11-23"]


def test_fetch_failure_is_recorded_not_raised(tmp_path):
    def boom(contract):
        raise RuntimeError("network down")

    rep = ensure_contract_bars("RB", "2026-11-23", tmp_path, prev_main="RB2701", fetcher=boom)
    assert rep["fetched"] == [] and rep["failed"]
    assert not (tmp_path / ".cache" / "contracts").exists() or not list((tmp_path / ".cache" / "contracts").glob("*.json"))


def test_recent_expired_contracts_cover_the_signal_window():
    assert recent_expired_contracts("RB", "2026-11-23", 150) == ["RB2610"]  # RB lists 1/5/10 only
    cf = recent_expired_contracts("CF", "2026-11-23", 150)
    assert {"CF2607", "CF2609", "CF2611"} <= set(cf)
    assert not set(cf) & set(nearest_listed_contracts("CF", "2026-11-23", 3))
