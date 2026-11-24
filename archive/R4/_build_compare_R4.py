# -*- coding: utf-8 -*-
"""R6c vs R4 comparison (read-only): table, per-trade changes, pre-fix over-limit days.

Inputs : archive/R6/replay_after_R6c.json, archive/R4/replay_after_R4.json,
         archive/R4/audit_after_R4.json, archive/R4/prefix_R6c_caps.json, frozen snapshot (mult/bucket)
Output : archive/R4/R6c_vs_R4.json
"""
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab/shadow"))
import replay as R  # noqa: E402

rc = json.loads((ROOT / "archive/R6/replay_after_R6c.json").read_text(encoding="utf-8"))
r4 = json.loads((ROOT / "archive/R4/replay_after_R4.json").read_text(encoding="utf-8"))
audit = json.loads((ROOT / "archive/R4/audit_after_R4.json").read_text(encoding="utf-8"))
pre = json.loads((ROOT / "archive/R4/prefix_R6c_caps.json").read_text(encoding="utf-8"))
snap = json.loads((ROOT / "archive/snapshots/bt_input_20261123_da9c8de64ab4.json").read_text(encoding="utf-8"))
_p, pack = R.make_pack(snap_obj=snap)
series = pack[0]
mult = {c: float(s["meta"]["mult"]) for c, s in series.items()}
bucket = {c: s["meta"].get("bucket") for c, s in series.items()}
days = [c["date"] for c in rc["equity_curve"]]


def sig_day(entry_date):
    prev = [d for d in days if d < entry_date]
    return prev[-1] if prev else days[0]


def equity_before(bt, day):
    prev = bt["equity_start"]
    for c in bt["equity_curve"]:
        if c["date"] >= day:
            break
        prev = c["equity"]
    return prev


def key(t):
    return (t["code"], t["direction"], t["entry_date"])


def trade_risk_pct(bt, t):
    eq = equity_before(bt, t["entry_date"])
    return abs(t["lots"]) * abs(t["entry"] - t["stop"]) * mult[t["code"]] / eq * 100.0


def curve_stats(bt):
    g = [c["gross_pct"] for c in bt["equity_curve"] if c.get("gross_pct") is not None]
    return {
        "gross_pct_median": round(st.median(g), 2),
        "gross_pct_max": round(max(g), 2),
        "gross_pct_days_gt50": sum(1 for x in g if x > 50),
        "gross_pct_days_gt55": sum(1 for x in g if x > 55),
        "avg_held": bt.get("avg_held"),
        "median_trade_risk_pct": round(st.median(trade_risk_pct(bt, t) for t in bt["closed_pnls"]), 3),
    }


keys = ["ret_pct", "gross_ret_pct", "max_dd_pct", "closed_trades", "exits", "cost_yuan"]
t6 = {k: rc.get(k) for k in keys}
t4 = {k: r4.get(k) for k in keys}
t6.update(curve_stats(rc))
t4.update(curve_stats(r4))
t6.update(
    caps_entry_gross_max=pre["max_gross_pct_sizing_eq"],
    caps_entry_risk_max=pre["max_atr_risk_pct"],
    caps_scaled_n=None,
    caps_drift_days_gt55=t6["gross_pct_days_gt55"],
    entry_days_gross_gt50=pre["days_gross_gt50_sizing_eq"],
    entry_days_risk_gt8=pre["days_risk_gt8"],
)
t4.update(
    caps_entry_gross_max=r4["caps_entry_gross_max"],
    caps_entry_risk_max=r4["caps_entry_risk_max"],
    caps_scaled_n=r4["caps_scaled_n"],
    caps_drift_days_gt55=r4["caps_drift_days_gt55"],
    entry_days_gross_gt50=sum(1 for e in r4["caps_entry_log"] if e["gross_pct"] > 50),
    entry_days_risk_gt8=sum(1 for e in r4["caps_entry_log"] if e["risk_pct"] > 8),
)
table = {"R6c": t6, "R4": t4, "audit_mismatches_R4": audit["mismatches"], "audit_checked_R4": audit["checked"]}

# ---- per-trade changes ----------------------------------------------------------------
m6 = {key(t): t for t in rc["closed_pnls"]}
m4 = {key(t): t for t in r4["closed_pnls"]}
pre_by_sig = {r["date"]: r for r in pre["rows"]}
log4 = {e["date"]: e for e in r4["caps_entry_log"]}


def brief(t):
    if t is None:
        return None
    return {k: t.get(k) for k in ("lots", "entry", "exit", "date", "reason", "R", "stop", "target") if t.get(k) is not None}


def pnl(t):
    return None if t is None else round((t["exit"] - t["entry"]) * (1 if t["direction"] == "多" else -1) * t["lots"] * mult[t["code"]], 2)


changes = []
for k in sorted(set(m6) | set(m4), key=lambda x: (x[2], x[0])):
    a, b = m6.get(k), m4.get(k)
    sa = None if a is None else (a["lots"], a["date"], a["exit"], a["reason"])
    sb = None if b is None else (b["lots"], b["date"], b["exit"], b["reason"])
    if sa == sb:
        continue
    code, direction, ent = k
    sd = sig_day(ent)
    prow = pre_by_sig.get(sd)
    others = [p for p in (prow["positions"] if prow else []) if p["code"] != code]
    bucket_hit = [p["code"] for p in others if p["bucket"] == bucket[code]]
    rec = {
        "trade": {"code": code, "direction": direction, "entry_date": ent, "signal_day": sd, "bucket": bucket[code]},
        "R6c": brief(a),
        "R4": brief(b),
        "R6c_book_on_signal_day": None
        if not prow
        else {"held": prow["held_codes"], "gross_pct": prow["gross_pct_sizing_eq"], "risk_pct": prow["atr_risk_pct_sizing_eq"]},
        "R4_entry_log": log4.get(sd),
        "pnl_yuan": {"R6c": pnl(a), "R4": pnl(b)},
    }
    why = []
    if a and not b:
        rec["kind"] = "dropped"
        if prow and prow["gross_pct_sizing_eq"] > 50:
            why.append("R6c book on the signal day was %.1f%% gross (>50%%): the entry only fitted because the old call ignored held positions" % prow["gross_pct_sizing_eq"])
        if bucket_hit:
            why.append("bucket %s already occupied by %s in the book (max_per_bucket=1)" % (bucket[code], ",".join(bucket_hit)))
        if not why:
            why.append("not selected in R4: slot/quota used by earlier book changes (path effect)")
    elif b and not a:
        rec["kind"] = "new"
        why.append("path effect: earlier R4 sizing/drops changed the book, equity and free slots; entry gate itself unchanged")
    elif a["lots"] != b["lots"] and a["entry"] == b["entry"]:
        rec["kind"] = "scaled"
        why.append("lots %d -> %d to fit remaining gross/risk quota after the already-open book" % (a["lots"], b["lots"]))
        if a["date"] != b["date"] or a["reason"] != b["reason"]:
            why.append("exit path also differs (%s %s -> %s %s) because size changed equity/stop timing" % (a["date"], a["reason"], b["date"], b["reason"]))
    else:
        rec["kind"] = "other"
        why.append("same position, different outcome (entry/exit/lots): %s -> %s" % (sa, sb))
    rec["why"] = why
    changes.append(rec)

kinds = Counter(c["kind"] for c in changes)

# ---- pre-fix over-limit entry days and their R4 handling -----------------------------------
over = []
for r in pre["rows"]:
    if not r["gross_gt50"] and not r["risk_gt8"]:
        continue
    sd = r["date"]
    trades_that_day = [k for k in set(m6) | set(m4) if sig_day(k[2]) == sd]
    handled = []
    for k in sorted(trades_that_day):
        a, b = m6.get(k), m4.get(k)
        if a and b:
            how = "kept %d lots" % b["lots"] if a["lots"] == b["lots"] else "scaled %d -> %d lots" % (a["lots"], b["lots"])
        elif a:
            how = "dropped (R6c had %d lots)" % a["lots"]
        else:
            how = "new in R4 (%d lots)" % b["lots"]
        handled.append({"code": k[0], "direction": k[1], "entry_date": k[2], "how": how})
    over.append(
        {
            "signal_day": sd,
            "R6c_added": r["added"],
            "R6c_held": r["held_codes"],
            "R6c_gross_pct": r["gross_pct_sizing_eq"],
            "R6c_risk_pct": r["atr_risk_pct_sizing_eq"],
            "R4_entry_log": log4.get(sd),
            "R4_handling": handled,
        }
    )

out = {
    "table": table,
    "changes_R6c_to_R4": changes,
    "change_kinds": dict(kinds),
    "prefix_over_limit_days": over,
}
(ROOT / "archive/R4/R6c_vs_R4.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps(table, ensure_ascii=False, indent=1))
print("kinds", dict(kinds), "n_trades R6c/R4", len(m6), len(m4))
for c in changes:
    t = c["trade"]
    print(t["entry_date"], t["code"], t["direction"], c["kind"], c["R6c"] and (c["R6c"]["lots"], c["R6c"]["reason"], c["R6c"].get("R")), "->",
          c["R4"] and (c["R4"]["lots"], c["R4"]["reason"], c["R4"].get("R")), "| pnl", c["pnl_yuan"], "|", "; ".join(c["why"])[:150])
print("--- over-limit days ---")
for o in over:
    print(o["signal_day"], "R6c", o["R6c_held"], o["R6c_gross_pct"], "R4 log", o["R4_entry_log"], [(h["code"], h["how"]) for h in o["R4_handling"]])
