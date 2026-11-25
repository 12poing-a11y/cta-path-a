# -*- coding: utf-8 -*-
"""Post-hoc DESCRIPTIVE diagnostics for R8b (not part of any pass criterion; written after the results were known).
Explains where the F1 / F2 differences to the control come from: filter hits by code/half, and trade-set differences."""
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

R8 = Path(__file__).resolve().parent
ctrl = json.loads((R8 / "E1000k" / "result.json").read_text(encoding="utf-8"))
mult = {u["code"]: float(u.get("mult") or 1) for u in json.loads((R8.parents[1] / "universe.json").read_text(encoding="utf-8"))["symbols"]}
cdates = [x["date"] for x in ctrl["equity_curve"]]
h1 = set(cdates[: len(cdates) // 2])


def pnl(t):
    d = 1.0 if str(t["direction"]) in ("多", "long", "buy") else -1.0
    return d * (float(t["exit"]) - float(t["entry"])) * int(t["lots"]) * mult[t["code"]]


def keyed(r):
    return {(t["code"], t["entry_date"]): t for t in r["closed_pnls"]}


ck = keyed(ctrl)
out = {}
for g in ("F1", "F2", "F1F2"):
    r = json.loads((R8 / g / "result.json").read_text(encoding="utf-8"))
    log = r["entry_filters"]["log"]
    gk = keyed(r)
    gone = [ck[k] for k in ck if k not in gk]
    new = [gk[k] for k in gk if k not in ck]
    both = [k for k in gk if k in ck]
    # same entry key but different lots/exit (path changed sizing / exits)
    diff_both = [k for k in both if (gk[k]["lots"], gk[k]["exit"]) != (ck[k]["lots"], ck[k]["exit"])]
    by_half = Counter("H1" if x["date"] in h1 else "H2" for x in log)
    by_code = Counter(x["code"] for x in log)
    out[g] = {
        "hits_signal_days": len(log), "hits_by_half": dict(by_half), "hits_by_code_top": dict(by_code.most_common(8)),
        "control_trades": len(ck), "group_trades": len(gk), "common_entry_keys": len(both),
        "common_but_different_lots_or_exit": len(diff_both),
        "control_only": {"n": len(gone), "price_pnl": round(sum(pnl(t) for t in gone)), "codes": dict(Counter(t["code"] for t in gone))},
        "group_only": {"n": len(new), "price_pnl": round(sum(pnl(t) for t in new)), "codes": dict(Counter(t["code"] for t in new))},
        "price_pnl_total_control": round(sum(pnl(t) for t in ctrl["closed_pnls"])),
        "price_pnl_total_group": round(sum(pnl(t) for t in r["closed_pnls"])),
        "equity_end": r["equity_end"],
        "top5_group_only_pnl": sorted(((round(pnl(t)), t["code"], t["entry_date"]) for t in new), reverse=True)[:5],
        "bottom5_control_only_pnl": sorted(((round(pnl(t)), t["code"], t["entry_date"]) for t in gone))[:5],
    }
    if g != "F1":
        ratios = [x["atr14"] / x["atr100"] for x in log if x.get("atr100")]
        out[g]["hit_ratio_atr14_atr100"] = {"median": round(statistics.median(ratios), 3), "max": round(max(ratios), 3)}
        out[g]["atr_spike_unavailable_days"] = r["entry_filters"]["hits"]["atr_spike_unavailable"]
    if g == "F1":
        out[g]["hit_unit_notional_pct_of_cap"] = {
            "min": round(min(x["unit_notional"] / x["gross_cap_amount"] for x in log) * 100, 1),
            "max": round(max(x["unit_notional"] / x["gross_cap_amount"] for x in log) * 100, 1)}
print(json.dumps(out, ensure_ascii=False, indent=1))
(R8 / "f_diag.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
