# -*- coding: utf-8 -*-
"""VP Phase 1A — accounting, isolation, pollution fences."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from virtual_portfolio.engine import (
    VpError,
    check_auto_permissions,
    close_position,
    compute_account_state,
    create_account,
    deposit,
    list_accounts,
    load_account_state,
    mark_positions,
    open_position,
    rebuild_account,
)
from virtual_portfolio.guard import VpGuardError, assert_vp_write_path
from virtual_portfolio.ledger import append_event, load_events
from virtual_portfolio.permissions import VpPermissionError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def vp_root(tmp_path: Path) -> Path:
    """Isolated root with configs + formal artifacts to prove non-pollution."""
    # configs
    src_cfg = ROOT / "configs" / "virtual_portfolio"
    dst_cfg = tmp_path / "configs" / "virtual_portfolio"
    dst_cfg.mkdir(parents=True)
    for name in ("instruments_v1.json", "schema_versions.json"):
        shutil.copy(src_cfg / name, dst_cfg / name)
    # research_cost + universe for fill_cost slippage fallback
    for name in ("research_cost.json", "universe.json"):
        shutil.copy(ROOT / name, tmp_path / name)
    # formal artifacts that must stay byte-identical
    paper = tmp_path / "paper_book_latest.json"
    paper.write_text(json.dumps({"sentinel": "paper", "n": 1}), encoding="utf-8")
    l1 = tmp_path / "data" / "l1_report.json"
    l1.parent.mkdir(parents=True, exist_ok=True)
    l1.write_text(json.dumps({"sentinel": "l1", "asof": "2026-11-21"}), encoding="utf-8")
    gate = tmp_path / "data" / "options" / "upgrade_gate_latest.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(
        json.dumps({"ready": False, "next_upgrade_id": "F2", "sentinel": "gate"}),
        encoding="utf-8",
    )
    return tmp_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_guard_rejects_outside_namespace(vp_root: Path):
    with pytest.raises(VpGuardError):
        assert_vp_write_path(vp_root / "paper_book_latest.json", vp_root)
    ok = vp_root / "data" / "virtual_portfolio" / "a1" / "ledger.jsonl"
    ok.parent.mkdir(parents=True)
    assert_vp_write_path(ok, vp_root)


def test_multi_account_isolation(vp_root: Path):
    create_account(vp_root, "acct_a", initial_cash=100_000)
    create_account(vp_root, "acct_b", initial_cash=50_000)
    open_position(
        vp_root,
        "acct_a",
        symbol="MA",
        side="long",
        qty=2,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="a-open-1",
    )
    sa = load_account_state(vp_root, "acct_a")
    sb = load_account_state(vp_root, "acct_b")
    assert sa["equity"]["cash"] < 100_000
    assert abs(sb["equity"]["cash"] - 50_000) < 1e-6
    assert sb["positions"] == []
    assert any(p["symbol"] == "MA" for p in sa["positions"])


def test_open_add_reduce_close_equity_consistent(vp_root: Path):
    create_account(vp_root, "trader", initial_cash=200_000)
    open_position(
        vp_root,
        "trader",
        symbol="MA",
        side="long",
        qty=2,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="o1",
    )
    open_position(
        vp_root,
        "trader",
        symbol="MA",
        side="long",
        qty=1,
        price=2510,
        asof="2026-11-25",
        source="SYSTEM_TEST",
        client_event_id="o2",
    )
    st = load_account_state(vp_root, "trader")
    assert st["positions"][0]["qty"] == 3
    close_position(
        vp_root,
        "trader",
        symbol="MA",
        qty=1,
        price=2520,
        asof="2026-11-26",
        source="SYSTEM_TEST",
        client_event_id="c1",
    )
    st2 = load_account_state(vp_root, "trader")
    assert st2["positions"][0]["qty"] == 2
    close_position(
        vp_root,
        "trader",
        symbol="MA",
        qty=2,
        price=2530,
        asof="2026-11-27",
        source="SYSTEM_TEST",
        client_event_id="c2",
    )
    st3 = load_account_state(vp_root, "trader")
    assert st3["positions"] == []
    eq = st3["equity"]
    # cash + unrealized(=0) == equity; fees reduced cash vs initial
    assert abs(eq["cash"] - eq["equity"]) < 1e-6
    assert eq["cash"] != 200_000


def test_margin_missing_flagged(vp_root: Path):
    create_account(vp_root, "miss", initial_cash=100_000)
    st = open_position(
        vp_root,
        "miss",
        symbol="VPTEST",
        side="long",
        qty=1,
        price=100,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="m1",
    )
    assert st["equity"]["margin_complete"] is False
    assert "MARGIN_DATA_MISSING" in st["equity"]["flags"]
    assert st["last_event"].get("flags") and "MARGIN_DATA_MISSING" in st["last_event"]["flags"]


def test_reject_negative_and_duplicate(vp_root: Path):
    create_account(vp_root, "rej", initial_cash=100_000)
    with pytest.raises(VpError):
        open_position(
            vp_root,
            "rej",
            symbol="MA",
            side="long",
            qty=-1,
            price=2500,
            asof="2026-11-24",
            source="SYSTEM_TEST",
        )
    open_position(
        vp_root,
        "rej",
        symbol="MA",
        side="long",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="dup-1",
    )
    n1 = len(load_events(vp_root, "rej"))
    open_position(
        vp_root,
        "rej",
        symbol="MA",
        side="long",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="dup-1",
    )
    n2 = len(load_events(vp_root, "rej"))
    assert n1 == n2
    pos = load_account_state(vp_root, "rej")["positions"][0]
    assert pos["qty"] == 1


def test_lots_batches(vp_root: Path):
    create_account(vp_root, "lots", initial_cash=200_000)
    open_position(
        vp_root,
        "lots",
        symbol="MA",
        side="long",
        qty=2,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="l1",
    )
    open_position(
        vp_root,
        "lots",
        symbol="MA",
        side="long",
        qty=3,
        price=2600,
        asof="2026-11-25",
        source="SYSTEM_TEST",
        client_event_id="l2",
    )
    lots = load_account_state(vp_root, "lots")["positions"][0]["lots"]
    assert len(lots) == 2
    assert lots[0]["qty"] == 2 and lots[1]["qty"] == 3


def test_cta_signal_source_forbidden(vp_root: Path):
    create_account(vp_root, "sig", initial_cash=10_000)
    with pytest.raises((VpError, VpPermissionError)):
        open_position(
            vp_root,
            "sig",
            symbol="MA",
            side="long",
            qty=1,
            price=2500,
            asof="2026-11-24",
            source="CTA_SIGNAL",
        )
    with pytest.raises(VpPermissionError):
        check_auto_permissions(vp_root, "sig", action="open")
    st = load_account_state(vp_root, "sig")
    assert st["account"]["ACCOUNT_MODE"] == "RESEARCH_ONLY"
    assert st["account"]["AUTO_OPEN_ALLOWED"] is False
    assert st["account"]["SIGNAL_INGEST_ALLOWED"] is False


def test_persistence_rebuild(vp_root: Path):
    create_account(vp_root, "persist", initial_cash=80_000)
    open_position(
        vp_root,
        "persist",
        symbol="RB",
        side="short",
        qty=1,
        price=3500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="p1",
    )
    mark_positions(
        vp_root,
        "persist",
        {"RB": 3480},
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="mk1",
    )
    # wipe projections
    for name in ("account.json", "positions.json", "equity.json"):
        # keep account.json required — only wipe positions/equity
        if name == "account.json":
            continue
        (vp_root / "data" / "virtual_portfolio" / "persist" / name).unlink()
    st = rebuild_account(vp_root, "persist")
    assert st["positions"][0]["qty"] == 1
    assert st["positions"][0]["side"] == "short"
    assert st["n_events"] >= 2


def test_pollution_paper_l1_f2_unchanged(vp_root: Path):
    paper = vp_root / "paper_book_latest.json"
    l1 = vp_root / "data" / "l1_report.json"
    gate = vp_root / "data" / "options" / "upgrade_gate_latest.json"
    h0 = {_sha(paper), _sha(l1), _sha(gate)}
    hashes = {"paper": _sha(paper), "l1": _sha(l1), "gate": _sha(gate)}
    create_account(vp_root, "pollute", initial_cash=100_000)
    deposit(vp_root, "pollute", 1000, source="SYSTEM_TEST", client_event_id="d1")
    open_position(
        vp_root,
        "pollute",
        symbol="CF",
        side="long",
        qty=1,
        price=14000,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="o1",
    )
    close_position(
        vp_root,
        "pollute",
        symbol="CF",
        qty=1,
        price=14100,
        asof="2026-11-25",
        source="SYSTEM_TEST",
        client_event_id="c1",
    )
    assert _sha(paper) == hashes["paper"]
    assert _sha(l1) == hashes["l1"]
    assert _sha(gate) == hashes["gate"]
    gate_obj = json.loads(gate.read_text(encoding="utf-8"))
    assert gate_obj.get("ready") is False
    assert gate_obj.get("next_upgrade_id") == "F2"
    # VP data exists only under virtual_portfolio
    assert (vp_root / "data" / "virtual_portfolio" / "pollute" / "ledger.jsonl").is_file()
    assert list_accounts(vp_root) == ["pollute"]


def test_history_not_silently_rewritten(vp_root: Path):
    create_account(vp_root, "hist", initial_cash=10_000)
    append_event(
        vp_root,
        "hist",
        {
            "kind": "deposit",
            "amount": 500,
            "source": "SYSTEM_TEST",
            "client_event_id": "h1",
        },
    )
    path = vp_root / "data" / "virtual_portfolio" / "hist" / "ledger.jsonl"
    raw0 = path.read_text(encoding="utf-8")
    append_event(
        vp_root,
        "hist",
        {
            "kind": "deposit",
            "amount": 500,
            "source": "SYSTEM_TEST",
            "client_event_id": "h1",
        },
    )
    raw1 = path.read_text(encoding="utf-8")
    assert raw0 == raw1  # dedupe: no second line
    append_event(
        vp_root,
        "hist",
        {
            "kind": "deposit",
            "amount": 100,
            "source": "SYSTEM_TEST",
            "client_event_id": "h2",
            "note": "compensating",
        },
    )
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3  # bootstrap initial + h1 + h2 (initial_cash deposit)


def _mtime_tree(base: Path) -> dict[str, float]:
    out = {}
    for f in base.rglob("*"):
        if f.is_file():
            out[str(f.relative_to(base))] = f.stat().st_mtime_ns
    return out


def test_query_load_is_read_only(vp_root: Path):
    create_account(vp_root, "ro", initial_cash=50_000)
    open_position(
        vp_root,
        "ro",
        symbol="MA",
        side="long",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="ro1",
    )
    base = vp_root / "data" / "virtual_portfolio" / "ro"
    before = _mtime_tree(base)
    for _ in range(3):
        load_account_state(vp_root, "ro")
        compute_account_state(vp_root, "ro")
    after = _mtime_tree(base)
    assert before == after


def test_short_close_pnl(vp_root: Path):
    create_account(vp_root, "shortpnl", initial_cash=200_000)
    open_position(
        vp_root,
        "shortpnl",
        symbol="RB",
        side="short",
        qty=2,
        price=3500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="s1",
        slippage_ticks=0,
    )
    st = close_position(
        vp_root,
        "shortpnl",
        symbol="RB",
        qty=2,
        price=3400,
        asof="2026-11-25",
        source="SYSTEM_TEST",
        client_event_id="s2",
        slippage_ticks=0,
    )
    assert st["positions"] == []
    assert st["equity"]["realized_pnl"] > 0
    assert st["last_event"]["realized_pnl"] > 1500


def test_partial_close_long_and_short(vp_root: Path):
    create_account(vp_root, "partial", initial_cash=300_000)
    open_position(
        vp_root,
        "partial",
        symbol="MA",
        side="long",
        qty=3,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="pl1",
        slippage_ticks=0,
    )
    close_position(
        vp_root,
        "partial",
        symbol="MA",
        qty=1,
        price=2510,
        asof="2026-11-25",
        source="SYSTEM_TEST",
        client_event_id="pl2",
        slippage_ticks=0,
    )
    st = load_account_state(vp_root, "partial")
    assert st["positions"][0]["qty"] == 2
    create_account(vp_root, "partial_s", initial_cash=300_000)
    open_position(
        vp_root,
        "partial_s",
        symbol="RB",
        side="short",
        qty=3,
        price=3500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="ps1",
        slippage_ticks=0,
    )
    close_position(
        vp_root,
        "partial_s",
        symbol="RB",
        qty=2,
        price=3490,
        asof="2026-11-25",
        source="SYSTEM_TEST",
        client_event_id="ps2",
        slippage_ticks=0,
    )
    st2 = load_account_state(vp_root, "partial_s")
    assert st2["positions"][0]["qty"] == 1


def test_close_today_fee_flag_and_cost(vp_root: Path):
    cfg_path = vp_root / "configs" / "virtual_portfolio" / "instruments_v1.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for row in cfg["rows"]:
        if row["instrument_id"] == "MA":
            row["commission_close"] = {"fee_yuan": 1.0, "fee_rate": 0.0}
            row["commission_close_today"] = {"fee_yuan": 10.0, "fee_rate": 0.0}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    create_account(vp_root, "ctoday", initial_cash=100_000)
    open_position(
        vp_root,
        "ctoday",
        symbol="MA",
        side="long",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="ct1",
        slippage_ticks=0,
    )
    a = close_position(
        vp_root,
        "ctoday",
        symbol="MA",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="ct2",
        slippage_ticks=0,
        close_today=False,
    )
    create_account(vp_root, "ctoday2", initial_cash=100_000)
    open_position(
        vp_root,
        "ctoday2",
        symbol="MA",
        side="long",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="ct3",
        slippage_ticks=0,
    )
    b = close_position(
        vp_root,
        "ctoday2",
        symbol="MA",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="ct4",
        slippage_ticks=0,
        close_today=True,
    )
    assert b["last_event"]["fee"] > a["last_event"]["fee"]
    assert b["last_event"]["fee_kind"] == "close_today"


def test_tick_size_rejected(vp_root: Path):
    create_account(vp_root, "tick", initial_cash=50_000)
    with pytest.raises(VpError, match="PRICE_NOT_ON_TICK"):
        open_position(
            vp_root,
            "tick",
            symbol="MA",
            side="long",
            qty=1,
            price=2500.5,
            asof="2026-11-24",
            source="SYSTEM_TEST",
        )


def test_failed_open_leaves_ledger_unchanged(vp_root: Path):
    create_account(vp_root, "rollback", initial_cash=10)
    path = vp_root / "data" / "virtual_portfolio" / "rollback" / "ledger.jsonl"
    before = path.read_text(encoding="utf-8")
    with pytest.raises(VpError, match="INSUFFICIENT"):
        open_position(
            vp_root,
            "rollback",
            symbol="MA",
            side="long",
            qty=1,
            price=2500,
            asof="2026-11-24",
            source="SYSTEM_TEST",
            client_event_id="rb1",
        )
    after = path.read_text(encoding="utf-8")
    assert before == after


def test_rebuild_matches_compute(vp_root: Path):
    create_account(vp_root, "cons", initial_cash=100_000)
    open_position(
        vp_root,
        "cons",
        symbol="MA",
        side="long",
        qty=1,
        price=2500,
        asof="2026-11-24",
        source="SYSTEM_TEST",
        client_event_id="c1",
    )
    computed = compute_account_state(vp_root, "cons")
    rebuilt = rebuild_account(vp_root, "cons", note="test")
    assert computed["equity"]["cash"] == rebuilt["equity"]["cash"]
    assert computed["equity"]["equity"] == rebuilt["equity"]["equity"]
    assert computed["positions"][0]["qty"] == rebuilt["positions"][0]["qty"]
    loaded = load_account_state(vp_root, "cons")
    assert loaded["equity"]["equity"] == rebuilt["equity"]["equity"]
