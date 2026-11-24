# -*- coding: utf-8 -*-
"""R6b-fix vs R6c: comparison table, roll-day signal differences (Top10), per-trade changes.

Inputs : archive/R6/replay_after_R6b_fix.json (R6b-fix, raw signals)
         archive/R6/_replay_R6bfix_rawsignals.json (same engine, adjusted_signals=False; carries
         signal_candidates for the R6b-fix column)
         archive/R6/replay_after_R6c.json, audit_after_R6c.json
Output : archive/R6/R6bfix_vs_R6c.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab/shadow"))
import historical_backtest as hb  # noqa: E402
import replay as R  # noqa: E402
from research.data_quality.adjusted import build_adjusted_pack  # noqa: E402
from research.data_quality.main_map import build_main_map, contract_bars_by_date  # noqa: E402

SNAP = ROOT / "archive/snapshots/bt_input_20261123_da9c8de64ab4.json"
rf = json.loads((ROOT / "archive/R6/replay_after_R6b_fix.json").read_text(encoding="utf-8"))
rf_raw = json.loads((ROOT / "archive/R6/_replay_R6bfix_rawsignals.json").read_text(encoding="utf-8"))
rc = json.loads((ROOT / "archive/R6/replay_after_R6c.json").read_text(encoding="utf-8"))
audit = json.loads((ROOT / "archive/R6/audit_after_R6c.json").read_text(encoding="utf-8"))
snap = json.loads(SNAP.read_text(encoding="utf-8"))
_p, pack = R.make_pack(snap_obj=snap)
series = pack[0]
mm = build_main_map(series, root=ROOT, start=None)
adj = build_adjusted_pack(series, mm, root=ROOT)
start = rc["start"]

# the raw-signal engine re-run must reproduce the committed R6b-fix numbers
assert (rf_raw["ret_pct"], rf_raw["max_dd_pct"], rf_raw["closed_trades"]) == (
    rf["ret_pct"], rf["max_dd_pct"], rf["closed_trades"]
), "adjusted_signals=False no longer reproduces R6b-fix"

keys = ["ret_pct", "gross_ret_pct", "max_dd_pct", "closed_trades", "exits", "cost_yuan"]
table = {
    "R6b_fix": {k: rf.get(k) for k in keys},
    "R6c": {k: rc.get(k) for k in keys},
}
table["R6b_fix"]["signal_candidates"] = rf_raw["signal_candidates"]
table["R6c"]["signal_candidates"] = rc["signal_candidates"]
table["R6b_fix"]["adj_fallback_days"] = None
table["R6c"]["adj_fallback_days"] = rc["adj_fallback_days"]
table["R6c"]["adj_fallback_days_in_window"] = rc["adj_fallback_days_in_window"]
table["R6b_fix"]["gap_through_target_conservative"] = None
table["R6c"]["gap_through_target_conservative"] = audit["gap_through_target_conservative"]
table["R6b_fix"]["audit_mismatches"] = 1
table["R6c"]["audit_mismatches"] = audit["mismatches"]
for name, bt in (("R6b_fix", rf), ("R6c", rc)):
    for k in ("roll_shifted", "roll_unpriced_cont", "roll_unpriced", "held_contract_missing"):
        table[name][k] = bt.get(k)
table["R6c"]["adj_roll_days_in_window_total"] = sum((rc.get("adj_roll_days_in_window") or {}).values())
table["R6c"]["adj_roll_days_total"] = sum((rc.get("adj_roll_days") or {}).values())


def raw_ret(hist, i, n):
    return hb.ret_n(hist, i, n)


def sig_at(code, i):
    hist = series[code]["hist"]
    a = adj[code]
    return {
        "date": hist[i]["date"],
        "raw": {"r20": raw_ret(hist, i, 20), "r60": raw_ret(hist, i, 60), "atr": hb.atr14(hist, i)},
        "adj": {"r20": a.ret_n(i, 20), "r60": a.ret_n(i, 60), "atr": a.atr14(i)},
    }


def diff(x, y):
    return None if x is None or y is None else y - x


# ---- roll-day differences over the whole history (incl. warmup) -------------------------
rows = []
n_rolls = 0
for code, a in sorted(adj.items()):
    hist = series[code]["hist"]
    for i in range(len(hist)):
        if not a.roll[i]:
            continue
        n_rolls += 1
        s = sig_at(code, i)
        d20 = diff(s["raw"]["r20"], s["adj"]["r20"])
        d60 = diff(s["raw"]["r60"], s["adj"]["r60"])
        datr = diff(s["raw"]["atr"], s["adj"]["atr"])
        mags = [abs(x) for x in (d20, d60) if x is not None]
        rows.append(
            {
                "code": code,
                "date": s["date"],
                "idx": i,
                "from": mm.main(code, hist[i - 1]["date"]),
                "to": mm.main(code, s["date"]),
                "in_trade_window": s["date"] >= start,
                "raw_r20": s["raw"]["r20"],
                "adj_r20": s["adj"]["r20"],
                "d_r20": d20,
                "raw_r60": s["raw"]["r60"],
                "adj_r60": s["adj"]["r60"],
                "d_r60": d60,
                "raw_atr": s["raw"]["atr"],
                "adj_atr": s["adj"]["atr"],
                "d_atr": datr,
                "max_abs_d": max(mags) if mags else None,
                "sign_flip_r20": (
                    s["raw"]["r20"] is not None
                    and s["adj"]["r20"] is not None
                    and (s["raw"]["r20"] > 0) != (s["adj"]["r20"] > 0)
                ),
                "sign_flip_r60": (
                    s["raw"]["r60"] is not None
                    and s["adj"]["r60"] is not None
                    and (s["raw"]["r60"] > 0) != (s["adj"]["r60"] > 0)
                ),
            }
        )
scored = [r for r in rows if r["max_abs_d"] is not None]
scored.sort(key=lambda r: -r["max_abs_d"])
roll_summary = {
    "roll_days_total": n_rolls,
    "roll_days_with_r20": sum(1 for r in rows if r["raw_r20"] is not None),
    "roll_days_with_r60": sum(1 for r in rows if r["raw_r60"] is not None),
    "roll_days_in_trade_window": sum(1 for r in rows if r["in_trade_window"]),
    "sign_flips_r20": sum(1 for r in rows if r["sign_flip_r20"]),
    "sign_flips_r60": sum(1 for r in rows if r["sign_flip_r60"]),
    "top10_by_max_abs_diff_r20_r60": scored[:10],
}


def key(t):
    return (t["code"], t["direction"], t["entry_date"])


def prev_idx(code, day):
    hist = series[code]["hist"]
    ds = [b["date"] for b in hist]
    j = max(k for k, d in enumerate(ds) if d < day) if any(d < day for d in ds) else None
    return j


def idx_of(code, day):
    for k, b in enumerate(series[code]["hist"]):
        if b["date"] == day:
            return k
    return None


def gate(s):
    """Entry gate on a signal dict ('raw'/'adj'): direction or None."""
    out = {}
    for tag in ("raw", "adj"):
        r20, r60 = s[tag]["r20"], s[tag]["r60"]
        if r20 is None or r60 is None or abs(r20) < rc["min_r20_pct"] or abs(r60) < rc["min_r60_pct"]:
            out[tag] = None
        elif r20 > 0 and r60 > 0:
            out[tag] = "多"
        elif r20 < 0 and r60 < 0:
            out[tag] = "空"
        else:
            out[tag] = None
    return out


def brief(t):
    if t is None:
        return None
    return {
        k: t.get(k)
        for k in (
            "lots", "entry_date", "date", "entry", "exit", "stop", "target", "reason", "R",
            "fill_price_basis", "fill_contract", "held_contract", "roll_events",
        )
        if t.get(k) is not None
    }


def contract_klines(code, contract, d0, d1):
    by = contract_bars_by_date(contract, ROOT)
    out = []
    for b in series[code]["hist"]:
        d = b["date"]
        if d0 <= d <= d1:
            cb = by.get(d)
            if (
                b.get("contract_close") is not None
                and str(b.get("contract") or "").upper() == contract
            ):
                o = b.get("contract_open", b["contract_close"])
                out.append({"date": d, "open": o, "high": b["contract_high"], "low": b["contract_low"], "close": b["contract_close"], "main": mm.main(code, d)})
            elif cb:
                out.append({"date": d, "open": cb["open"], "high": cb["high"], "low": cb["low"], "close": cb["close"], "main": mm.main(code, d)})
            else:
                out.append({"date": d, "main": mm.main(code, d), "cont_close": b["close"]})
    return out


def equity_before(bt, day):
    prev = None
    for c in bt["equity_curve"]:
        if c["date"] >= day:
            break
        prev = c["equity"]
    return prev


mf = {key(t): t for t in rf["closed_pnls"]}
mc = {key(t): t for t in rc["closed_pnls"]}
changes = []
for k in sorted(set(mf) | set(mc), key=lambda x: (x[2], x[0])):
    a, b = mf.get(k), mc.get(k)
    sa = None if a is None else (a["date"], a["exit"], a["reason"], a["R"], a["lots"], a["stop"], a["target"])
    sb = None if b is None else (b["date"], b["exit"], b["reason"], b["R"], b["lots"], b["stop"], b["target"])
    if sa == sb:
        continue
    code = k[0]
    ent = k[2]
    si = prev_idx(code, ent)
    entry_sig = sig_at(code, si) if si is not None else None
    ent_gate = gate(entry_sig) if entry_sig else None
    rec = {
        "trade": {"code": code, "direction": k[1], "entry_date": ent},
        "R6b_fix": brief(a),
        "R6c": brief(b),
        "equity_before_entry": {"R6b_fix": equity_before(rf, ent), "R6c": equity_before(rc, ent)},
        "entry_signal": entry_sig,
        "entry_gate": ent_gate,
    }
    exit_sig = {}
    for tag, tr in (("R6b_fix", a), ("R6c", b)):
        if tr and tr.get("reason") == "signal":
            ei = idx_of(code, tr["date"])
            exit_sig[tag] = sig_at(code, ei)
    rec["signal_exit_context"] = exit_sig or None
    # classification
    if a and b:
        why = []
        cats = []
        atr_changed = bool(
            entry_sig
            and entry_sig["raw"]["atr"] is not None
            and abs(entry_sig["raw"]["atr"] - entry_sig["adj"]["atr"]) > 1e-6
        )
        if atr_changed:
            cats.append("atr")
            why.append(
                "signal-day ATR differs (raw %.2f vs same-contract %.2f) -> stop/target distance"
                % (entry_sig["raw"]["atr"], entry_sig["adj"]["atr"])
            )
        if a["lots"] != b["lots"]:
            cats.append("lots")
            why.append(
                "lots %s -> %s (%s)"
                % (a["lots"], b["lots"], "ATR change" if atr_changed else "sizing equity path; ATR identical")
            )
        if a["date"] != b["date"] or a["reason"] != b["reason"]:
            if "signal" in (a["reason"], b["reason"]):
                cats.append("signal_exit")
                why.append(
                    "exit path differs: %s %s -> %s %s (signal exit decided on raw vs roll-free r20/r60)"
                    % (a["date"], a["reason"], b["date"], b["reason"])
                )
            else:
                cats.append("exit_level_shift")
                why.append(
                    "exit day/reason differs: %s %s -> %s %s (stop/target levels moved with ATR)"
                    % (a["date"], a["reason"], b["date"], b["reason"])
                )
        elif a["exit"] != b["exit"]:
            cats.append("exit_price_level")
            why.append("same exit day/reason, exit level differs only via ATR distance")
        rec["kind"] = "same_position_different_outcome"
        rec["categories"] = cats
        rec["why_auto"] = why
    else:
        side = "R6c_only" if b else "R6b_fix_only"
        direct = ent_gate and (ent_gate["raw"] != ent_gate["adj"])
        rec["kind"] = side
        rec["categories"] = ["entry_gate" if direct else "path_effect"]
        rec["why_auto"] = [
            "entry gate differs raw vs adjusted at the signal day (direct signal effect)"
            if direct
            else "gate identical raw vs adjusted at the signal day -> path effect (equity / slots / caps from earlier changes)"
        ]
    # real-contract K-lines of the held contract (entry -> later exit)
    kl = {}
    for tag, tr in (("R6b_fix", a), ("R6c", b)):
        if tr:
            c_ = (
                tr.get("fill_contract")
                if tr.get("fill_price_basis") == "contract"
                else (tr.get("held_contract") or (tr.get("roll_events") or [{}])[0].get("from") or tr.get("fill_contract"))
            )
            if c_:
                kl[tag] = {"contract": c_, "klines": contract_klines(code, c_, ent, tr["date"])}
    rec["klines"] = kl
    changes.append(rec)

# trades that were only affected because of a roll inside their signal windows
out = {
    "table": table,
    "roll_day_signal_differences": roll_summary,
    "roll_day_signal_differences_all": rows,
    "changed_trades_R6bfix_to_R6c": changes,
    "audit": {
        "checked": audit["checked"],
        "mismatches": audit["mismatches"],
        "gap_through_target_conservative": audit["gap_through_target_conservative"],
        "gap_through_target_conservative_trades": audit["gap_through_target_conservative_trades"],
        "checks": audit["checks"],
    },
}
(ROOT / "archive/R6/R6bfix_vs_R6c.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(table, ensure_ascii=False, indent=1))
print({k: v for k, v in roll_summary.items() if k != "top10_by_max_abs_diff_r20_r60"})
for r in roll_summary["top10_by_max_abs_diff_r20_r60"]:
    print(
        r["code"], r["date"], r["from"], ">", r["to"],
        "r20 %.2f→%.2f (Δ%.2f)" % (r["raw_r20"], r["adj_r20"], r["d_r20"]) if r["raw_r20"] is not None else "r20 n/a",
        "r60 %.2f→%.2f (Δ%.2f)" % (r["raw_r60"], r["adj_r60"], r["d_r60"]) if r["raw_r60"] is not None else "r60 n/a",
        "atr %.2f→%.2f" % (r["raw_atr"], r["adj_atr"]) if r["raw_atr"] is not None else "",
        "win" if r["in_trade_window"] else "warmup",
    )
from collections import Counter  # noqa: E402

print("changes", len(changes), Counter(c["kind"] for c in changes))
print(Counter(cat for c in changes for cat in c["categories"]))
print("--- direct signal effects (entry gate / signal exit) ---")
for c in changes:
    t = c["trade"]
    if "entry_gate" in c["categories"] or "signal_exit" in c["categories"]:
        s = c["entry_signal"]
        print(t["code"], t["direction"], t["entry_date"], c["kind"], c["categories"])
        print("    entry sig", s["date"], "raw r20/r60", s["raw"]["r20"], s["raw"]["r60"], "adj", s["adj"]["r20"], s["adj"]["r60"], "gate", c["entry_gate"])
        for tag in ("R6b_fix", "R6c"):
            b = c[tag]
            print("   ", tag, None if not b else {x: b.get(x) for x in ("lots", "date", "exit", "reason", "R")})
        if c["signal_exit_context"]:
            for tag, v in c["signal_exit_context"].items():
                print("    exit sig", tag, v)
