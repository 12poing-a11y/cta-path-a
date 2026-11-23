# -*- coding: utf-8 -*-
"""fix3 CI gates: freeze fix, delivery-month guard, truncation lookahead, locked OOS.

Offline: replays archive/snapshots/bt_input_20261113_d246813d911a.json (no network).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "lab" / "shadow", ROOT / "lab" / "shadow" / "fix3"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if "ifind_call" not in sys.modules:
    stub = types.ModuleType("ifind_call")
    stub.active_slot = lambda *a, **k: None
    stub.call = lambda *a, **k: {}
    stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = stub

import historical_backtest as hb  # noqa: E402

SNAP = ROOT / "archive/snapshots/bt_input_20261113_d246813d911a.json"
pytestmark = pytest.mark.skipif(not SNAP.exists(), reason="snapshot missing")

_PATCHED = ("prepare_pack_for_execution", "load_member_seats", "load_member_changes", "lag_member", "load_curves", "lag_curves_carry")
_SHADOW_MODS = ("replay", "variants", "recompute", "oos_gate", "seat_backfill_run")


@pytest.fixture(autouse=True)
def _isolate_replay_patches():
    """lab/shadow/replay.py monkeypatches historical_backtest at import; undo after each test."""
    saved = {k: getattr(hb, k) for k in _PATCHED}
    yield
    for k, v in saved.items():
        setattr(hb, k, v)
    for m in _SHADOW_MODS:
        sys.modules.pop(m, None)


def test_delivery_ym():
    assert hb.contract_delivery_ym("L2601") == "2026-01"
    assert hb.contract_delivery_ym("FG2605") == "2026-05"
    assert hb.contract_delivery_ym("CF605") == "2026-05"
    assert hb.contract_delivery_ym("XX") is None


def test_manage_bar_fixed_uses_basis_when_contract_missing():
    p = {"fill_price_basis": "contract", "fill_contract": "L2601"}
    b1 = {"date": "d1", "contract": "L2601", "open": 100, "high": 110, "low": 90, "close": 105,
          "contract_open": 98, "contract_high": 108, "contract_low": 88, "contract_close": 103}
    m, prox, fr = hb.manage_bar_fixed(b1, p)
    assert not prox and fr is None and m["close"] == 103 and p["basis_off"] == -2
    b2 = {"date": "d2", "contract": "L2605", "open": 200, "high": 210, "low": 190, "close": 205,
          "contract_open": 300, "contract_high": 310, "contract_low": 290, "contract_close": 305}
    m, prox, fr = hb.manage_bar_fixed(b2, p)  # other month => continuous + last basis, never other-month OHLC
    assert prox and fr is None and m["close"] == 203 and m["high"] == 208 and m["low"] == 188


def test_legacy_reproduces_ee4476b_and_fix_has_no_cross_delivery():
    import replay as R
    import recompute as RC

    p, pack = R.make_pack()
    legacy = R.run(p, pack, freeze_fix=False, min_seat_days=0)
    # R2→R3: gap-through stop fills at open → KPI lock drifts (same n=42).
    assert (legacy["ret_pct"], legacy["max_dd_pct"], legacy["closed_trades"]) == (4.189, 4.294, 42)
    assert len(RC.cross_delivery(legacy)) == 2  # L2601 / FG2605 frozen across delivery month
    p, pack = R.make_pack()
    fixed = R.run(p, pack)
    assert fixed["freeze_fix"]["enabled"] is True
    assert RC.cross_delivery(fixed) == []
    for t in fixed["closed_pnls"]:
        if t.get("fill_price_basis") == "contract":
            held = [b for b in pack[0][t["code"]]["hist"] if t["entry_date"] <= b["date"] <= t["date"]]
            assert len(held) <= 40, t  # no multi-month freeze


def test_truncation_lookahead_four_cuts():
    import oos_gate as G

    res = G.lookahead()
    assert set(res) == set(G.CUTS)
    for cut, r in res.items():
        assert r["ok"], (cut, r["only_full"][:3], r["only_trunc"][:3])
        assert r["full_entries"] > 0


def test_truncation_lookahead_with_backfilled_seats_truncated():
    """H口径: DCE historical-main seat backfill; bars AND seats truncated at each cut."""
    import oos_gate as G

    mem = G.backfilled_member()
    assert sum(len(mem.get(c) or {}) for c in ("M", "P", "L", "I")) > 300
    res = G.lookahead(member=mem)
    for cut, r in res.items():
        assert r["ok"], (cut, r["only_full"][:3], r["only_trunc"][:3])


def test_truncation_lookahead_block_variant():
    """entry_delivery_action=block must also be truncation-safe (ex-ante calendar)."""
    import oos_gate as G

    res = G.lookahead(entry_delivery_action="block")
    for cut, r in res.items():
        assert r["ok"], (cut, r["only_full"][:3], r["only_trunc"][:3])


def test_locked_oos_train_only_selection_and_report():
    import oos_gate as G

    seen = []
    orig = G.R.make_pack

    def spy(bars=None):
        seen.append(max(b["date"] for h in (bars or G.R.snap["bars"]).values() for b in h))
        return orig(bars)

    G.R.make_pack = spy
    try:
        res = G.oos()
    finally:
        G.R.make_pack = orig
    assert res["n_trials"] == len(hb.STOP_GRID) * len(hb.RR_GRID)
    # every other make_pack call (the selection input) is truncated at train end
    assert all(d <= G.TR_END for d in seen[0::2])
    assert res["train_test_rank_corr"] is not None
    assert res["pbo"]["ok"] and 0.0 <= res["pbo"]["pbo"] <= 1.0
    assert res["test_trades_formal"] > 0 and res["formal_0.8_2"]["train_n"] > 0


def test_seat_gate_as_of_T():
    import replay as R

    p, pack = R.make_pack()
    out = R.run(p, pack)
    sg = out["seat_gate"]
    assert sg["rule"] == "as_of_T_post_lag" and sg["min_seat_days"] == 60
    # short-history varieties (DCE 21/42 days in snapshot) never reach 60 => always skipped
    for c in ("I", "JM", "M", "P", "L"):
        assert sg["seat_days"].get(c, 0) < 60


def test_entry_delivery_window():
    import replay as R

    p, pack = R.make_pack()
    out = R.run(p, pack)
    assert out["delivery_entry_block"]["buffer_sessions"] == 10
    assert sum(out["delivery_entry_block"]["blocked"].values()) > 0
    import numpy as np

    for t in out["closed_pnls"]:
        if t.get("fill_price_basis") != "contract":
            continue
        ym = hb.contract_delivery_ym(t.get("fill_contract"))
        assert int(np.busday_count(t["entry_date"][:10], f"{ym}-01")) >= 10, t
