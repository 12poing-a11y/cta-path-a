# -*- coding: utf-8 -*-
"""Read-only diagnostics behind the feasibility report (no strategy). Writes archive/R8/feasibility_diag.json"""
from __future__ import annotations

import gzip
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import CODE_EX, RAW, load_all  # noqa: E402
from research.data_quality.contract_store import BundleContractStore  # noqa: E402
from research.data_quality.main_map import build_main_map  # noqa: E402

W0, W1 = "2016-01-04", "2025-12-31"
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
probe = json.loads((ROOT / "archive" / "R8" / "long_coverage_probe.json").read_text(encoding="utf-8"))["rows"]
by = load_all()
quote_days = {d for v in by.values() for d in v}


def traded(r):
    return all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))


bundle = {c: [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(rows.items()) if traded(r)] for c, rows in by.items()}
store = BundleContractStore(bundle)
by_code = defaultdict(list)
for cid in by:
    by_code[re.match(r"[A-Z]+", cid).group(0)].append(cid)
hists = {c: [b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8")) if "2015-06-01" <= str(b["date"])[:10] <= W1] for c in meta}
mm = build_main_map({c: {"hist": hists[c], "meta": {"tick": meta[c]["tick"]}} for c in meta}, root=store)
out = {}

# (a) unidentified days
unid = {}
date_ct = Counter()
cat = Counter()
for c in meta:
    start = max(W0, probe[c]["first_tradable_day_in_window"] or W0)
    rows = []
    for b in hists[c]:
        d = str(b["date"])[:10]
        if not (start <= d <= W1) or d not in quote_days or mm.maps[c].get(d) is not None:
            continue
        cands = {x: by[x][d] for x in by_code[c] if d in by[x] and traded(by[x][d])}
        tick = float(meta[c]["tick"])
        best = min(((abs(v["close"] - float(b["close"])) / tick, x) for x, v in cands.items()), default=(None, None))
        rows.append({"date": d, "cont_close": float(b["close"]), "cont_vol": b.get("volume"), "nearest_contract": best[1], "nearest_diff_ticks": None if best[0] is None else round(best[0], 2)})
        date_ct[d] += 1
        if best[0] is None:
            cat["no_candidate"] += 1
        elif best[0] <= 3:
            cat["<=3 ticks"] += 1
        elif best[0] <= 20:
            cat["3-20 ticks"] += 1
        else:
            cat[">20 ticks"] += 1
    unid[c] = rows
out["unidentified_summary"] = {"categories_excluding_FU": None}
cat_nofu = Counter()
for c, rows in unid.items():
    if c == "FU":
        continue
    for r in rows:
        k = "no_candidate" if r["nearest_diff_ticks"] is None else "<=3 ticks" if r["nearest_diff_ticks"] <= 3 else "3-20 ticks" if r["nearest_diff_ticks"] <= 20 else ">20 ticks"
        cat_nofu[k] += 1
out["unidentified_summary"]["categories_excluding_FU"] = dict(cat_nofu)
out["unidentified_total_excluding_FU"] = sum(len(r) for c, r in unid.items() if c != "FU")
out["unidentified_dates_shared_by_>=5_symbols"] = sorted([d for d, n in date_ct.items() if n >= 5])
out["unidentified_examples"] = {c: unid[c][:6] for c in ("V", "P", "EB", "NI", "AU")}

# FU
fu = hists["FU"]
zv_last = max(str(b["date"])[:10] for b in fu if W0 <= str(b["date"])[:10] <= W1 and not b.get("volume") and str(b["date"])[:10] != "2017-01-02")
i_next = next(i for i, b in enumerate(fu) if str(b["date"])[:10] > zv_last)
fu_all = json.loads((ROOT / ".cache" / "history" / "FU0.json").read_text(encoding="utf-8"))
j_next = next(i for i, b in enumerate(fu_all) if str(b["date"])[:10] > zv_last)
fu_start = str(fu_all[j_next + 60]["date"])[:10]
days_fu = [str(b["date"])[:10] for b in fu if fu_start <= str(b["date"])[:10] <= W1 and str(b["date"])[:10] in quote_days]
ok_fu = sum(1 for d in days_fu if mm.maps["FU"].get(d))
vol_by_day = defaultdict(float)
for cid in by_code["FU"]:
    for d, r in by[cid].items():
        if "2016-01-01" <= d <= "2018-12-31" and r.get("volume"):
            vol_by_day[d] += r["volume"]
out["FU"] = {
    "last_zero_volume_bar_in_cache_excl_2017-01-02": zv_last, "first_valid_bar_after": str(fu_all[j_next]["date"])[:10], "start_after_60_warmup_bars": fu_start,
    "days_from_new_start": len(days_fu), "main_identified_from_new_start": ok_fu, "share": round(ok_fu / len(days_fu), 5),
    "official_total_FU_volume_median_by_year": {y: statistics.median([v for d, v in vol_by_day.items() if d[:4] == y]) for y in ("2016", "2017", "2018")},
    "cache_FU_zero_volume_bars_2016_2018": sum(1 for b in fu if not b.get("volume") and W0 <= str(b["date"])[:10] <= "2018-12-31"),
}
bb = [b for b in fu if "2017-03-01" <= str(b["date"])[:10] <= "2017-03-10"]
out["FU"]["cache_sample_2017-03"] = bb[:4]
out["FU"]["official_2017-03-01_contracts"] = {x: {k: by[x]["2017-03-01"][k] for k in ("close", "volume")} for x in by_code["FU"] if "2017-03-01" in by[x] and traded(by[x]["2017-03-01"])}

# (b) volume / OI mismatch distribution vs local cache
XV0 = "2024-09-01"
dist = defaultdict(lambda: {"n": 0, "rel_gt_0.1pct": 0, "rel_gt_1pct": 0, "rel_gt_10pct": 0, "local_lower": 0, "local_higher": 0, "abs_eq_1": 0, "dates": Counter()})
for p in sorted((ROOT / ".cache" / "contracts").glob("*.json")):
    cid = p.stem
    if cid not in by:
        continue
    ex = CODE_EX.get(re.match(r"[A-Z]+", cid).group(0))
    if ex is None:
        continue
    for lb in json.loads(p.read_text(encoding="utf-8")).get("bars", []):
        d = str(lb["date"])[:10]
        ob = by[cid].get(d)
        if d < XV0 or ob is None:
            continue
        for fo, fl in (("volume", "volume"), ("oi", "open_interest")):
            ov, lv = ob.get(fo), lb.get(fl)
            if ov is None or lv is None:
                continue
            k = dist[(ex, fo)]
            k["n"] += 1
            diff = float(lv) - float(ov)
            if diff == 0:
                continue
            rel = abs(diff) / max(1.0, abs(float(ov)))
            k["rel_gt_0.1pct"] += rel > 0.001
            k["rel_gt_1pct"] += rel > 0.01
            k["rel_gt_10pct"] += rel > 0.1
            k["local_lower"] += diff < 0
            k["local_higher"] += diff > 0
            k["abs_eq_1"] += abs(diff) == 1
            k["dates"][d] += 1
out["vol_oi_mismatch"] = {f"{ex}:{f}": {**{kk: vv for kk, vv in v.items() if kk != "dates"}, "top_dates": v["dates"].most_common(4), "n_mismatch_days": len(v["dates"])} for (ex, f), v in dist.items()}
# price mismatches: zero-volume rows?
pm = Counter()
for p in sorted((ROOT / ".cache" / "contracts").glob("*.json")):
    cid = p.stem
    if cid not in by:
        continue
    for lb in json.loads(p.read_text(encoding="utf-8")).get("bars", []):
        d = str(lb["date"])[:10]
        ob = by[cid].get(d)
        if d < XV0 or ob is None:
            continue
        if any(abs(float(lb[k]) - float(ob[k])) > 1e-9 for k in ("open", "high", "low", "close") if ob.get(k) is not None and lb.get(k) is not None):
            pm["price_mismatch_rows"] += 1
            pm["of_which_official_volume_zero"] += (ob.get("volume") or 0) == 0
            pm["of_which_date_2024-09-25"] += d == "2024-09-25"
out["price_mismatch_rows"] = dict(pm)

# (d) SHFE old-format product-level turnover?
for ymd in ("20160104", "20190102", "20201231", "20210104"):
    j = json.loads(gzip.decompress((RAW / "shfe" / f"{ymd}.gz").read_bytes()))
    cp = j.get("o_curproduct") or []
    out.setdefault("shfe_curproduct_keys", {})[ymd] = {"n": len(cp), "keys": list(cp[0].keys()) if cp else None, "instr_has_TURNOVER": "TURNOVER" in (j["o_curinstrument"][0] if j["o_curinstrument"] else {})}
(ROOT / "archive" / "R8" / "feasibility_diag.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
print(json.dumps({k: out[k] for k in ("unidentified_summary", "unidentified_total_excluding_FU", "unidentified_dates_shared_by_>=5_symbols", "FU", "price_mismatch_rows", "shfe_curproduct_keys")}, ensure_ascii=False, indent=1, default=str)[:6000])
print(json.dumps(out["vol_oi_mismatch"], ensure_ascii=False, indent=1, default=str))
print(json.dumps(out["unidentified_examples"], ensure_ascii=False, default=str)[:2500])
