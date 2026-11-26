# -*- coding: utf-8 -*-
"""R8 closeout appendix A.1: bridge test (read-only attribution, not a candidate, not in DSR).

A1000k on the frozen 216-day window (2026-01-05 -> 2026-11-25) in a 2x2x2 factor table:
  data source  : local frozen snapshot / official per-contract stitched main (5% guard, seed data)
  fill basis   : calendar front-contract open (frozen) / main-contract open (long-sample engine)
  mode         : full (seats + carry) / base
Start cell = frozen E1000k (must reproduce Base +4.97 / Stress +3.48 bit for bit); end cell = long-sample engine on the window.
Extra cell: frozen start cell without the 15m minute cache (the official path has none).
Output: archive/R8/ATTRIB/bridge.json
"""
from __future__ import annotations

import copy
import json
import sys
from itertools import product
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE), str(ROOT / "lab" / "shadow")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import long_sample as ls  # noqa: E402

WIN0, WIN1 = "2026-01-05", "2026-11-25"
FROZEN = HERE / "E1000k" / "result.json"


def _params(snap_obj_p, mode, scenario):
    from path_a_filters import carry_bypass_cfg
    from research.execution.cost_model import load_cost_scenario

    p = snap_obj_p
    p["equity0"] = 1_000_000.0
    if mode == "base":
        p["carry_bypass"] = carry_bypass_cfg({"enabled": False})
    sc = load_cost_scenario(scenario, root=ROOT)
    if scenario != "base":
        p["slippage_ticks"], p["fee_mult"], p["cost_scenario"] = sc["slippage_ticks"], sc["fee_mult"], scenario
    return p


def run_cell(data, fill, mode, scenario, official, *, minute=True):
    import historical_backtest as hb

    names = ("prepare_pack_for_execution", "load_member_seats", "load_member_changes", "lag_member", "load_curves", "lag_curves_carry")
    saved = {k: getattr(hb, k) for k in names}  # BEFORE importing replay (import-time legacy side effect)
    try:
        from lab.shadow import replay
        from research.data_quality.contract_store import snapshot_store

        live = json.loads(FROZEN.read_text(encoding="utf-8"))
        snap_path = ROOT / live["input_snapshot"]["path"]
        snap_obj, bt_obj = replay.load_inputs(snap_path, FROZEN)
        replay.apply_freeze(snap_obj, bt_obj)
        p, pack_local = replay.make_pack(snap_obj=snap_obj)
        p = _params(p, mode, scenario)
        entry_mode = p["entry_filter"] if mode == "full" else "base"
        lsx = {"trade_start": WIN0, "skip_contract_overlay": fill == "main", "no_minute": (not minute) or data == "official"}
        if data == "local":
            pack = (copy.deepcopy(pack_local[0]), dict(pack_local[1]), dict(pack_local[2]))
            store = snapshot_store(snap_obj, Path(snap_path))
            if fill == "main":  # back to continuous-series open: drop the calendar front-contract stamps
                for s in pack[0].values():
                    for b in s["hist"]:
                        for k in [k for k in b if str(k).startswith("contract_")] + [k for k in ("fill_price_basis",) if k in b]:
                            del b[k]
            main_map = None
        else:
            pack, main_map, store, _info = official
            if fill == "cal":
                hb.prepare_pack_for_execution = saved["prepare_pack_for_execution"]  # the real calendar front-contract stamp
        r = ls.run_long("A", 1_000_000.0, scenario, pack, main_map, store, p=p, mode=entry_mode, ls_extra=lsx)
    finally:
        for k, v in saved.items():
            setattr(hb, k, v)
    out = r["out"]
    meta = {u["code"]: u for u in json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))["symbols"]}
    trades = []
    for t in out["closed_pnls"]:
        n = ls.trade_net_pnl(t, meta[t["code"]], float(out["slippage_ticks"]), float(out["fee_mult"]))
        trades.append({"code": t["code"], "dir": t["direction"], "entry_date": t["entry_date"], "date": t["date"], "reason": t.get("reason"),
                       "net": round(n["net"], 2), "n_rolls": n["n_rolls"]})
    keep = ("ret_pct", "max_dd_pct", "closed_trades", "cost_yuan", "exits", "avg_held", "roll_shifted", "roll_unpriced_cont",
            "held_contract_missing", "minute_exit_n", "fill_series", "start", "end", "trade_days", "equity_end")
    rec = {k: out.get(k) for k in keep}
    rec.update(skips=r.get("skips"), trade_dates=(out.get("long_sample") or {}).get("trade_dates"),
               final_positions=len(out.get("final_positions") or {}), trades=trades,
               slip=out["slippage_ticks"], fee_mult=out["fee_mult"])
    return rec


def main() -> int:
    official = ls.build_official_pack(w1=WIN1)
    assert official[3]["max_loaded_date"] <= WIN1
    cells = {}
    plan = [(d, f, m, True) for d, f, m in product(("local", "official"), ("cal", "main"), ("full", "base"))]
    plan.append(("local", "cal", "full", False))  # frozen start cell, no minute cache
    for d, f, m, minute in plan:
        key = f"{d}|{f}|{m}" + ("" if minute else "|no_minute")
        cells[key] = {}
        for sc in ("base", "stress"):
            cells[key][sc] = run_cell(d, f, m, sc, official, minute=minute)
        print(key, {sc: (cells[key][sc]["ret_pct"], cells[key][sc]["max_dd_pct"], cells[key][sc]["closed_trades"], cells[key][sc]["trade_dates"]) for sc in ("base", "stress")}, flush=True)
    out_dir = HERE / "ATTRIB"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "bridge.json").write_text(json.dumps({"window": [WIN0, WIN1], "official_info": official[3], "cells": cells}, ensure_ascii=False, default=str), encoding="utf-8")
    fr = json.loads(FROZEN.read_text(encoding="utf-8"))
    st = (fr.get("cost_scenario_contrast") or {}).get("rows", {}).get("stress") or {}
    c0 = cells["local|cal|full"]
    print("start cell vs frozen: base", c0["base"]["ret_pct"], fr["ret_pct"], "stress", c0["stress"]["ret_pct"], st.get("ret_pct"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
