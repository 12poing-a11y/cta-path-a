# -*- coding: utf-8 -*-
"""R3 / R6ab / R6b-fix comparison, per-trade change list with real held-contract K-lines,
main_map coverage and trades spanning an actual main roll.  Output: archive/R6/R3_vs_R6ab_vs_R6bfix.json"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab/shadow"))
import replay as R  # noqa: E402
from research.data_quality.main_map import build_main_map, contract_bars_by_date  # noqa: E402

SNAP = ROOT / "archive/snapshots/bt_input_20261123_da9c8de64ab4.json"
r3 = json.loads((ROOT / "archive/R3/replay_after_R3.json").read_text(encoding="utf-8"))
r6 = json.loads((ROOT / "archive/R6/replay_after_R6ab.json").read_text(encoding="utf-8"))
rf = json.loads((ROOT / "archive/R6/replay_after_R6b_fix.json").read_text(encoding="utf-8"))
audit = json.loads((ROOT / "archive/R6/audit_after_R6b_fix.json").read_text(encoding="utf-8"))
snap = json.loads(SNAP.read_text(encoding="utf-8"))
_p, pack = R.make_pack(snap_obj=snap)
series = pack[0]
mm = build_main_map(series, root=ROOT, start=rf["start"])
mm_all = build_main_map(series, root=ROOT, start="2000-01-01")


def gap_stats(bt):
    out = []
    for t in bt.get("closed_pnls") or []:
        if str(t.get("reason")) != "stop":
            continue
        try:
            entry, stop, exit_px = float(t["entry"]), float(t["stop"]), float(t["exit"])
        except (KeyError, TypeError, ValueError):
            continue
        d = str(t.get("direction") or "")
        if (d == "多" and exit_px < stop - 1e-9) or (d == "空" and exit_px > stop + 1e-9):
            risk = abs(entry - stop) or 1e-9
            out.append(
                {
                    "code": t["code"],
                    "date": t["date"],
                    "R": t["R"],
                    "extra_R": abs(exit_px - stop) / risk,
                    "basis": t.get("fill_price_basis"),
                }
            )
    return out


keys = [
    "ret_pct", "gross_ret_pct", "max_dd_pct", "closed_trades", "exits", "cost_yuan",
    "roll_shifted", "roll_exit", "roll_unpriced_cont", "roll_unpriced", "held_contract_missing",
]
g3, g6, gf = gap_stats(r3), gap_stats(r6), gap_stats(rf)
table = {
    "R3": {k: r3.get(k) for k in keys},
    "R6ab": {k: r6.get(k) for k in keys},
    "R6b_fix": {k: rf.get(k) for k in keys},
}
for name, bt, g in (("R3", r3, g3), ("R6ab", r6, g6), ("R6b_fix", rf, gf)):
    table[name]["gap_stop_exits"] = len(g)
    table[name]["gap_slippage_R"] = round(sum(x["extra_R"] for x in g), 4)
table["R3"]["main_map_none_days"] = None
table["R6ab"]["main_map_none_days"] = None
table["R6b_fix"]["main_map_none_days"] = rf["main_map"]["none_days_total"]
table["R6b_fix"]["main_map_days"] = rf["main_map"]["days_total"]
table["R6b_fix"]["roll_held_bar_days"] = rf.get("roll_held_bar_days")
table["R6b_fix"]["roll_open_gap_stops"] = rf.get("roll_open_gap_stops")


def key(t):
    return (t["code"], t["direction"], t["entry_date"])


def contract_klines(code, contract, d0, d1):
    by = contract_bars_by_date(contract, ROOT)
    bars = snap["bars"].get(code) or []
    snap_by = {b["date"]: b for b in bars}
    rows = []
    for d in sorted(snap_by):
        if d < d0 or d > d1:
            continue
        b = by.get(d)
        sb = snap_by[d]
        if (
            sb.get("contract_close") is not None
            and str(sb.get("contract") or "").upper() == contract
        ):
            o, h, l, c = (
                sb.get("contract_open") if sb.get("contract_open") is not None else sb["contract_close"],
                sb["contract_high"],
                sb["contract_low"],
                sb["contract_close"],
            )
            src = "snap_contract"
        elif b:
            o, h, l, c, src = b["open"], b["high"], b["low"], b["close"], "cache_contract"
        else:
            o = h = l = c = None
            src = "missing"
        rows.append(
            {
                "date": d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "src": src,
                "main": mm_all.main(code, d),
                "cont_close": sb.get("close"),
            }
        )
    return rows


def entry_contract(t, bt_name):
    if t.get("fill_price_basis") == "contract" and t.get("fill_contract"):
        return t["fill_contract"]
    ev = t.get("roll_events") or []
    if ev and ev[0].get("from"):
        return ev[0]["from"]
    if t.get("held_contract"):
        return t["held_contract"]
    return mm_all.main(t["code"], t["entry_date"])


def brief(t):
    if t is None:
        return None
    return {
        k: t.get(k)
        for k in (
            "lots", "entry_date", "date", "entry", "exit", "stop", "target", "reason", "R",
            "fill_price_basis", "fill_contract", "held_contract", "roll_events", "entry_orig",
        )
        if t.get(k) is not None
    }


def equity_before(bt, day):
    prev = None
    for c in bt["equity_curve"]:
        if c["date"] >= day:
            break
        prev = c["equity"]
    return prev


m3 = {key(t): t for t in r3["closed_pnls"]}
mf = {key(t): t for t in rf["closed_pnls"]}
changes = []
for k in sorted(set(m3) | set(mf), key=lambda x: (x[2], x[0])):
    a, b = m3.get(k), mf.get(k)
    sa = None if a is None else (a["date"], a["exit"], a["reason"], a["R"], a["lots"])
    sb = None if b is None else (b["date"], b["exit"], b["reason"], b["R"], b["lots"])
    if sa == sb:
        continue
    t_any = b or a
    d_end = max((a or {}).get("date", ""), (b or {}).get("date", ""))
    ec3 = entry_contract(a, "R3") if a else None
    ecf = entry_contract(b, "R6bfix") if b else None
    kl = {}
    for tag, c_, tr in (("R3", ec3, a), ("R6b_fix", ecf, b)):
        if c_ and tr:
            kl[tag] = {
                "contract": c_,
                "klines": contract_klines(t_any["code"], c_, k[2], tr["date"]),
            }
    # roll legs after a shifted roll
    for tag, tr in (("R6b_fix", b),):
        if tr and tr.get("roll_events"):
            for ev in tr["roll_events"]:
                if ev.get("status") == "shifted":
                    kl.setdefault("R6b_fix_after_roll", []).append(
                        {
                            "contract": ev["to"],
                            "klines": contract_klines(t_any["code"], ev["to"], ev["date"], tr["date"]),
                        }
                    )
    kind = (
        "cascade_only_in_one_run"
        if (a is None or b is None)
        else "same_position_different_exit"
    )
    changes.append(
        {
            "trade": {"code": k[0], "direction": k[1], "entry_date": k[2]},
            "kind": kind,
            "R3": brief(a),
            "R6b_fix": brief(b),
            "equity_before_entry": {
                "R3": equity_before(r3, k[2]),
                "R6b_fix": equity_before(rf, k[2]),
            },
            "klines": kl,
        }
    )

# trades whose life spans an actual main roll (entry < roll day <= exit), any basis
spans = []
for tag, bt in (("R3", r3), ("R6b_fix", rf)):
    for t in bt["closed_pnls"]:
        code = t["code"]
        days = [b["date"] for b in snap["bars"][code] if t["entry_date"] <= b["date"] <= t["date"]]
        rolls_in = []
        prev = None
        for d in days:
            m = mm_all.main(code, d)
            if prev is not None and m is not None and m != prev and d > t["entry_date"]:
                rolls_in.append({"roll_day": d, "from": prev, "to": m})
            if m is not None:
                prev = m
        if rolls_in:
            spans.append(
                {
                    "run": tag,
                    "code": code,
                    "entry_date": t["entry_date"],
                    "exit_date": t["date"],
                    "basis": t.get("fill_price_basis"),
                    "reason": t["reason"],
                    "R": t["R"],
                    "rolls": rolls_in,
                    "roll_events": t.get("roll_events"),
                }
            )

mandatory = []
for code, ed in (("TA", "2026-01-12"), ("JD", "2026-06-11"), ("L", "2026-09-11"),
                 ("MA", "2026-10-12"), ("EG", "2026-09-22"), ("EG", "2026-09-18")):
    row = {"code": code, "date": ed, "runs": {}}
    for tag, bt in (("R3", r3), ("R6ab", r6), ("R6b_fix", rf)):
        row["runs"][tag] = [
            brief(t) | {"code": t["code"], "direction": t["direction"]}
            for t in bt["closed_pnls"]
            if t["code"] == code and (t["entry_date"] == ed or t["date"] == ed)
        ]
    ts = [t for t in rf["closed_pnls"] if t["code"] == code and (t["entry_date"] == ed or t["date"] == ed)]
    if ts:
        t = ts[0]
        c_ = entry_contract(t, "R6bfix")
        row["klines"] = {"contract": c_, "rows": contract_klines(code, c_, t["entry_date"], t["date"])}
    mandatory.append(row)

cov = {}
for c, s in sorted(mm.stats.items()):
    cov[c] = {
        "days": s["days"],
        "matched": s["matched"],
        "none_days": s["none_days"],
        "coverage": s["coverage"],
        "none_no_candidate_bar": s["none_no_candidate_bar"],
        "none_no_match_within_tick": s["none_no_match_within_tick"],
        "none_ambiguous": s["none_ambiguous"],
        "main_rolls_in_window": sum(
            1
            for a, b in zip(
                [v for d, v in sorted(mm_all.maps[c].items()) if d >= rf["start"] and v],
                [v for d, v in sorted(mm_all.maps[c].items()) if d >= rf["start"] and v][1:],
            )
            if a != b
        ),
        "contracts_available": s["candidates"],
    }

out = {
    "table": table,
    "mandatory_trades": mandatory,
    "changed_trades_vs_R3": changes,
    "trades_spanning_actual_main_roll": spans,
    "main_map_coverage": {
        "window": [rf["start"], rf["end"]],
        "overall": {
            "days": sum(v["days"] for v in cov.values()),
            "matched": sum(v["matched"] for v in cov.values()),
            "none_days": sum(v["none_days"] for v in cov.values()),
        },
        "by_code": cov,
    },
    "audit": {
        "checked": audit["checked"],
        "mismatches": audit["mismatches"],
        "mismatches_excluding_conservative_target_gap": audit.get(
            "mismatches_excluding_conservative_target_gap"
        ),
        "checks": audit.get("checks"),
        "mismatch_trades": audit["mismatch_trades"],
    },
}
(ROOT / "archive/R6/R3_vs_R6ab_vs_R6bfix.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(table, ensure_ascii=False, indent=1))
print("changed", len(changes), "spans", len(spans))
for s in spans:
    print(s["run"], s["code"], s["entry_date"], s["exit_date"], s["basis"], s["reason"], s["R"], s["rolls"], s["roll_events"])
