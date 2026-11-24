# -*- coding: utf-8 -*-
"""R6c / R4 / R4b comparison (read-only) + per-trade R4 -> R4b changes.

Output: archive/R4/R4_vs_R4b.json
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

LD = lambda p: json.loads((ROOT / p).read_text(encoding="utf-8"))  # noqa: E731
rc, r4, rb = LD("archive/R6/replay_after_R6c.json"), LD("archive/R4/replay_after_R4.json"), LD("archive/R4/replay_after_R4b.json")
audit_b = LD("archive/R4/audit_after_R4b.json")
pre = LD("archive/R4/prefix_R6c_caps.json")
snap = LD("archive/snapshots/bt_input_20261123_da9c8de64ab4.json")
_p, pack = R.make_pack(snap_obj=snap)
series = pack[0]
mult = {c: float(s["meta"]["mult"]) for c, s in series.items()}
days = [c["date"] for c in rb["equity_curve"]]


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


def stats(bt):
    g = [c["gross_pct"] for c in bt["equity_curve"] if c.get("gross_pct") is not None]
    risk = [
        abs(t["lots"]) * abs(t["entry"] - t["stop"]) * mult[t["code"]] / equity_before(bt, t["entry_date"]) * 100
        for t in bt["closed_pnls"]
    ]
    return {
        "ret_pct": bt["ret_pct"],
        "gross_ret_pct": bt["gross_ret_pct"],
        "max_dd_pct": bt["max_dd_pct"],
        "closed_trades": bt["closed_trades"],
        "exits": bt["exits"],
        "cost_yuan": bt["cost_yuan"],
        "gross_pct_median": round(st.median(g), 2),
        "gross_pct_max": round(max(g), 2),
        "avg_held": bt.get("avg_held"),
        "median_trade_risk_pct": round(st.median(risk), 3),
        "caps_drift_days_gt55": sum(1 for x in g if x > 55),
    }


t6, t4, tb = stats(rc), stats(r4), stats(rb)
t6.update(caps_entry_gross_max=pre["max_gross_pct_sizing_eq"], caps_entry_risk_max=pre["max_atr_risk_pct"],
          caps_scaled_n=None, caps_topup_lots=None, caps_topup_revived=None)
for t, bt in ((t4, r4), (tb, rb)):
    t.update(
        caps_entry_gross_max=bt["caps_entry_gross_max"],
        caps_entry_risk_max=bt["caps_entry_risk_max"],
        caps_scaled_n=bt["caps_scaled_n"],
        caps_topup_lots=bt.get("caps_topup_lots"),
        caps_topup_revived=bt.get("caps_topup_revived"),
        caps_drift_days_gt55=bt["caps_drift_days_gt55"],
    )
table = {"R6c": t6, "R4": t4, "R4b": tb, "audit_mismatches_R4b": audit_b["mismatches"], "audit_checked_R4b": audit_b["checked"]}


def pnl(t):
    return None if t is None else round((t["exit"] - t["entry"]) * (1 if t["direction"] == "多" else -1) * t["lots"] * mult[t["code"]], 2)


def brief(t):
    if t is None:
        return None
    return {k: t.get(k) for k in ("lots", "entry", "exit", "date", "reason", "R", "stop", "target") if t.get(k) is not None}


m4 = {key(t): t for t in r4["closed_pnls"]}
mb = {key(t): t for t in rb["closed_pnls"]}
logb = {e["date"]: e for e in rb["caps_entry_log"]}
log4 = {e["date"]: e for e in r4["caps_entry_log"]}
m6 = {key(t): t for t in rc["closed_pnls"]}
changes = []
for k in sorted(set(m4) | set(mb), key=lambda x: (x[2], x[0])):
    a, b = m4.get(k), mb.get(k)
    sa = None if a is None else (a["lots"], a["date"], a["exit"], a["reason"])
    sb = None if b is None else (b["lots"], b["date"], b["exit"], b["reason"])
    if sa == sb:
        continue
    sd = sig_day(k[2])
    if a and b and a["lots"] != b["lots"] and a["entry"] == b["entry"]:
        kind = "lots_changed"
    elif b and not a:
        kind = "added"
    elif a and not b:
        kind = "removed"
    else:
        kind = "other"
    changes.append(
        {
            "trade": {"code": k[0], "direction": k[1], "entry_date": k[2], "signal_day": sd},
            "kind": kind,
            "in_R6c": k in m6,
            "R4": brief(a),
            "R4b": brief(b),
            "pnl_yuan": {"R4": pnl(a), "R4b": pnl(b)},
            "R4_entry_log": log4.get(sd),
            "R4b_entry_log": logb.get(sd),
        }
    )
kinds = Counter(c["kind"] for c in changes)
out = {"table": table, "changes_R4_to_R4b": changes, "change_kinds": dict(kinds)}
(ROOT / "archive/R4/R4_vs_R4b.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

for name in ("R6c", "R4", "R4b"):
    print(name, json.dumps(table[name], ensure_ascii=False))
print("audit", audit_b["checked"], audit_b["mismatches"], "kinds", dict(kinds), "trades R4/R4b", len(m4), len(mb))
tot_a = tot_b = 0.0
for c in changes:
    t = c["trade"]
    tot_a += c["pnl_yuan"]["R4"] or 0
    tot_b += c["pnl_yuan"]["R4b"] or 0
    print(t["entry_date"], t["code"], t["direction"], c["kind"], "R6c" if c["in_R6c"] else "-",
          c["R4"] and (c["R4"]["lots"], c["R4"]["reason"], c["R4"].get("R")), "->",
          c["R4b"] and (c["R4b"]["lots"], c["R4b"]["reason"], c["R4b"].get("R")), "pnl", c["pnl_yuan"])
print("sum pnl of changed trades R4 / R4b", round(tot_a, 2), round(tot_b, 2))
