# -*- coding: utf-8 -*-
"""R8 follow-up (read-only data check; no strategy run; not counted in DSR).

Volume guard on the OFFICIAL data path: a candidate contract whose official same-day volume is < pct x (max official volume
among all candidates of that day) cannot be the main contract.  The remaining candidates go through the engine's own
price-match rule (research.data_quality.main_map.match_main_contract); an unmatched day stays unidentified and carries
the previous main (no roll).

Part 1  sensitivity at 1% / 5% / 10%  (baseline 0%):  roll events, immediate reversals split by new-main volume < 5% / >= 5%
        of the old main's same-day volume, normal (not reversed within 3 trading days) rolls that are blocked / delayed.
Part 2  official(guarded)-vs-local(unguarded) main comparison on 2024-09..2025-12, remaining differences listed.
Writes archive/R8/guard_sensitivity.json and archive/R8/guard_vs_local.json
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
from research.data_quality.main_map import build_main_map, match_main_contract  # noqa: E402

W0, W1 = "2016-01-04", "2025-12-31"
FU_START = "2018-10-16"
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
probe = json.loads((ROOT / "archive" / "R8" / "long_coverage_probe.json").read_text(encoding="utf-8"))["rows"]
by = load_all()
qd = {d for v in by.values() for d in v}


def traded(r):
    return all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))


def bundle_of(rows_by_contract, keep=None):
    out = {}
    for c, rows in rows_by_contract.items():
        rr = [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(rows.items()) if traded(r) and (keep is None or (c, d) in keep)]
        if rr:
            out[c] = rr
    return out


hists = {c: [b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8")) if "2015-06-01" <= str(b["date"])[:10] <= W1] for c in meta}


def guarded_main_map(code, hist, store, tick, pct, ref_vol):
    """Replica of build_main_map's loop (calendar candidates, price-only match) + volume guard.
    ref_vol(contract, day) -> official volume.  pct == 0 reproduces the engine exactly."""
    rows_cache, m, prev = {}, {}, None
    for b in hist:
        d = str(b.get("date") or "")[:10]
        if not d:
            continue
        cands = {}
        for c in listed_contracts_on(code, d):
            rows = rows_cache.get(c)
            if rows is None:
                rows = rows_cache[c] = store.by_date(c)
            if d in rows:
                cands[c] = rows[d]
        if pct > 0 and cands:
            vols = {c: float(ref_vol(c, d) or 0) for c in cands}
            vmax = max(vols.values())
            if vmax > 0:
                cands = {c: r for c, r in cands.items() if vols[c] >= pct * vmax}
        main, _ = match_main_contract(b, cands, tick=float(tick or 0.0), prev_main=prev)
        m[d] = main
        prev = main
    return m


def full_vol(c, d):
    r = by.get(c, {}).get(d)
    return (r or {}).get("volume") or 0


off_store = BundleContractStore(bundle_of(by))


def window_days(code):
    start = max(W0, probe[code]["first_tradable_day_in_window"] or W0)
    if code == "FU":
        start = FU_START
    return [str(b["date"])[:10] for b in hists[code] if start <= str(b["date"])[:10] <= W1 and str(b["date"])[:10] in qd]


def resolved(mp, days):
    out, last, unid = [], None, 0
    for d in days:
        v = mp.get(d)
        if v is None:
            unid += 1
        out.append(v or last)
        last = v or last
    return out, unid


def roll_events(days, ser):
    return [(i, days[i], ser[i - 1], ser[i]) for i in range(1, len(days)) if ser[i - 1] and ser[i] and ser[i] != ser[i - 1]]


def reversal_flags(ev):
    """indices (into ev) of events that belong to an A->B, B->A reversal within <=3 trading days."""
    first, second = set(), set()
    for k, (i, d, a, b) in enumerate(ev):
        for k2 in range(k + 1, len(ev)):
            j, d2, a2, b2 = ev[k2]
            if j - i > 3:
                break
            if a2 == b and b2 == a:
                first.add(k)
                second.add(k2)
                break
    return first, second


# ---------------------------------------------------------------- self-test: pct=0 replica == engine
print("self-test: replica(pct=0) vs engine build_main_map ...", flush=True)
ser_all = {c: {"hist": hists[c], "meta": {"tick": meta[c]["tick"]}} for c in meta}
eng = build_main_map(ser_all, root=off_store)
bad = 0
maps0 = {}
for c in meta:
    maps0[c] = guarded_main_map(c, hists[c], off_store, meta[c]["tick"], 0.0, full_vol)
    bad += sum(1 for d in maps0[c] if maps0[c][d] != eng.maps[c].get(d))
print("replica mismatches vs engine:", bad)
assert bad == 0

# ---------------------------------------------------------------- Part 1
TIERS = [0.0, 0.01, 0.05, 0.10]
maps = {0.0: maps0}
for p in TIERS[1:]:
    maps[p] = {c: guarded_main_map(c, hists[c], off_store, meta[c]["tick"], p, full_vol) for c in meta}

per_tier = {}
base_events = {}
base_flags = {}
for c in sorted(meta):
    days = window_days(c)
    ser, _ = resolved(maps[0.0][c], days)
    ev = roll_events(days, ser)
    base_events[c] = (days, ev)
    f1, f2 = reversal_flags(ev)
    base_flags[c] = (f1, f2)
normal_base = {c: [e for k, e in enumerate(base_events[c][1]) if k not in base_flags[c][0] and k not in base_flags[c][1]] for c in meta}
res = {"tiers": {}, "baseline_normal_rolls": sum(len(v) for v in normal_base.values())}
detail_rows = {}
for p in TIERS:
    rolls = rev_lt = rev_ge = unid = 0
    rev_rows = []
    blocked = []  # normal baseline rolls not reproduced on the same date
    sym_roll_removed = 0
    new_reversal_rows = []
    for c in sorted(meta):
        days = base_events[c][0]
        ser, u = resolved(maps[p][c], days)
        unid += u
        ev = roll_events(days, ser)
        rolls += len(ev)
        f1, _ = reversal_flags(ev)
        for k in sorted(f1):
            i, d, a, b = ev[k]
            vb, va = full_vol(b, d), full_vol(a, d)
            small = vb < 0.05 * max(va, 1)
            rev_lt += small
            rev_ge += not small
            rev_rows.append([c, d, a, b, vb, va, "lt5pct" if small else "ge5pct"])
        evset = {(d, a, b) for _, d, a, b in ev}
        for (i, d, a, b) in normal_base[c]:
            if (d, a, b) in evset:
                continue
            # delayed? same a->b later within 10 trading days
            later = [(j, d2) for j, d2, a2, b2 in ev if a2 == a and b2 == b and 0 < j - i <= 10]
            if later:
                blocked.append({"symbol": c, "date": d, "roll": f"{a}->{b}", "outcome": f"delayed {later[0][0]-i} trading day(s) to {later[0][1]}"})
            else:
                near = [(d2, a2, b2) for j, d2, a2, b2 in ev if abs(j - i) <= 5]
                blocked.append({"symbol": c, "date": d, "roll": f"{a}->{b}", "outcome": "not reproduced (blocked or different contract)", "new_main_vol": full_vol(b, d), "old_main_vol": full_vol(a, d), "max_cand_vol_that_day": max([full_vol(x, d) for x in listed_contracts_on(c, d)] or [0]), "guarded_rolls_within_5_days": near,
                                "guarded_main_on_day": ser[i], "unguarded_main_on_day": base_events[c][0][i] and maps[0.0][c].get(d)})
        # all baseline events absent under this tier (any kind)
        sym_roll_removed += sum(1 for (i, d, a, b) in base_events[c][1] if (d, a, b) not in evset)
    res["tiers"][f"{int(p*100)}%"] = {"roll_events": rolls, "unidentified_symbol_days": unid, "immediate_reversals": rev_lt + rev_ge, "reversals_new_main_lt5pct": rev_lt, "reversals_new_main_ge5pct": rev_ge,
                                      "normal_rolls_blocked_or_delayed": len(blocked), "baseline_events_not_reproduced_all_kinds": sym_roll_removed}
    detail_rows[f"{int(p*100)}%"] = {"reversals": rev_rows, "normal_blocked_or_delayed": blocked}
res["details"] = detail_rows
(ROOT / "archive" / "R8" / "guard_sensitivity.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("PART 1 baseline normal rolls:", res["baseline_normal_rolls"])
for k, v in res["tiers"].items():
    print(" ", k, v)
for k in ("1%", "5%", "10%"):
    print(f"-- normal rolls blocked/delayed at {k}: {len(detail_rows[k]['normal_blocked_or_delayed'])}")
    for r in detail_rows[k]["normal_blocked_or_delayed"]:
        print("   ", r)
print("-- remaining reversals at 5%:")
for r in detail_rows["5%"]["reversals"]:
    print("   ", r)

# ---------------------------------------------------------------- Part 2
XV0 = "2024-09-01"
loc = CacheContractStore(ROOT)
avail = {c: loc.by_date(c) for c in by if loc.by_date(c)}
keep = {(c, d) for c, ld in avail.items() for d in ld if d in by[c]}
common_store = BundleContractStore(bundle_of({c: by[c] for c in avail}, keep))
_loc_bars = {c: [dict(date=d, open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b.get("volume")) for d, b in sorted(avail[c].items()) if d in by[c] and d <= W1 and all((b.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))] for c in avail}
loc_store = BundleContractStore({c: v for c, v in _loc_bars.items() if v})
snap_days = {"2016-04-05", "2017-10-09", "2019-04-30", "2021-01-07", "2021-12-28", "2021-12-30", "2022-03-23", "2023-08-28", "2024-09-25"}
rows_out = {}
for name, p in (("official guarded 5% on local set", 0.05), ("official unguarded on local set", 0.0)):
    diffs, rolls_diff, tot = [], [], Counter()
    for c in sorted(meta):
        h = [b for b in hists[c] if XV0 <= str(b["date"])[:10] <= W1]
        days = [str(b["date"])[:10] for b in h if str(b["date"])[:10] in qd]
        a = guarded_main_map(c, h, common_store, meta[c]["tick"], p, full_vol)  # reference max volume over ALL official candidates
        b = guarded_main_map(c, h, loc_store, meta[c]["tick"], 0.0, full_vol)  # local, unguarded (default path)
        dd = [(c, d, a.get(d), b.get(d)) for d in days if a.get(d) != b.get(d)]
        ra, rb = roll_events(days, resolved(a, days)[0]), roll_events(days, resolved(b, days)[0])
        sa, sb = {(d, x, y) for _, d, x, y in ra}, {(d, x, y) for _, d, x, y in rb}
        rolls_diff += [(c, "official_only", *t) for t in sorted(sa - sb)] + [(c, "local_only", *t) for t in sorted(sb - sa)]
        diffs += dd
        tot["symbol_days"] += len(days)
        tot["main_differs_days"] += len(dd)
        tot["roll_events_official"] += len(ra)
        tot["roll_events_local"] += len(rb)
    rows_out[name] = {"totals": dict(tot), "main_differs": [list(x) for x in diffs], "roll_differs": [list(x) for x in rolls_diff]}
    print("\nPART 2", name, dict(tot))
    for x in diffs:
        print("   day diff", x, "SNAPSHOT-DAY" if x[1] in snap_days else "non-snapshot-day")
    for x in rolls_diff:
        print("   roll diff", x, "SNAPSHOT-DAY" if x[2] in snap_days or (x[2] > "2024-09-25" and x[2] <= "2024-09-27") else "non-snapshot-day")
(ROOT / "archive" / "R8" / "guard_vs_local.json").write_text(json.dumps(rows_out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
