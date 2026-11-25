# -*- coding: utf-8 -*-
"""Read-only: on the OFFICIAL per-contract data, how many roll events are immediate reversals (A->B then B->A within
<=3 trading days) and how thin is the 'new main' on the roll day?  (price-only match rule can latch on a thin contract.)"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import load_all  # noqa: E402
from research.data_quality.contract_store import BundleContractStore  # noqa: E402
from research.data_quality.main_map import build_main_map  # noqa: E402

W1 = "2025-12-31"
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
by = load_all()
qd = {d for v in by.values() for d in v}


def traded(r):
    return all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))


store = BundleContractStore({c: [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(rows.items()) if traded(r)] for c, rows in by.items()})
hists = {c: [b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8")) if "2015-06-01" <= str(b["date"])[:10] <= W1] for c in meta}
mm = build_main_map({c: {"hist": hists[c], "meta": {"tick": meta[c]["tick"]}} for c in meta}, root=store)
tot_rolls = tot_rev = 0
rows = []
thin = Counter()
for c in sorted(meta):
    days = [str(b["date"])[:10] for b in hists[c] if "2016-01-04" <= str(b["date"])[:10] <= W1 and str(b["date"])[:10] in qd]
    if c == "FU":
        days = [d for d in days if d >= "2018-10-16"]
    cur_series, last = [], None
    for d in days:
        v = mm.maps[c].get(d) or last
        cur_series.append(v)
        last = v or last
    ev = []
    for i in range(1, len(days)):
        if cur_series[i - 1] and cur_series[i] and cur_series[i] != cur_series[i - 1]:
            ev.append((i, days[i], cur_series[i - 1], cur_series[i]))
    tot_rolls += len(ev)
    for k, (i, d, a, b) in enumerate(ev):
        rev = any(j == i + 1 + 0 or (0 < j - i <= 3 and a2 == b and b2 == a) for (j, d2, a2, b2) in ev[k + 1 :] if (0 < j - i <= 3 and a2 == b and b2 == a))
        if rev:
            tot_rev += 1
            va = (by[a].get(days[i - 1], {}) or {}).get("volume") or 0
            vb = (by[b].get(d, {}) or {}).get("volume") or 0
            vold = (by[a].get(d, {}) or {}).get("volume") or 0
            rows.append((c, d, a, b, vb, vold))
            if vb < 0.05 * max(vold, 1):
                thin[c] += 1
print("official-based roll events (carry-forward, window start 2016-01-04 / FU 2018-10-16):", tot_rolls)
print("immediate reversals (A->B then B->A within 3 trading days):", tot_rev, "of which new main volume <5% of old main's same-day volume:", sum(thin.values()))
print("by symbol:", dict(Counter(r[0] for r in rows)))
for r in rows:
    print(r)
(ROOT / "archive" / "R8" / "spurious_rolls_official.json").write_text(json.dumps({"roll_events": tot_rolls, "immediate_reversals": tot_rev, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
