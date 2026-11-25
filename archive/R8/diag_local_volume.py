# -*- coding: utf-8 -*-
"""Read-only: why is local per-contract volume/OI lower than the official figure?
Hypothesis tests: (1) mismatching bars are the last bar of the local file (stale intraday snapshot);
(2) relation to file mtime / bar date; (3) which fields the local bars carry (source marker)."""
from __future__ import annotations

import datetime
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import load_all  # noqa: E402

by = load_all()
W0, W1 = "2024-09-01", "2025-12-31"
rows = []  # (cid, date, pos_from_end, n_bars, loc_vol, off_vol, loc_oi, off_oi)
keys = Counter()
mt_all = {}
for p in sorted((ROOT / ".cache" / "contracts").glob("*.json")):
    cid = p.stem
    raw = json.loads(p.read_text(encoding="utf-8"))
    bars = raw["bars"]
    mt_all[cid] = datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")
    for k in raw:
        keys["file:" + k] += 1
    for b in bars[:3]:
        for k in b:
            keys["bar:" + k] += 1
    dates = [str(b["date"])[:10] for b in bars]
    for i, b in enumerate(bars):
        d = dates[i]
        if not (W0 <= d <= W1) or cid not in by or d not in by[cid]:
            continue
        o = by[cid][d]
        rows.append((cid, d, len(bars) - 1 - i, len(bars), b.get("volume"), o["volume"], b.get("open_interest"), o["oi"], b))
print("file/bar keys:", dict(keys))
print("source field values:", Counter(str(r[8].get("source") or r[8].get("src") or "-") for r in rows).most_common(8))
mv = [r for r in rows if r[4] is not None and r[5] is not None and r[4] != r[5]]
print("pairs", len(rows), "volume mismatches", len(mv))
pos = Counter(min(r[2], 5) for r in mv)
allpos = Counter(min(r[2], 5) for r in rows)
print("mismatch by position-from-end (0=last bar, 5=>=5):", dict(sorted(pos.items())), "| all rows:", dict(sorted(allpos.items())))
for k in sorted(pos):
    print("  pos", k, "mismatch share", round(pos[k] / allpos[k], 4))
# relative size distribution and diff==1
diffs = [r[5] - r[4] for r in mv]
print("diff official-local: ==1:", sum(1 for x in diffs if x == 1), " 2..10:", sum(1 for x in diffs if 2 <= x <= 10), " >10:", sum(1 for x in diffs if x > 10), " <0:", sum(1 for x in diffs if x < 0))
rel = sorted((r[5] - r[4]) / r[5] for r in mv if r[5])
print("rel diff quantiles (official-local)/official: p50 %.5f p90 %.5f p99 %.5f max %.4f" % (rel[len(rel) // 2], rel[int(.9 * len(rel))], rel[int(.99 * len(rel))], rel[-1]))
# by month of bar date
bm = defaultdict(lambda: [0, 0])
for r in rows:
    bm[r[1][:7]][0] += 1
    if r[4] != r[5]:
        bm[r[1][:7]][1] += 1
print("mismatch share by bar month:", {k: round(v[1] / v[0], 3) for k, v in sorted(bm.items())})
# top mismatches
mv.sort(key=lambda r: -(r[5] - r[4]))
print("top 12 by abs diff:")
for r in mv[:12]:
    print("  ", r[0], r[1], "pos_from_end", r[2], "local", r[4], "official", r[5], "mtime", mt_all[r[0]])
# mismatch dates concentration vs. file mtime date
late = [r for r in mv if r[1] >= "2025-12-01"]
print("mismatches in Dec-2025:", len(late), "of", len(mv))
mtc = Counter(v[:10] for v in mt_all.values())
print("local contract file mtime dates (top):", mtc.most_common(6))
# OI direction
oi_m = [r for r in rows if r[6] is not None and r[7] is not None and r[6] != r[7]]
print("OI mismatches", len(oi_m), "local<official", sum(1 for r in oi_m if r[6] < r[7]), "local>official", sum(1 for r in oi_m if r[6] > r[7]))
# same-row co-occurrence
print("rows with both vol and OI mismatch:", sum(1 for r in mv if r[6] != r[7]), "of", len(mv))
