# -*- coding: utf-8 -*-
"""Read-only: why can the engine rule not identify the main contract on the shared dates?
Hypothesis: the Sina continuous bar of that day is an incomplete intraday snapshot (range contained in the official
range, volume smaller) or a different time-stamp convention.  Compare continuous bar vs nearest official contract."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import load_all  # noqa: E402

R8 = ROOT / "archive" / "R8"
a = json.loads((R8 / "main_official_resolved.json").read_text(encoding="utf-8"))
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
by = load_all()
hist = {c: {str(b["date"])[:10]: b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))} for c in meta}
print("cache bar keys (AG 2021-12-30):", sorted(hist["AG"]["2021-12-30"].keys()))
shared = ["2016-04-05", "2017-10-09", "2019-04-30", "2021-01-07", "2021-12-28", "2021-12-30", "2022-03-23", "2023-08-28", "2024-09-25"]
summary = {}
rows_all = []
for d in shared:
    syms = a["unidentified_by_date"].get(d, [])
    cls = Counter()
    for c in syms:
        rec = next(r for r in a["per_symbol"][c]["unidentified"] if r["date"] == d)
        cand = rec.get("nearest")
        if not cand:
            cls["no_candidate"] += 1
            continue
        h = hist[c][d]
        o = by[cand][d]
        tick = float(meta[c]["tick"])
        if not (o.get("high") and o.get("low")):
            cls["official_ohlc_missing"] += 1
            continue
        contained = h["high"] <= o["high"] + 1e-9 and h["low"] >= o["low"] - 1e-9
        hv = h.get("volume") or 0
        key = ("range_contained_in_official" if contained else "range_not_contained") + ("|cont_vol<official_main_vol" if hv < (o.get("volume") or 0) else "|cont_vol>=official_main_vol")
        cls[key] += 1
        rows_all.append((d, c, cand, h["open"], h["high"], h["low"], h["close"], hv, o["open"], o["high"], o["low"], o["close"], o.get("settle"), o.get("volume")))
    summary[d] = {"n": len(syms), "classes": dict(cls)}
for d, s in summary.items():
    print(d, s)
print()
print("sample rows (date sym nearest | cont O H L C V | official O H L C settle V):")
for r in rows_all:
    if r[0] in ("2021-12-30", "2024-09-25", "2019-04-30") and r[1] in ("AG", "AU", "NI", "P", "V", "RU", "BU", "EB"):
        print(r)
# weekday / calendar context
import datetime

for d in shared:
    dt = datetime.date.fromisoformat(d)
    print(d, dt.strftime("%a"))
(R8 / "shared_dates_diag.json").write_text(json.dumps({"summary": summary, "rows": rows_all}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
