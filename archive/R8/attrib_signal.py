# -*- coding: utf-8 -*-
"""R8 closeout appendix A.3: signal-layer diagnostic (read-only attribution; not a candidate; not in DSR).

Definitions are fixed in archive/R8/R8_CLOSEOUT.md appendix A.3/A.4 (committed before this ran).
Output: archive/R8/ATTRIB/signal_layer.json (+ events.json.gz of the raw independent trades)."""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE), str(ROOT / "lab" / "shadow")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import long_sample as ls  # noqa: E402

SEED, B_BOOT = 20261126, 10_000
RISK_PCT, EQ_B = 0.02, 1_000_000.0
BIG_EQUITY = 1e12  # only so that every signal sizes to > 0 lots; lots are overridden (1 lot) in the signal layer


def build_events(pack, main_map, store, meta, scen):
    """Run the signal layer once (cost-independent exits); returns per-event records with per-lot net pnl for Base and Stress."""
    p = ls._long_params("A", BIG_EQUITY, "base")
    p["max_positions"] = 10 ** 6  # slots never bind: every candidate is evaluated every day (exits are A's)
    r = ls.run_long("A", BIG_EQUITY, "base", pack, main_map, store, with_taps=False, p=p, mode="base",
                    ls_extra={"signal_layer": {}})
    out = r["out"]
    sl = out["long_sample"]["signal_layer"]
    events = sl["events"]
    closed = {(t["code"], t["entry_date"]): t for t in out["closed_pnls"]}
    openp = {(t["code"], t["entry_date"]): t for t in sl["open_at_end"]}
    last_close = {c: s["hist"][-1]["close"] for c, s in pack[0].items()}
    recs = []
    for e in events:
        if e["status"] != "filled":
            recs.append({**e, "kind": "unfilled"})
            continue
        key = (e["code"], e["entry_date"])
        t = closed.get(key)
        kind = "closed"
        if t is None:
            t = openp[key]
            kind = "open_at_end"
        m = meta[e["code"]]
        rec = {**e, "kind": kind, "exit_date": t.get("date"), "reason": t.get("reason"), "n_rolls": 0}
        for name, (slip, fm) in scen.items():
            if kind == "closed":
                n = ls.trade_net_pnl(t, m, slip, fm)
            else:  # mark to the last close, charge the exit fill as if closed there
                tt = dict(t, exit=last_close[e["code"]], lots=1)
                n = ls.trade_net_pnl(tt, m, slip, fm)
            rec[f"net1_{name}"] = n["net"]
            rec["n_rolls"] = n["n_rolls"]
        rpl = float(e["risk_per_lot"])
        rec["lots_b"] = int(math.floor(RISK_PCT * EQ_B / rpl)) if rpl > 0 else 0
        recs.append(rec)
    return recs, out, r


def classify(recs, a_runs, meta):
    """Attach the A1000k group (per cost scenario) to every event."""
    for name, (ares, atrades) in a_runs.items():
        ev_cat, clog_days = ares["ev_cat"], ares["clog_days"]
        cur = ares["out"]["equity_curve"]
        curve_codes = {x["date"]: set(x.get("codes") or []) for x in cur}
        prev_day = {cur[i]["date"]: cur[i - 1]["date"] for i in range(1, len(cur))}
        akeys = {(t["code"], t["entry_date"]) for t in atrades["closed"]} | {(c, p.get("entry_date")) for c, p in (ares["out"].get("final_positions") or {}).items()}
        for e in recs:
            d, code = e["day"], e["code"]
            if e["kind"] != "unfilled" and (code, e["entry_date"]) in akeys and ev_cat.get((d, code)) == "selected":
                g = "traded"
            elif ev_cat.get((d, code)) is not None:
                g = {"selected": "selected_unfilled", "positions_full": "positions_full_ranked"}.get(ev_cat[(d, code)], ev_cat[(d, code)])
            elif d not in clog_days:
                g = "positions_full_nofreeslot"
            elif code in curve_codes.get(d, ()) or code in curve_codes.get(prev_day.get(d), ()):
                g = "held_in_A"
            else:
                g = "other_unevaluated"
            e[f"grp_{name}"] = g
    return recs


def month_of(d):
    return d[:7]


def boot_mean(vals_by_month: dict, rng) -> dict:
    """monthly block bootstrap of the pooled mean.  vals_by_month: {month: (sum, n)}"""
    months = sorted(vals_by_month)
    s = np.array([vals_by_month[m][0] for m in months], float)
    n = np.array([vals_by_month[m][1] for m in months], float)
    if n.sum() == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    idx = rng.randint(0, len(months), size=(B_BOOT, len(months)))
    ss, nn = s[idx].sum(1), n[idx].sum(1)
    ok = nn > 0
    means = ss[ok] / nn[ok]
    return {"mean": float(s.sum() / n.sum()), "lo": float(np.percentile(means, 2.5)), "hi": float(np.percentile(means, 97.5)), "n": int(n.sum())}


def stats_for(rows, rkey, rng, *, yuan_key=None):
    byM = defaultdict(lambda: [0.0, 0])
    for e in rows:
        byM[month_of(e["day"])][0] += e[rkey]; byM[month_of(e["day"])][1] += 1
    b = boot_mean({k: tuple(v) for k, v in byM.items()}, rng)
    n = len(rows)
    b.update(win=(sum(1 for e in rows if e[rkey] > 0) / n) if n else None)
    if yuan_key:
        b["yuan_mean"] = (sum(e[yuan_key] for e in rows) / n) if n else None
        b["yuan_sum"] = sum(e[yuan_key] for e in rows)
    return b


def main() -> int:
    pack, main_map, store, info = ls.build_official_pack()
    meta = {c: s["meta"] for c, s in pack[0].items()}
    # A1000k reference runs (identical to the committed OOS results) with event categories
    a_runs, scen = {}, {}
    for name in ("base", "stress"):
        ares = ls.run_long("A", 1_000_000.0, name, pack, main_map, store)
        slim = ls.slim(ares, meta, 1_000_000.0)
        a_runs[name] = (ares, {"closed": slim["trades"], "slim": slim})
        scen[name] = (float(ares["out"]["slippage_ticks"]), float(ares["out"]["fee_mult"]))
    print("scen", scen, "A ret", {k: v[1]["slim"]["ret_pct"] for k, v in a_runs.items()}, flush=True)
    recs, sl_out, _ = build_events(pack, main_map, store, meta, scen)
    print("events", len(recs), Counter(e["kind"] for e in recs), flush=True)
    recs = classify(recs, a_runs, meta)

    # reconciliation of the 'traded' group against A's actual trades (per-lot net)
    recon = {}
    for name in ("base", "stress"):
        atr = {(t["code"], t["entry_date"]): t for t in a_runs[name][1]["closed"]}
        diffs = []
        for e in recs:
            if e.get(f"grp_{name}") == "traded" and e["kind"] == "closed":
                t = atr.get((e["code"], e["entry_date"]))
                if t is not None and t["lots"]:
                    diffs.append(abs(t["net"] / t["lots"] - e[f"net1_{name}"]))
        recon[name] = {"n": len(diffs), "max_abs_diff_yuan_per_lot": (max(diffs) if diffs else None), "n_over_1yuan": sum(1 for x in diffs if x > 1.0),
                       "a_trades": len(atr)}
    print("recon", recon, flush=True)

    rng = np.random.RandomState(SEED)
    result = {"info": {"events": len(recs), "kinds": dict(Counter(e["kind"] for e in recs)), "pack_sha256": info["pack_sha256"], "seed": SEED,
                       "bootstrap_draws": B_BOOT, "risk_pct_b": RISK_PCT, "equity_b": EQ_B}, "recon": recon, "scen": {}}
    for name in ("base", "stress"):
        evs = [e for e in recs if e["kind"] != "unfilled"]
        for e in evs:
            e["R_a"] = e[f"net1_{name}"] / float(e["risk_per_lot"]) if e["risk_per_lot"] > 0 else 0.0
            e["yuan_a"] = e[f"net1_{name}"]
            e["yuan_b"] = e[f"net1_{name}"] * e["lots_b"]
        bevs = [e for e in evs if e["lots_b"] >= 1]
        sc = {"n_events": len(recs), "n_unfilled": sum(1 for e in recs if e["kind"] == "unfilled"), "n_filled": len(evs),
              "n_open_at_end": sum(1 for e in evs if e["kind"] == "open_at_end"), "n_zero_lots_b": len(evs) - len(bevs)}
        for lab, rows, ykey in (("a", evs, "yuan_a"), ("b", bevs, "yuan_b")):
            blk = {"all": stats_for(rows, "R_a", rng, yuan_key=ykey)}
            gk = f"grp_{name}"
            groups = defaultdict(list)
            for e in rows:
                groups[e[gk]].append(e)
            blk["groups"] = {g: stats_for(v, "R_a", rng, yuan_key=ykey) for g, v in sorted(groups.items())}
            pf = groups.get("positions_full_ranked", []) + groups.get("positions_full_nofreeslot", [])
            blk["groups"]["positions_full_all"] = stats_for(pf, "R_a", rng, yuan_key=ykey)
            blk["by_year"] = {y: stats_for([e for e in rows if e["day"][:4] == y], "R_a", rng, yuan_key=ykey) for y in sorted({e["day"][:4] for e in rows})}
            blk["by_bucket"] = {b: stats_for([e for e in rows if e["bucket"] == b], "R_a", rng, yuan_key=ykey) for b in sorted({str(e["bucket"]) for e in rows})}
            blk["by_year_bucket"] = {f"{y}|{b}": {"n": sum(1 for e in rows if e["day"][:4] == y and e["bucket"] == b),
                                                  "mean_R": (lambda v: (sum(x["R_a"] for x in v) / len(v)) if v else None)([e for e in rows if e["day"][:4] == y and e["bucket"] == b])}
                                     for y in sorted({e["day"][:4] for e in rows}) for b in sorted({str(e["bucket"]) for e in rows})}
            # 'strongest-in-bucket': same (signal day, bucket) cells holding both an A-traded event and a bucket_full loser
            cells = defaultdict(lambda: {"sel": [], "los": []})
            for e in rows:
                if e[gk] == "traded":
                    cells[(e["day"], e["bucket"])]["sel"].append(e["R_a"])
                elif e[gk] == "bucket_full":
                    cells[(e["day"], e["bucket"])]["los"].append(e["R_a"])
            both = {k: v for k, v in cells.items() if v["sel"] and v["los"]}
            byM = defaultdict(lambda: [0.0, 0, 0.0, 0])
            for (d, b), v in both.items():
                m = byM[month_of(d)]
                m[0] += sum(v["sel"]); m[1] += len(v["sel"]); m[2] += sum(v["los"]); m[3] += len(v["los"])
            months = sorted(byM)
            arr = np.array([byM[m] for m in months], float)
            if len(months):
                idx = rng.randint(0, len(months), size=(B_BOOT, len(months)))
                S = arr[idx]
                ssel, nsel, slos, nlos = S[:, :, 0].sum(1), S[:, :, 1].sum(1), S[:, :, 2].sum(1), S[:, :, 3].sum(1)
                ok = (nsel > 0) & (nlos > 0)
                diffs = ssel[ok] / nsel[ok] - slos[ok] / nlos[ok]
                msel, mlos = arr[:, 0].sum() / arr[:, 1].sum(), arr[:, 2].sum() / arr[:, 3].sum()
                blk["strongest_in_bucket"] = {"cells": len(both), "n_selected": int(arr[:, 1].sum()), "n_losers": int(arr[:, 3].sum()), "mean_R_selected": float(msel),
                                              "mean_R_losers": float(mlos), "diff_selected_minus_losers": float(msel - mlos),
                                              "lo": float(np.percentile(diffs, 2.5)), "hi": float(np.percentile(diffs, 97.5))}
            else:
                blk["strongest_in_bucket"] = None
            sc[lab] = blk
        result["scen"][name] = sc
    # ---- A.4 decision (Stress, (b), all signals) ------------------------------------------------------------------
    st = result["scen"]["stress"]["b"]
    allb, traded = st["all"], st["groups"].get("traded")
    if allb["mean"] <= 0:
        verdict = "信号无优势"
    elif allb["lo"] > 0:
        verdict = "信号有优势"
    else:
        verdict = "不确定"
    sib = st["strongest_in_bucket"]
    result["decision"] = {"verdict": verdict, "all_signals_mean_R": allb["mean"], "ci": [allb["lo"], allb["hi"]], "n": allb["n"],
                          "traded_mean_R": traded["mean"] if traded else None,
                          "traded_lt_all": (traded["mean"] < allb["mean"]) if traded else None,
                          "strongest_selected_lt_losers_ci_excludes_0": bool(sib and sib["diff_selected_minus_losers"] < 0 and sib["hi"] < 0),
                          "strongest_in_bucket": sib}
    (HERE / "ATTRIB").mkdir(exist_ok=True)
    (HERE / "ATTRIB" / "signal_layer.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    keep = [{k: e.get(k) for k in ("day", "code", "direction", "bucket", "kind", "entry_date", "exit_date", "reason", "n_rolls", "risk_per_lot", "lots_b",
                                    "net1_base", "net1_stress", "grp_base", "grp_stress")} for e in recs]
    with gzip.open(HERE / "ATTRIB" / "signal_events.json.gz", "wt", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, default=str)
    print(json.dumps(result["decision"], ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
