# -*- coding: utf-8 -*-
"""Read-only extras for the feasibility report: SHFE product-level implied multiplier (2016-2020 have no instrument turnover),
and how many of the 91 'prior-month-end settle missing' symbol-months could be recovered from official per-contract settle.
Writes archive/R8/feasibility_extra.json"""
from __future__ import annotations

import gzip
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import EXCH, RAW, load_all  # noqa: E402
from research.data_quality.contract_store import BundleContractStore  # noqa: E402
from research.data_quality.main_map import build_main_map  # noqa: E402

W1 = "2025-12-31"
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
by = load_all()
by_code = defaultdict(list)
for cid in by:
    by_code[re.match(r"[A-Z]+", cid).group(0)].append(cid)
out = {"shfe_product_level_implied_mult_ratio": {}, "settle_recovery": {}}

# ---- SHFE product-level: turnover(万元)*1e4 / sum(volume*settle) / mult, annual median
mani = json.loads((RAW / "MANIFEST_shfe.json").read_text(encoding="utf-8"))
acc = defaultdict(lambda: defaultdict(list))
for d, rec in sorted(mani.items()):
    if rec.get("status") != "ok":
        continue
    j = json.loads(gzip.decompress((RAW / "shfe" / f"{d.replace('-', '')}.gz").read_bytes()))
    for r in j.get("o_curproduct") or []:
        pid = str(r.get("PRODUCTID", "")).strip()
        if not pid.endswith("_f"):
            continue
        code = pid.split("_")[0].upper()
        if code not in EXCH["shfe"]:
            continue
        t, v = r.get("TURNOVER"), r.get("VOLUME")
        if not t or not v:
            continue
        denom = sum((by[c][d]["volume"] or 0) * (by[c][d]["settle"] or 0) for c in by_code[code] if d in by[c])
        if denom <= 0 or v < 2000:
            continue
        # o_curproduct.TURNOVER is in 亿元 (verified: ratio is exactly 1e-4 when 万元 is assumed)
        acc[code][d[:4]].append(float(t) * 1e8 / denom / meta[code]["mult"])
for code in sorted(EXCH["shfe"]):
    out["shfe_product_level_implied_mult_ratio"][code] = {y: round(statistics.median(v), 4) for y, v in sorted(acc[code].items()) if len(v) >= 20}  # ratio vs universe mult

# ---- settle recovery for the 91 symbol-months
hists = {c: [b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8")) if "2015-06-01" <= str(b["date"])[:10] <= W1] for c in meta}
bundle = {c: [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(rows.items()) if all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))] for c, rows in by.items()}
mm = build_main_map({c: {"hist": hists[c], "meta": {"tick": meta[c]["tick"]}} for c in meta}, root=BundleContractStore(bundle))
months = [f"{y}-{m:02d}" for y in range(2016, 2026) for m in range(1, 13)]
prev = lambda ym: f"{int(ym[:4]) - 1}-12" if ym[5:] == "01" else f"{ym[:4]}-{int(ym[5:]) - 1:02d}"
tot = rec = 0
rows_out = []
elig_total = 0
for c in meta:
    bs = json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))
    last, cnt = {}, {}
    for i, b in enumerate(bs):
        last[str(b["date"])[:7]] = b
        cnt[str(b["date"])[:7]] = i + 1
    for ym in months:
        pm = prev(ym)
        if pm not in last or cnt[pm] <= 60:
            continue
        elig_total += 1
        b = last[pm]
        if b.get("settle") not in (None, 0):
            continue
        tot += 1
        d = str(b["date"])[:10]
        mc = mm.maps[c].get(d)
        ok_off = False
        src = None
        if mc and by.get(mc, {}).get(d) and (by[mc][d].get("settle") or 0) > 0:
            ok_off, src = True, "main-contract official settle"
        else:
            # fall back: any official contract of the symbol whose close is within 1 tick of the cache close
            for x in by_code[c]:
                r = by[x].get(d)
                if r and (r.get("settle") or 0) > 0 and abs((r.get("close") or 0) - float(b["close"])) <= float(meta[c]["tick"]):
                    ok_off, src = True, "contract matched by close"
                    break
        rec += ok_off
        rows_out.append([c, ym, d, ok_off, src])
out["settle_recovery"] = {"eligible_symbol_months": elig_total, "cache_settle_missing_symbol_months": tot, "recoverable_from_official": rec, "not_recoverable": [r for r in rows_out if not r[3]]}
(ROOT / "archive" / "R8" / "feasibility_extra.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(json.dumps(out["shfe_product_level_implied_mult_ratio"], ensure_ascii=False))
print({k: v for k, v in out["settle_recovery"].items() if k != "not_recoverable"}, "not recoverable:", out["settle_recovery"]["not_recoverable"][:10])
