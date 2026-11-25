# -*- coding: utf-8 -*-
"""Daily implied-multiplier check (read-only): ratio = exchange-published turnover / (sum volume*settle) / universe mult.
DCE/CZCE: sum over the symbol's contracts of instrument turnover.  SHFE: product-level turnover (亿元) from o_curproduct.
Writes archive/R8/mult_daily_check.json"""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import EXCH, RAW, load_all  # noqa: E402

uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
by = load_all()
by_code = defaultdict(list)
for cid in by:
    by_code[re.match(r"[A-Z]+", cid).group(0)].append(cid)
days_by_code = defaultdict(dict)  # code -> day -> ratio
for code in meta:
    if code in EXCH["shfe"]:
        continue
    ds = {d for c in by_code[code] for d in by[c]}
    for d in ds:
        t = sum((by[c][d].get("turnover_wan") or 0) for c in by_code[code] if d in by[c])
        den = sum((by[c][d].get("volume") or 0) * (by[c][d].get("settle") or 0) for c in by_code[code] if d in by[c])
        vol = sum((by[c][d].get("volume") or 0) for c in by_code[code] if d in by[c])
        if t > 0 and den > 0 and vol >= 2000:
            days_by_code[code][d] = t * 1e4 / den / meta[code]["mult"]
mani = json.loads((RAW / "MANIFEST_shfe.json").read_text(encoding="utf-8"))
for d, rec in sorted(mani.items()):
    if rec.get("status") != "ok":
        continue
    j = json.loads(gzip.decompress((RAW / "shfe" / f"{d.replace('-', '')}.gz").read_bytes()))
    for r in j.get("o_curproduct") or []:
        pid = str(r.get("PRODUCTID", "")).strip()
        code = pid.split("_")[0].upper() if pid.endswith("_f") else None
        if code in EXCH["shfe"] and r.get("TURNOVER") and (r.get("VOLUME") or 0) >= 2000:
            den = sum((by[c][d].get("volume") or 0) * (by[c][d].get("settle") or 0) for c in by_code[code] if d in by[c])
            if den > 0:
                days_by_code[code][d] = float(r["TURNOVER"]) * 1e8 / den / meta[code]["mult"]
out = {}
for code in sorted(meta):
    v = days_by_code[code]
    bad = sorted(d for d, x in v.items() if abs(x - 1) > 0.02)
    xs = sorted(v.values())
    out[code] = {"days_checked": len(v), "first": min(v) if v else None, "last": max(v) if v else None, "ratio_min": round(xs[0], 4) if xs else None, "ratio_max": round(xs[-1], 4) if xs else None,
                 "days_dev_gt_2pct": len(bad), "dev_dates_first5": bad[:5], "dev_dates_last5": bad[-5:]}
(ROOT / "archive" / "R8" / "mult_daily_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
for c, s in out.items():
    print(c, meta[c]["mult"], s["days_checked"], s["first"], s["last"], s["ratio_min"], s["ratio_max"], "dev>2%:", s["days_dev_gt_2pct"], s["dev_dates_first5"][:3])
