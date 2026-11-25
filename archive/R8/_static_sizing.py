# -*- coding: utf-8 -*-
"""R8 step 0 (read-only): static sizing diagnostics on the FORMAL frozen snapshot.

Offline replay of the formal setup (equity 200k, risk_pct 2, min_lots 0, no parameter changed) with in-process
wrappers that only *record*; nothing is patched on disk, no result file at the repo root is touched, no
experiment group is created (not counted in n_trials).

  (a) per symbol, per trading day: 1-lot notional and 1-lot stop risk (engine risk_per_lot = stop_dist * mult),
      median / max, and the minimum equity for ">=1 lot AND 1-lot notional <= half of the gross cap".
  (b) is the "1-lot stop risk > per-trade risk budget" half of F1 already blocked by floor rounding at BASE?
      can R4b top-up restore a 0-lot candidate?
  (c) BASE skipped-signal split: computed 0 lots / gross-cap scaled to 0 / positions full / bucket full (+ rest).

usage: python archive/R8/_static_sizing.py
writes archive/R8/static_sizing.json (numbers) ; the narrative lives in static_sizing.md
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab" / "shadow"))


def q(xs, f):
    return None if not xs else round(float(f(xs)), 4)


def pctile(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 4)


def main() -> int:
    import historical_backtest as hb
    from lab.shadow import replay
    from position_rules import _strength
    from research.data_quality.contract_store import snapshot_store

    bt_path = ROOT / "historical_backtest_latest.json"
    bt = json.loads(bt_path.read_text(encoding="utf-8"))
    snap_path = ROOT / bt["input_snapshot"]["path"]
    snap_obj, bt_obj = replay.load_inputs(snap_path, bt_path)
    replay.apply_freeze(snap_obj, bt_obj)
    p, pack = replay.make_pack(snap_obj=snap_obj)
    store = snapshot_store(snap_obj, snap_path)
    mult = {c: float(s["meta"].get("mult") or 1) for c, s in pack[0].items()}
    bucket_of = {c: s["meta"].get("bucket") for c, s in pack[0].items()}

    import research.data_quality.adjusted as adj_mod

    holder: dict = {}
    orig_adj, orig_cand, orig_caps = adj_mod.build_adjusted_pack, hb.path_a_candidate, hb.apply_portfolio_caps
    ctx = {"day": None}
    cand_log: list[dict] = []
    caps_first: dict[str, dict] = {}

    def adj_wrap(*a, **k):
        r = orig_adj(*a, **k)
        holder["adj"] = r
        return r

    def cand_wrap(code, hist, i, **kw):
        ctx["day"] = kw["ctx"]["day"]
        res = orig_cand(code, hist, i, **kw)
        sz = res.get("sizing")
        if res.get("status") in ("ok", "lots0") and sz is not None:
            cand_log.append({
                "day": ctx["day"], "code": code, "status": res["status"], "lots": sz["lots"],
                "risk_per_lot": sz["risk_per_lot"], "day_risk": kw["params"]["day_risk"],
                "close": hist[i]["close"],
            })
        return res

    def caps_wrap(cands, **kw):
        sel, meta = orig_caps(cands, **kw)
        d = ctx["day"]
        if d is not None and d not in caps_first:
            caps_first[d] = {
                "cands": [dict(c) for c in cands], "meta": json.loads(json.dumps(meta, default=str)),
                "selected": [c["code"] for c in sel], "max_positions": kw.get("max_positions"),
            }
        return sel, meta

    adj_mod.build_adjusted_pack, hb.path_a_candidate, hb.apply_portfolio_caps = adj_wrap, cand_wrap, caps_wrap
    clog: list[dict] = []
    try:
        out = replay.run(p, pack, contract_root=store, candidate_log=clog)
    finally:
        adj_mod.build_adjusted_pack, hb.path_a_candidate, hb.apply_portfolio_caps = orig_adj, orig_cand, orig_caps

    # replay must equal the formal result, otherwise nothing below means anything
    for k in ("ret_pct", "gross_ret_pct", "max_dd_pct", "closed_trades"):
        assert out.get(k) == bt.get(k), (k, out.get(k), bt.get(k))

    adj = holder["adj"]
    eq0 = float(p["equity0"])
    risk_pct, l1 = float(p["risk_pct"]), float(p["l1_mult"])
    gross_pct = float(p["max_gross_pct"])
    stop_mult = float(p["stop_atr_mult"])
    dates = [r["date"] for r in out["equity_curve"]]
    start = bt["start"]

    # ---------------------------------------------------------------- (a)
    per_code: dict[str, dict] = {}
    for code, a in sorted(adj.items()):
        idx = {str(b["date"])[:10]: j for j, b in enumerate(a.hist)}
        notl, riskl, need_r, need_n, need = [], [], [], [], []
        for d in dates:
            j = idx.get(d)
            if j is None or j < hb.WARMUP or d < start:
                continue
            atr = a.atr14(j)
            if not atr:
                continue
            close = float(a.hist[j]["close"])
            n1 = close * mult[code]                       # 1-lot notional (yuan)
            r1 = stop_mult * atr * mult[code]             # engine risk_per_lot (yuan)
            e_risk = r1 / (risk_pct / 100.0 * l1)         # equity so that floor(day_risk / r1) >= 1
            e_not = n1 / (0.5 * gross_pct / 100.0)        # equity so that 1-lot notional <= half of gross cap
            notl.append(n1); riskl.append(r1); need_r.append(e_risk); need_n.append(e_not)
            need.append(max(e_risk, e_not))
        per_code[code] = {
            "days": len(notl), "mult": mult[code], "bucket": bucket_of[code],
            "notional_1lot_yuan": {"median": q(notl, statistics.median), "max": q(notl, max)},
            "risk_1lot_yuan": {"median": q(riskl, statistics.median), "max": q(riskl, max)},
            "notional_pct_of_200k": {"median": q([x / eq0 * 100 for x in notl], statistics.median),
                                     "max": q([x / eq0 * 100 for x in notl], max)},
            "risk_pct_of_200k": {"median": q([x / eq0 * 100 for x in riskl], statistics.median),
                                 "max": q([x / eq0 * 100 for x in riskl], max)},
            "notional_pct_of_1m": {"median": q([x / 1e6 * 100 for x in notl], statistics.median),
                                   "max": q([x / 1e6 * 100 for x in notl], max)},
            "risk_pct_of_1m": {"median": q([x / 1e6 * 100 for x in riskl], statistics.median),
                               "max": q([x / 1e6 * 100 for x in riskl], max)},
            "min_equity_yuan": {"median": q(need, statistics.median), "p90": pctile(need, 0.9), "max": q(need, max),
                                "median_by_risk": q(need_r, statistics.median),
                                "median_by_notional": q(need_n, statistics.median)},
            "binding_on_median_day": "risk" if statistics.median(need_r) >= statistics.median(need_n) else "notional",
            "share_days_openable": {
                f"{int(E/1000)}k": round(sum(1 for v in need if v <= E) / len(need), 3)
                for E in (100_000, 200_000, 300_000, 500_000, 1_000_000)
            },
            "share_days_1lot_notional_gt_half_cap": {
                f"{int(E/1000)}k": round(sum(1 for v in notl if v > 0.5 * E * gross_pct / 100) / len(notl), 3)
                for E in (200_000, 1_000_000)
            },
            "share_days_1lot_notional_gt_full_cap": {
                f"{int(E/1000)}k": round(sum(1 for v in notl if v > E * gross_pct / 100) / len(notl), 3)
                for E in (200_000, 1_000_000)
            },
        }

    # ---------------------------------------------------------------- (b)
    ok_rows = [r for r in cand_log if r["status"] == "ok"]
    lots0_rows = [r for r in cand_log if r["status"] == "lots0"]
    ok_viol = [r for r in ok_rows if r["risk_per_lot"] > r["day_risk"] + 1e-9]
    lots0_not_over = [r for r in lots0_rows if r["risk_per_lot"] <= r["day_risk"] + 1e-9]
    # can top-up restore a lots0 signal?  lots0 never enters `cands` (engine: status != ok -> continue)
    sel_codes = {d: set(v["selected"]) for d, v in caps_first.items()}
    lots0_selected = [r for r in lots0_rows if r["code"] in sel_codes.get(r["day"], set())]
    topup = {k: out.get(k) for k in out if "topup" in k}

    # ---------------------------------------------------------------- (c)
    cats = Counter()
    by_cat_code: dict[str, Counter] = defaultdict(Counter)
    lots0_by_code = Counter(r["code"] for r in lots0_rows)
    cats["lots0"] = len(lots0_rows)
    by_cat_code["lots0"].update(lots0_by_code)
    check_bucket = check_drop = 0
    for d, v in caps_first.items():
        m, cands, final = v["meta"], v["cands"], set(v["selected"])
        weak, bsk = set(m.get("weak_filtered") or []), set(m.get("bucket_skipped") or [])
        strong = [c for c in cands if c["code"] not in weak]
        ranked = sorted(strong, key=_strength, reverse=True)
        sel3, ncap, bk = [], set(), set()
        counts = dict(m.get("_existing_buckets") or {})
        # replicate stage 2-3 exactly as position_rules does (existing buckets are not in meta -> use cands/held)
        held = (next((e for e in clog if e["date"] == d), {}) or {}).get("held") or {}
        counts = Counter(str(h.get("bucket") or "_") for h in held.values())
        for c in ranked:
            if len(sel3) >= max(0, int(v["max_positions"])):
                ncap.add(c["code"]); continue
            b = str(c.get("bucket") or "_")
            if int(p["max_per_bucket"]) > 0 and counts.get(b, 0) >= int(p["max_per_bucket"]):
                bk.add(c["code"]); continue
            sel3.append(c); counts[b] = counts.get(b, 0) + 1
        assert bk == bsk, (d, bk, bsk)       # replication check against the engine's own meta
        check_bucket += len(bk)
        check_drop += len(ncap)
        for c in cands:
            code = c["code"]
            if code in final:
                continue
            if code in weak:
                k = "weak_momentum(caps)"
            elif code in bsk:
                k = "bucket_full"
            elif code in ncap:
                k = "positions_full(N cap, slots_left>0)"
            else:
                sg, sr = float(m.get("scale_gross", 1.0)), float(m.get("scale_risk", 1.0))
                lg = math.floor(int(c["lots"]) * sg) if sg < 1 else int(c["lots"])
                lr = math.floor(lg * sr) if sr < 1 else lg
                if sg < 1 and lg == 0:
                    k = "gross_cap_scaled_to_0"
                elif lr == 0:
                    k = "atr_risk_cap_scaled_to_0"
                else:
                    k = "hard_trim_or_refill_dropped"
            cats[k] += 1
            by_cat_code[k][code] += 1

    slots_hist = Counter(int(e.get("slots_left")) for e in clog)
    held_hist = Counter(len(e.get("held") or {}) for e in clog)
    curve_held = Counter(int(r.get("held") or 0) for r in out["equity_curve"])
    slots_zero_days = sum(1 for d in dates if d >= start) - len(caps_first)
    cand_days_with_signal = sum(1 for e in clog if e.get("cands") or e.get("verdicts"))
    selected_entries = sum(len(v["selected"]) for v in caps_first.values())

    res = {
        "formal": {"ret_pct": out["ret_pct"], "closed_trades": out["closed_trades"], "max_dd_pct": out["max_dd_pct"],
                   "equity0": eq0, "risk_pct": risk_pct, "max_gross_pct": gross_pct, "stop_atr_mult": stop_mult,
                   "min_lots": p.get("min_lots", 0), "window": [start, bt["end"]], "trading_days": len([d for d in dates if d >= start]),
                   "snapshot": str(snap_path.relative_to(ROOT))},
        "a_per_symbol": per_code,
        "b_floor": {
            "ok_candidate_days": len(ok_rows),
            "ok_with_risk_per_lot_gt_day_risk": len(ok_viol),
            "lots0_candidate_days": len(lots0_rows),
            "lots0_with_risk_per_lot_le_day_risk": len(lots0_not_over),
            "lots0_selected_by_caps_or_topup": len(lots0_selected),
            "topup_counters_in_result": topup,
        },
        "c_skips_base": {
            "unit": "signal-days (a signal that persists several days is counted once per day)",
            "categories": dict(cats),
            "by_code": {k: dict(v.most_common()) for k, v in by_cat_code.items()},
            "replication_checks": {"bucket_skipped_matches_engine_meta": True, "bucket_n": check_bucket, "ncap_n": check_drop},
            "days_with_candidates_evaluated(slots_left>0)": len(caps_first),
            "days_positions_full_signals_not_evaluated": slots_zero_days,
            "slots_left_hist_on_candidate_days": dict(sorted(slots_hist.items())),
            "held_count_hist_on_candidate_days": dict(sorted(held_hist.items())),
            "clog_entries": len(clog),
            "curve_held_hist": dict(sorted(curve_held.items())),
            "selected_entries_total": selected_entries,
            "closed_trades": out["closed_trades"],
        },
        "equity_curve_row_keys": sorted((out["equity_curve"][0] or {}).keys()),
    }
    (ROOT / "archive" / "R8" / "static_sizing.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("formal", "b_floor", "c_skips_base", "equity_curve_row_keys")},
                     ensure_ascii=False, indent=1))
    for c, v in per_code.items():
        print(c, v["bucket"], "n1_med%200k", v["notional_pct_of_200k"]["median"], "r1_med%200k", v["risk_pct_of_200k"]["median"],
              "minEq med/max", v["min_equity_yuan"]["median"], v["min_equity_yuan"]["max"], v["binding_on_median_day"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
