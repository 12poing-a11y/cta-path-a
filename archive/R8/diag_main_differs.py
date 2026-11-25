# -*- coding: utf-8 -*-
"""Read-only: for every (symbol, date) where the like-for-like official/local main maps differ in the 2024-09..2025-12
overlap, print continuous bar vs official vs local bar of the relevant contracts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import load_all  # noqa: E402
from research.data_quality.contract_store import CacheContractStore  # noqa: E402

R8 = ROOT / "archive" / "R8"
res = json.loads((R8 / "main_official_vs_local.json").read_text(encoding="utf-8"))["2024-09-01..2025-12-31"]
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
tick = {u["code"]: float(u["tick"]) for u in uni["symbols"]}
by = load_all()
loc = CacheContractStore(ROOT)
stable = {p.stem for p in (ROOT / ".cache" / "contracts").glob("*.json")}
hist = {c: {str(b["date"])[:10]: b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))} for c in tick}


def f(r):
    if not r:
        return "-"
    return "O%s H%s L%s C%s V%s" % (r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("volume"))


out = []
for code, d, mo, ml in res["main_differs_rows"]:
    h = hist[code][d]
    print(f"== {code} {d}  official-on-local-set main={mo}  local main={ml}  (tick {tick[code]})")
    print("   continuous :", f(h))
    for c in sorted({x for x in (mo, ml) if x}):
        print(f"   {c} official:", f(by[c].get(d)), "| local[%s]:" % ("contracts" if c in stable else "sina"), f(loc.by_date(c).get(d)))
    if not mo:
        # nearest official candidate by close among all official contracts of the code listed that day
        near = sorted(((abs((by[c][d].get("close") or 0) - h["close"]) / tick[code], c) for c in by if c.startswith(code) and c[len(code) :].isdigit() and len(c) == len(code) + 4 and d in by[c] and by[c][d].get("close")), key=lambda x: x[0])[:2]
        print("   nearest official closes (ticks):", [(c, round(t, 1)) for t, c in near])
print()
for r in res["roll_differs_rows"]:
    print(r)
