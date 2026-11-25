# -*- coding: utf-8 -*-
"""R8 research helper (read-only w.r.t. the repo): offline replay on a frozen snapshot with wrappers that
record, per run, how many signals were skipped for 0 lots, how many entries were lifted to min_lots, and the
actual per-trade risk.  No repo code is patched on disk; wrappers are installed in-process only.

usage:
  python archive/R8/_r8_stats.py --tag base [--equity N] [--max-gross PCT] [--min-lots N] [--bt PATH --snap PATH]
Writes archive/R8/<tag>/stats_offline.json (and prints a summary).  Never writes root files.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab" / "shadow"))


def run_stats(*, snap_path: Path, bt_path: Path, equity=None, max_gross=None, min_lots=None) -> dict:
    import historical_backtest as hb
    from lab.shadow import replay
    from research.data_quality.contract_store import snapshot_store

    snap_obj, bt_obj = replay.load_inputs(snap_path, bt_path)
    replay.apply_freeze(snap_obj, bt_obj)
    p, pack = replay.make_pack(snap_obj=snap_obj)
    if equity is not None:
        p["equity0"] = float(equity)
    if max_gross is not None:
        p["max_gross_pct"] = float(max_gross)
    if min_lots is not None:
        p["min_lots"] = int(min_lots)
    store = snapshot_store(snap_obj, snap_path)
    mult = {c: float(s["meta"].get("mult") or 1) for c, s in pack[0].items()}

    ctx = {"day": None}
    cand_log: list[dict] = []          # one row per path_a_candidate call that reached sizing
    caps_first: dict[str, dict] = {}   # day -> meta of the first (real) apply_portfolio_caps call

    orig_cand = hb.path_a_candidate
    orig_caps = hb.apply_portfolio_caps

    def cand_wrap(code, hist, i, **kw):
        day = kw["ctx"]["day"]
        ctx["day"] = day
        res = orig_cand(code, hist, i, **kw)
        sz = res.get("sizing")
        if res.get("status") in ("ok", "lots0") and sz is not None:
            cand_log.append({
                "day": day, "code": code, "status": res["status"], "direction": res.get("direction"),
                "lots": sz["lots"], "bumped": bool(sz.get("min_lots_bumped")),
                "stop_dist": sz["stop_dist"], "risk_per_lot": sz["risk_per_lot"],
            })
        return res

    def caps_wrap(cands, **kw):
        sel, meta = orig_caps(cands, **kw)
        day = ctx["day"]
        if day is not None and day not in caps_first:
            caps_first[day] = {"min_lots_bumped": list(meta.get("min_lots_bumped") or []),
                               "selected": [c["code"] for c in sel]}
        return sel, meta

    hb.path_a_candidate = cand_wrap
    hb.apply_portfolio_caps = caps_wrap
    clog: list[dict] = []
    try:
        out = replay.run(p, pack, contract_root=store, candidate_log=clog)
    finally:
        hb.path_a_candidate = orig_cand
        hb.apply_portfolio_caps = orig_caps

    eq_by_day = {r["date"]: float(r["equity"]) for r in out.get("equity_curve") or []}
    sizing_eq = {e["date"]: float(e["sizing_eq"]) for e in clog}
    dates = [r["date"] for r in out.get("equity_curve") or []]
    nxt = {d: dates[i + 1] for i, d in enumerate(dates[:-1])}

    # ---- skipped signals (0 lots) --------------------------------------------------------------
    lots0 = [r for r in cand_log if r["status"] == "lots0"]
    one_lot = []
    for r in lots0:
        eq = sizing_eq.get(r["day"])
        if eq:
            one_lot.append(r["stop_dist"] * mult[r["code"]] / eq * 100.0)
    by_code: dict[str, int] = {}
    for r in lots0:
        by_code[r["code"]] = by_code.get(r["code"], 0) + 1

    # ---- entries lifted to min_lots ------------------------------------------------------------
    sel_by_day = {e["date"]: dict(e["selected"]) for e in clog}
    cand_idx = {(r["day"], r["code"]): r for r in cand_log}
    bumped_entries = []
    for d, sel in sel_by_day.items():
        capsb = set((caps_first.get(d) or {}).get("min_lots_bumped") or [])
        for code, lots in sel.items():
            c = cand_idx.get((d, code))
            by_sizing = bool(c and c["bumped"])
            by_caps = code in capsb
            if by_sizing or by_caps:
                bumped_entries.append({"signal_day": d, "code": code, "lots": lots,
                                       "by_sizing": by_sizing, "by_caps_floor": by_caps})

    # ---- per-trade actual risk (|entry-stop| x lots x mult / equity before entry) --------------
    def prior_equity(entry_date):
        prev = [d for d in dates if d < entry_date]
        return eq_by_day.get(prev[-1]) if prev else out.get("equity_start")

    trades = out.get("closed_pnls") or []
    risks = []
    risk_by_key = {}
    for t in trades:
        e0 = prior_equity(t["entry_date"])
        if not e0:
            continue
        rk = abs(float(t["entry"]) - float(t["stop"])) * int(t["lots"]) * mult.get(t["code"], 1) / e0 * 100.0
        risks.append(rk)
        risk_by_key[(t["code"], t["entry_date"])] = rk
    sig_of_entry = {(code, nxt.get(r["signal_day"])): r for r in bumped_entries for code in [r["code"]]}
    bumped_trade_risks = [risk_by_key[k] for k in sig_of_entry if k in risk_by_key]

    curve = out.get("equity_curve") or []
    gross_curve_max = max((float(r.get("gross_pct") or 0) for r in curve), default=None)

    def q(xs, f):
        return round(f(xs), 3) if xs else None

    return {
        "overrides": {"equity0": p["equity0"], "max_gross_pct": p["max_gross_pct"], "min_lots": p["min_lots"]},
        "replay_input": {"snapshot": str(snap_path.relative_to(ROOT)) if snap_path.is_relative_to(ROOT) else str(snap_path)},
        "kpi": {k: out.get(k) for k in ("ret_pct", "gross_ret_pct", "max_dd_pct", "cost_yuan", "closed_trades",
                                        "trade_win_rate", "expectancy_r", "exits", "equity_end",
                                        "caps_entry_gross_max", "caps_entry_risk_max", "caps_scaled_n")},
        "skipped_signals_lots0": {
            "signal_days": len(lots0),
            "by_code": dict(sorted(by_code.items(), key=lambda kv: -kv[1])),
            "if_lifted_to_1_lot_risk_pct": {"n": len(one_lot), "min": q(one_lot, min), "median": q(one_lot, statistics.median),
                                            "max": q(one_lot, max),
                                            "n_le_3pct": sum(1 for x in one_lot if x <= 3.0),
                                            "n_gt_3pct": sum(1 for x in one_lot if x > 3.0)},
            "note": "signal_days = (code, day) evaluations that passed momentum/seats/carry/vol and computed 0 lots; "
                    "a signal that persists several days is counted once per day",
        },
        "lifted_to_min_lots": {
            "entered_candidates_lifted": len(bumped_entries),
            "by_sizing": sum(1 for r in bumped_entries if r["by_sizing"]),
            "by_caps_floor": sum(1 for r in bumped_entries if r["by_caps_floor"]),
            "closed_trades_matched": len(bumped_trade_risks),
            "actual_risk_pct": {"max": q(bumped_trade_risks, max), "median": q(bumped_trade_risks, statistics.median),
                                "all": [round(x, 3) for x in bumped_trade_risks]},
            "entries": bumped_entries,
        },
        "trade_actual_risk_pct": {"n": len(risks), "max": q(risks, max), "median": q(risks, statistics.median),
                                  "n_gt_3pct": sum(1 for x in risks if x > 3.0)},
        "gross": {"curve_gross_pct_max": gross_curve_max},
        "equity_curve_returns_n": max(0, len(curve) - 1),
    }, out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--equity", type=float, default=None)
    ap.add_argument("--max-gross", type=float, default=None)
    ap.add_argument("--min-lots", type=int, default=None)
    ap.add_argument("--bt", default=str(ROOT / "historical_backtest_latest.json"))
    ap.add_argument("--snap", default=None)
    a = ap.parse_args(argv)
    bt_path = Path(a.bt)
    bt = json.loads(bt_path.read_text(encoding="utf-8"))
    snap_path = Path(a.snap) if a.snap else ROOT / bt["input_snapshot"]["path"]
    stats, out = run_stats(snap_path=snap_path, bt_path=bt_path, equity=a.equity, max_gross=a.max_gross,
                           min_lots=a.min_lots)
    d = ROOT / "archive" / "R8" / a.tag
    d.mkdir(parents=True, exist_ok=True)
    (d / "stats_offline.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("overrides", "kpi", "skipped_signals_lots0", "trade_actual_risk_pct", "gross")},
                     ensure_ascii=False, indent=1))
    lt = dict(stats["lifted_to_min_lots"]); lt.pop("entries", None)
    print("lifted:", json.dumps(lt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
