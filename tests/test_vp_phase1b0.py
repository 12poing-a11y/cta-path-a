# -*- coding: utf-8 -*-
"""VP Phase 1B-0 — read-only L1 → signal inbox hard gates."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from virtual_portfolio.engine import create_account, load_account_state
from virtual_portfolio.guard import VpGuardError, assert_vp_write_path
from virtual_portfolio.ledger import load_events
from virtual_portfolio.permissions import (
    VpPermissionError,
    assert_auto_open_allowed,
    resolve_runtime,
)
from virtual_portfolio.signal_inbox import (
    ingest_l1_to_inbox,
    load_inbox_asof,
    load_vp_runtime,
    set_signal_read_allowed,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample_l1(*, asof: str = "20261123", quality_ok: bool = True) -> dict:
    return {
        "asof": asof,
        "session_date": "2026-11-23",
        "quality_ok": quality_ok,
        "signals": [
            {
                "code": "MA",
                "ticker": "MAZL.CZC",
                "direction": "多",
                "selected": True,
                "lots_l1": 1,
                "sleeve": None,
                "bucket": "能化",
                "bar_date": "2026-11-23",
                "close": 3000.0,
                "atr": 100.0,
                "action": "多",
                "align": "同向",
            },
            {
                "code": "ZZZUNKNOWN",
                "direction": "空仓",
                "selected": False,
                "lots_l1": 0,
                "bar_date": "2026-11-23",
                "close": 1.0,
                "atr": 0.1,
            },
        ],
    }


@pytest.fixture()
def vp_root(tmp_path: Path) -> Path:
    src_cfg = ROOT / "configs" / "virtual_portfolio"
    dst_cfg = tmp_path / "configs" / "virtual_portfolio"
    dst_cfg.mkdir(parents=True)
    for name in ("instruments_v1.json", "schema_versions.json"):
        shutil.copy(src_cfg / name, dst_cfg / name)
    for name in ("research_cost.json", "universe.json"):
        shutil.copy(ROOT / name, tmp_path / name)

    paper = tmp_path / "paper_book_latest.json"
    paper.write_text(json.dumps({"sentinel": "paper", "n": 1}), encoding="utf-8")
    # Spec true source: repo-root l1_report.json
    l1 = tmp_path / "l1_report.json"
    l1.write_text(json.dumps(_sample_l1(), ensure_ascii=False), encoding="utf-8")
    gate = tmp_path / "data" / "options" / "upgrade_gate_latest.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(
        json.dumps({"ready": False, "next_upgrade_id": "F2", "sentinel": "gate"}),
        encoding="utf-8",
    )
    return tmp_path


def test_adapter_no_forbidden_imports():
    """T-RO-02: static source must not import daily_update / call refresh_paper_book."""
    import ast

    for rel in (
        Path("virtual_portfolio") / "adapters" / "l1.py",
        Path("virtual_portfolio") / "signal_inbox.py",
    ):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
                assert "daily_update" not in names
                assert "paper_book" not in names
            if isinstance(node, ast.ImportFrom):
                assert node.module not in ("daily_update", "paper_book")
            if isinstance(node, ast.Attribute) and node.attr == "refresh_paper_book":
                raise AssertionError(f"{rel}: refresh_paper_book attribute use forbidden")
            if isinstance(node, ast.Name) and node.id == "refresh_paper_book":
                raise AssertionError(f"{rel}: refresh_paper_book name forbidden")


def test_ingest_blocked_without_signal_read(vp_root: Path):
    """T-RO-03"""
    with pytest.raises(VpPermissionError, match="SIGNAL_READ_ALLOWED"):
        ingest_l1_to_inbox(vp_root)


def test_ingest_ok_does_not_pollute_or_touch_ledger(vp_root: Path):
    """T-RO-01 + T-RO-04"""
    create_account(vp_root, "obs", initial_cash=100_000)
    ledger_before = load_events(vp_root, "obs")
    l1 = vp_root / "l1_report.json"
    paper = vp_root / "paper_book_latest.json"
    gate = vp_root / "data" / "options" / "upgrade_gate_latest.json"
    h_l1, h_paper, h_gate = _sha(l1), _sha(paper), _sha(gate)

    set_signal_read_allowed(vp_root, True)
    rt = load_vp_runtime(vp_root)
    assert rt["SIGNAL_READ_ALLOWED"] is True
    assert rt["SIGNAL_INGEST_ALLOWED"] is False
    assert rt["AUTO_OPEN_ALLOWED"] is False

    # READ=true must not unlock auto-open
    with pytest.raises(VpPermissionError):
        assert_auto_open_allowed(rt)

    out = ingest_l1_to_inbox(vp_root)
    assert out["status"] == "OK"
    assert out["signal_asof"] == "20261123"

    assert _sha(l1) == h_l1
    assert _sha(paper) == h_paper
    assert _sha(gate) == h_gate
    assert load_events(vp_root, "obs") == ledger_before
    st = load_account_state(vp_root, "obs")
    assert abs(float(st["equity"]["cash"]) - 100_000) < 1e-6

    doc = load_inbox_asof(vp_root, "20261123")
    assert doc is not None
    assert doc["n_rows"] == 2
    assert doc["n_unmapped"] >= 1


def test_duplicate_ingest(vp_root: Path):
    """T-RO-05"""
    set_signal_read_allowed(vp_root, True)
    a = ingest_l1_to_inbox(vp_root)
    b = ingest_l1_to_inbox(vp_root)
    assert a["status"] == "OK"
    assert b["status"] == "DUPLICATE"
    doc = load_inbox_asof(vp_root, "20261123")
    assert doc is not None
    assert len(doc["rows"]) == 2


def test_guard_rejects_paper_write_escape(vp_root: Path):
    """T-RO-06"""
    with pytest.raises(VpGuardError):
        assert_vp_write_path(vp_root / "paper_book_latest.json", vp_root)


def test_missing_l1_rejects(vp_root: Path):
    """T-RO-07"""
    (vp_root / "l1_report.json").unlink()
    set_signal_read_allowed(vp_root, True)
    out = ingest_l1_to_inbox(vp_root)
    assert out["status"] == "REJECTED"
    assert out["reason"] == "MISSING_L1"


def test_bad_json_rejects(vp_root: Path):
    """T-RO-07"""
    (vp_root / "l1_report.json").write_text("{not-json", encoding="utf-8")
    set_signal_read_allowed(vp_root, True)
    out = ingest_l1_to_inbox(vp_root)
    assert out["status"] == "REJECTED"
    assert out["reason"] == "BAD_JSON"


def test_resolve_runtime_defaults_signal_read_false():
    rt = resolve_runtime({})
    assert rt["SIGNAL_READ_ALLOWED"] is False
    assert rt["SIGNAL_INGEST_ALLOWED"] is False
