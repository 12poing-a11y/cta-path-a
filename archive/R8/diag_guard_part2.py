# -*- coding: utf-8 -*-
"""Read-only: explain the non-snapshot-day differences of the guarded official-vs-local comparison.
(a) For each such (symbol, day): the highest-volume official candidate and whether the local store has it.
(b) Variant: guard applied on BOTH sides (same reference max volume) -> what remains."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
sys.path.insert(0, str(ROOT))
import importlib.util  # noqa: E402

# reuse definitions from guard_sensitivity without re-running Part 1: exec only the top part up to the self-test marker
src = (ROOT / "archive" / "R8" / "guard_sensitivity.py").read_text(encoding="utf-8")
head = src.split("# ---------------------------------------------------------------- self-test")[0]
ns: dict = {"__file__": str(ROOT / "archive" / "R8" / "guard_sensitivity.py")}
exec(compile(head, "guard_sensitivity_head", "exec"), ns)
by, hists, meta, qd = ns["by"], ns["hists"], ns["meta"], ns["qd"]
guarded_main_map, bundle_of, full_vol = ns["guarded_main_map"], ns["bundle_of"], ns["full_vol"]
BundleContractStore, CacheContractStore = ns["BundleContractStore"], ns["CacheContractStore"]
listed_contracts_on, W1 = ns["listed_contracts_on"], ns["W1"]

XV0 = "2024-09-01"
loc = CacheContractStore(ROOT)
avail = {c: loc.by_date(c) for c in by if loc.by_date(c)}
keep = {(c, d) for c, ld in avail.items() for d in ld if d in by[c]}
common_store = BundleContractStore(bundle_of({c: by[c] for c in avail}, keep))
_lb = {c: [dict(date=d, open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b.get("volume")) for d, b in sorted(avail[c].items()) if d in by[c] and d <= W1 and all((b.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))] for c in avail}
loc_store = BundleContractStore({c: v for c, v in _lb.items() if v})
snap = {"2024-09-25"}

# (a)
cause = Counter()
rows_a = []
for c in sorted(meta):
    h = [b for b in hists[c] if XV0 <= str(b["date"])[:10] <= W1]
    days = [str(b["date"])[:10] for b in h if str(b["date"])[:10] in qd]
    a = guarded_main_map(c, h, common_store, meta[c]["tick"], 0.05, full_vol)
    b = guarded_main_map(c, h, loc_store, meta[c]["tick"], 0.0, full_vol)
    for d in days:
        if a.get(d) == b.get(d) or d in snap:
            continue
        cands = [x for x in listed_contracts_on(c, d) if d in by.get(x, {})]
        top = max(cands, key=lambda x: full_vol(x, d)) if cands else None
        top_in_local = (top, d) in keep if top else None
        cause["top_volume_candidate_missing_from_local_store" if top and not top_in_local else "top_volume_candidate_in_local_store"] += 1
        rows_a.append((c, d, a.get(d), b.get(d), top, full_vol(top, d) if top else 0, top_in_local, full_vol(b.get(d), d) if b.get(d) else None))
print("(a) non-snapshot-day differences:", len(rows_a), dict(cause))
for r in rows_a:
    print("   ", r)

# (b) both sides guarded (reference max over ALL official candidates)
tot = Counter()
left = []
for c in sorted(meta):
    h = [b for b in hists[c] if XV0 <= str(b["date"])[:10] <= W1]
    days = [str(b["date"])[:10] for b in h if str(b["date"])[:10] in qd]
    a = guarded_main_map(c, h, common_store, meta[c]["tick"], 0.05, full_vol)
    b = guarded_main_map(c, h, loc_store, meta[c]["tick"], 0.05, full_vol)
    tot["symbol_days"] += len(days)
    for d in days:
        if a.get(d) != b.get(d):
            tot["differs"] += 1
            left.append((c, d, a.get(d), b.get(d), "SNAPSHOT-DAY" if d in snap else "non-snapshot-day"))
print("\n(b) guard on both sides:", dict(tot))
for r in left:
    print("   ", r)
json.dump({"a_non_snapshot": rows_a, "b_both_guarded_remaining": left, "b_totals": dict(tot)}, open(ROOT / "archive" / "R8" / "guard_part2_diag.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# (c) apples-to-apples: only (symbol, day) where the local store HAS the day's highest-volume official candidate
for label, pa, pb in (("official guarded 5% vs local unguarded (default path)", 0.05, 0.0), ("both unguarded", 0.0, 0.0)):
    tot, rows = Counter(), []
    for c in sorted(meta):
        h = [b for b in hists[c] if XV0 <= str(b["date"])[:10] <= W1]
        days = [str(b["date"])[:10] for b in h if str(b["date"])[:10] in qd]
        a = guarded_main_map(c, h, common_store, meta[c]["tick"], pa, full_vol)
        b = guarded_main_map(c, h, loc_store, meta[c]["tick"], pb, full_vol)
        for d in days:
            cands = [x for x in listed_contracts_on(c, d) if d in by.get(x, {})]
            top = max(cands, key=lambda x: full_vol(x, d)) if cands else None
            if not top or (top, d) not in keep:
                tot["days_excluded_top_volume_contract_not_in_local_store"] += 1
                continue
            tot["days_compared"] += 1
            if a.get(d) != b.get(d):
                tot["differs"] += 1
                rows.append((c, d, a.get(d), b.get(d), "SNAPSHOT-DAY" if d in snap else "non-snapshot-day"))
    print("\n(c)", label, dict(tot))
    for r in rows:
        print("   ", r)
