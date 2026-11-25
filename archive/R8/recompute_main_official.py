# -*- coding: utf-8 -*-
"""R8 follow-up (read-only, no strategy run).

Part A  engine main-contract rule recomputed on the OFFICIAL per-contract data, literal standard:
        every trading day must be identifiable.  Unidentified days -> carry previous main (no roll).
        Lists dates x symbols, diagnoses each unidentified day, explains the shared dates.
Part B  does the roll rule depend on volume/OI?  (static: the rule is price-only.)  Empirically: build the
        main map on the 2024-09..2025-12 overlap from official vs from local per-contract bars and compare
        the main on every day and every roll day.
Writes archive/R8/main_official_resolved.json and archive/R8/main_official_vs_local.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import CODE_EX, load_all  # noqa: E402
from research.data_quality.calendar import listed_contracts_on  # noqa: E402
from research.data_quality.contract_store import BundleContractStore, CacheContractStore  # noqa: E402
from research.data_quality.main_map import build_main_map  # noqa: E402

W0, W1 = "2016-01-04", "2025-12-31"
FU_START = "2018-10-16"
XV0 = "2024-09-01"
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
probe = json.loads((ROOT / "archive" / "R8" / "long_coverage_probe.json").read_text(encoding="utf-8"))["rows"]
by = load_all()
quote_days = sorted({d for v in by.values() for d in v})
qd = set(quote_days)


def traded(r):
    return all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))


bundle = {c: [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(rows.items()) if traded(r)] for c, rows in by.items()}
off_store = BundleContractStore(bundle)
hists = {}
for c in meta:
    bars = json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))
    hists[c] = [b for b in bars if "2015-06-01" <= str(b["date"])[:10] <= W1]
series = {c: {"hist": hists[c], "meta": {"tick": meta[c]["tick"]}} for c in meta}
mm = build_main_map(series, root=off_store)

# ------------------------------------------------------------------ Part A
by_code = defaultdict(list)
for cid in by:
    by_code[re.match(r"[A-Z]+", cid).group(0)].append(cid)


def diag(code, d, bar, tick):
    """classify an unidentified day by comparing the Sina continuous bar with official candidate bars."""
    cands = [c for c in listed_contracts_on(code, d) if d in by.get(c, {})]
    if not cands:
        return {"cls": "no_official_candidate", "detail": ""}
    c0 = float(bar["close"])
    best = None
    for c in cands:
        r = by[c][d]
        if not r.get("close"):
            continue
        t = abs(r["close"] - c0) / tick
        if best is None or t < best[0]:
            best = (t, c)
    t, c = best
    r = by[c][d]
    out = {"nearest": c, "nearest_close_diff_ticks": round(t, 2), "cont_close": c0, "nearest_close": r["close"], "nearest_settle": r.get("settle")}
    # H2: continuous close == some candidate's settle
    for cc in cands:
        s = by[cc][d].get("settle")
        if s and abs(s - c0) <= tick * 1.000001:
            out.update(cls="cont_close_equals_settle", detail=cc)
            return out
    # H1: date shift
    i = quote_days.index(d)
    for sh, dd in ((-1, quote_days[i - 1] if i > 0 else None), (1, quote_days[i + 1] if i + 1 < len(quote_days) else None)):
        if not dd:
            continue
        for cc in cands:
            rr = by[cc].get(dd)
            if rr and rr.get("close") and abs(rr["close"] - c0) <= tick * 1.000001:
                out.update(cls=f"cont_close_equals_close_of_{'prev' if sh < 0 else 'next'}_day", detail=f"{cc}@{dd}")
                return out
    if t <= 3:
        out.update(cls="within_3_ticks_of_nearest", detail=c)
    elif t <= 20:
        out.update(cls="3_to_20_ticks", detail=c)
    else:
        out.update(cls="over_20_ticks", detail=c)
    return out


resolved = {}
unid_all = []
for code in sorted(meta):
    pr = probe[code]
    start = max(W0, pr["first_tradable_day_in_window"] or W0)
    if code == "FU":
        start = FU_START
    m = mm.maps[code]
    hmap = {str(b["date"])[:10]: b for b in hists[code]}
    days = [str(b["date"])[:10] for b in hists[code] if start <= str(b["date"])[:10] <= W1 and str(b["date"])[:10] in qd]
    # carry-forward resolved map over the whole history (previous main before `start` comes from the same rule)
    series_res = {}
    last = None
    for b in hists[code]:
        d = str(b["date"])[:10]
        mv = m.get(d)
        if mv is not None:
            last = mv
        series_res[d] = (mv, last)
    unid = []
    first_no_prev = []
    for d in days:
        mv, carried = series_res[d]
        if mv is None:
            dg = diag(code, d, hmap[d], float(meta[code]["tick"]))
            rec = {"date": d, "carried_main": carried, **dg}
            if carried is None:
                first_no_prev.append(d)
            unid.append(rec)
            unid_all.append((code, rec))
    # unidentified runs that sit across a roll (carry-forward then delays the roll to the next identified day)
    gap_rolls = []
    i = 0
    while i < len(days):
        if series_res[days[i]][0] is None:
            j = i
            while j + 1 < len(days) and series_res[days[j + 1]][0] is None:
                j += 1
            before = series_res[days[i]][1]
            after = series_res[days[j + 1]][0] if j + 1 < len(days) else None
            if before and after and before != after:
                gap_rolls.append({"gap": [days[i], days[j]], "main_before": before, "next_identified_main": after})
            i = j + 1
        else:
            i += 1
    # roll count with and without carry
    n_roll = 0
    prev_c = None
    for d in days:
        cur = series_res[d][1]
        if prev_c and cur and cur != prev_c:
            n_roll += 1
        prev_c = cur or prev_c
    resolved[code] = {"start": start, "trading_days": len(days), "unidentified_n": len(unid), "unidentified": unid, "no_previous_main_dates": first_no_prev, "roll_days_after_carry": n_roll, "roll_inside_unidentified_gap": gap_rolls}

by_date = defaultdict(list)
for code, rec in unid_all:
    by_date[rec["date"]].append((code, rec))
shared = {d: v for d, v in by_date.items() if len(v) >= 5}
sh_out = {}
for d, v in sorted(shared.items()):
    cls = Counter(r["cls"] for _, r in v)
    # eligible symbols that day = symbols whose window includes d
    elig = [c for c in meta if resolved[c]["start"] <= d]
    # contrast: cache continuous bar vs official nearest on that date for a few symbols + volume of cache bar
    exs = Counter(CODE_EX[c] for c, _ in v)
    ex = {c: {"cont_close": r.get("cont_close"), "nearest": r.get("nearest"), "nearest_close": r.get("nearest_close"), "diff_ticks": r.get("nearest_close_diff_ticks"), "cls": r["cls"]} for c, r in v[:40]}
    sh_out[d] = {"n_symbols_unidentified": len(v), "n_symbols_eligible": len(elig), "by_exchange": dict(exs), "classes": dict(cls), "per_symbol": ex}
cls_total = Counter(r["cls"] for _, r in unid_all)
out_a = {
    "window": [W0, W1], "fu_start": FU_START, "unidentified_symbol_days": len(unid_all), "class_totals": dict(cls_total),
    "per_symbol": resolved, "shared_dates_ge5": sh_out,
    "unidentified_by_date": {d: sorted(c for c, _ in v) for d, v in sorted(by_date.items())},
}
(ROOT / "archive" / "R8" / "main_official_resolved.json").write_text(json.dumps(out_a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("PART A: unidentified symbol-days", len(unid_all), "classes", dict(cls_total))
print("symbols with no previous main on an unidentified day:", {c: v["no_previous_main_dates"] for c, v in resolved.items() if v["no_previous_main_dates"]})
for d, s in sh_out.items():
    print(d, s["n_symbols_unidentified"], "/", s["n_symbols_eligible"], s["by_exchange"], s["classes"])



