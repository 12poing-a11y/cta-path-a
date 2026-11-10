# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from scripts.gamma_wall_daily_collect import expiry_from_snapshot, resolve_expiry

ROOT = Path(__file__).resolve().parents[1]


def test_expiry_from_repo_snapshot_cf():
    # Real PASS snapshot should yield a future expiry relative to 2026-11-09.
    exp = expiry_from_snapshot("CF2701", "2026-11-09", root=ROOT)
    assert exp == "2026-12-11"


def test_resolve_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GAMMA_CF2701_EXPIRY", "2027-01-15")
    exp, src = resolve_expiry("CF2701", "2026-11-09", root=tmp_path)
    assert exp == "2027-01-15" and src == "env"


def test_resolve_snapshot_fallback(tmp_path):
    d = tmp_path / "data" / "gamma_wall" / "MA2701"
    d.mkdir(parents=True)
    (d / "2026-11-09.json").write_text(
        json.dumps(
            {
                "asof": "2026-11-09",
                "expiry": "2026-12-11",
                "data_quality": {"status": "PASS"},
            }
        ),
        encoding="utf-8",
    )
    exp, src = resolve_expiry("MA2701", "2026-11-09", root=tmp_path)
    assert exp == "2026-12-11" and src == "snapshot"
