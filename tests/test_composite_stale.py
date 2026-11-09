# -*- coding: utf-8 -*-
"""Stale desk composite must be marked expired and not feed the final-signal score."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import desk.final_signal as fs  # noqa: E402


def _composite(**over):
    base = {
        "ok": True,
        "desk_score": 51.5,
        "selected": {"asof": "20261105", "n": 1},
        "generated_at": "2026-11-05T16:37:29+08:00",
    }
    base.update(over)
    return base


def test_ymd_normalises():
    assert fs._ymd("20261109") == "2026-11-09"
    assert fs._ymd("2026-11-09T10:00:00+08:00") == "2026-11-09"
    assert fs._ymd("") is None
    assert fs._ymd("garbage") is None


def test_fresh_when_asof_matches_l1():
    r = fs.composite_freshness(_composite(selected={"asof": "20261109"}), "20261109")
    assert r["expired"] is False


def test_expired_on_mismatch_and_missing():
    r = fs.composite_freshness(_composite(), "20261109")
    assert r["expired"] is True and "≠" in r["reason"]
    assert fs.composite_freshness(None, "20261109")["expired"] is True
    assert fs.composite_freshness(_composite(), None)["expired"] is True
    # composite newer than L1 is also a mismatch
    assert fs.composite_freshness(_composite(selected={"asof": "20261110"}), "20261109")["expired"] is True


def test_generated_at_fallback():
    c = {"ok": True, "desk_score": 50, "generated_at": "2026-11-09T16:00:00+08:00"}
    assert fs.composite_freshness(c, "20261109")["expired"] is False
    c["generated_at"] = "2026-10-29T16:37:29+08:00"
    assert fs.composite_freshness(c, "20261109")["expired"] is True


def test_resolve_composite_hides_score_when_stale(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "desk_composite_latest.json").write_text(
        json.dumps(_composite()), encoding="utf-8"
    )
    # Recompute path unavailable/stale -> must stay expired with score hidden.
    import desk.composite_eval as ce

    monkeypatch.setattr(
        ce, "desk_composite_score", lambda root, write=False: {"ok": False, "desk_score": None}
    )
    out = fs.resolve_composite(tmp_path, "20261109")
    assert out is not None
    assert out["expired"] is True
    assert out["desk_score"] is None
    assert out["stale_score"] == 51.5


def test_resolve_composite_recomputes_when_stale(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "desk_composite_latest.json").write_text(
        json.dumps(_composite()), encoding="utf-8"
    )
    import desk.composite_eval as ce

    monkeypatch.setattr(
        ce,
        "desk_composite_score",
        lambda root, write=False: {
            "ok": True,
            "desk_score": 60.0,
            "selected": {"asof": "20261109"},
        },
    )
    out = fs.resolve_composite(tmp_path, "20261109")
    assert out["expired"] is False and out["desk_score"] == 60.0
