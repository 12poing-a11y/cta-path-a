# -*- coding: utf-8 -*-
"""Read-only: do volume mismatches look like day-specific feed gaps?  Per exchange-day, share of contracts
that mismatch and the local/official ratio among mismatched ones."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import CODE_EX, load_all  # noqa: E402

by = load_all()
W0, W1 = "2024-09-01", "2025-12-31"
day = defaultdict(lambda: {"n": 0, "mm": [], "n_act": 0})
for p in sorted((ROOT / ".cache" / "contracts").glob("*.json")):
    cid = p.stem
    if cid not in by:
        continue
    ex = CODE_EX[re.match(r"[A-Z]+", cid).group(0)]
    for b in json.loads(p.read_text(encoding="utf-8"))["bars"]:
        d = str(b["date"])[:10]
        if not (W0 <= d <= W1) or d not in by[cid]:
            continue
        o = by[cid][d]["volume"]
        if not o:
            continue
        x = day[(ex, d)]
        x["n"] += 1
        if (b.get("volume") or 0) != o:
            x["mm"].append((cid, (b.get("volume") or 0) / o))
res = sorted(day.items(), key=lambda kv: -len(kv[1]["mm"]))
print("exchange-days with >=1 volume mismatch:", sum(1 for _, v in res if v["mm"]), "of", len(res))
print("days with mismatch share >=20% of that exchange's traded contracts:", sum(1 for _, v in res if v["n"] and len(v["mm"]) / v["n"] >= 0.2))
for (ex, d), v in res[:12]:
    rs = sorted(r for _, r in v["mm"])
    print(ex, d, "contracts traded", v["n"], "mismatch", len(v["mm"]), "local/official min/median/max", round(rs[0], 3), round(rs[len(rs) // 2], 3), round(rs[-1], 3), "e.g.", v["mm"][:3])
# among mismatching rows: share by official volume bucket
import statistics
big = [(cid, r) for _, v in res for cid, r in v["mm"]]
print("overall mismatching local/official ratio median", round(statistics.median(r for _, r in big), 4))
