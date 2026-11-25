# -*- coding: utf-8 -*-
"""R8 long-sample DATA FEASIBILITY analysis (read-only; no strategy is run).

Uses the ENGINE's own main-contract rule (research.data_quality.main_map.build_main_map) on exchange-official per-contract
daily data to answer: coverage, main-contract determinability, cross-validation vs the local cache, continuous-series
adjustment status, roll-gap size in ATR14 units, implied multiplier by year.
Writes archive/R8/feasibility_results.json
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import CODE_EX, complete, load_all  # noqa: E402
from research.data_quality.contract_store import BundleContractStore  # noqa: E402
from research.data_quality.main_map import build_main_map  # noqa: E402

W0, W1 = "2016-01-04", "2025-12-31"
XV0 = "2024-09-01"  # cross-validation overlap start (local contract cache begins 2024-09)
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
probe = json.loads((ROOT / "archive" / "R8" / "long_coverage_probe.json").read_text(encoding="utf-8"))["rows"]

print("loading official per-contract data ...", flush=True)
by = load_all()
print("contracts:", len(by), "rows:", sum(len(v) for v in by.values()), flush=True)
quote_days = set()
for v in by.values():
    quote_days.update(v.keys())


def traded(r):
    return all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))


bundle = {c: [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(rows.items()) if traded(r)] for c, rows in by.items()}
store = BundleContractStore(bundle)
by_code = defaultdict(list)
for cid in by:
    import re

    by_code[re.match(r"[A-Z]+", cid).group(0)].append(cid)

hists = {}
for c in meta:
    bars = json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))
    hists[c] = [b for b in bars if "2015-06-01" <= str(b["date"])[:10] <= W1]
series = {c: {"hist": hists[c], "meta": {"tick": meta[c]["tick"]}} for c in meta}
print("building engine main_map on official data ...", flush=True)
mm = build_main_map(series, root=store)

res = {"window": [W0, W1], "per_symbol": {}, "xval": {}, "implied_mult": {}, "roll": {}}
phantom = sorted(d for d in {str(b["date"])[:10] for h in hists.values() for b in h if W0 <= str(b["date"])[:10] <= W1} if d not in quote_days)
res["phantom_days_in_cache_calendar"] = phantom
cache_days = {str(b["date"])[:10] for h in hists.values() for b in h}
res["official_trading_days_missing_from_cache_calendar"] = sorted(d for d in quote_days if W0 <= d <= W1 and d not in cache_days)

# ---------------- coverage + main determinability + roll gaps
all_gaps = []
for c in meta:
    h = hists[c]
    pr = probe[c]
    start = max(W0, pr["first_tradable_day_in_window"] or W0)
    days = [str(b["date"])[:10] for b in h]
    idx = {d: i for i, d in enumerate(days)}
    win = [d for d in days if start <= d <= W1 and d in quote_days]  # exclude phantom (no exchange quote at all)
    m = mm.maps[c]
    matched = full = anyfull = 0
    none_dates = []
    reason = Counter()
    per_year = defaultdict(lambda: [0, 0, 0])
    for d in win:
        mc = m.get(d)
        okm = mc is not None
        okf = okm and complete(by.get(mc, {}).get(d))
        okany = any(complete(by[x].get(d)) for x in by_code[c] if d in by[x])
        matched += okm
        full += okf
        anyfull += okany
        y = d[:4]
        per_year[y][0] += 1
        per_year[y][1] += okm
        per_year[y][2] += okf
        if not okm:
            none_dates.append(d)
    n = len(win)
    # FU / zero-volume info
    zv = [str(b["date"])[:10] for b in h if W0 <= str(b["date"])[:10] <= W1 and not b.get("volume")]
    # rolls and gaps
    atr = {}
    trs = []
    for i, b in enumerate(h):
        if i == 0:
            trs.append(None)
            continue
        pc = float(h[i - 1]["close"])
        trs.append(max(float(b["high"]) - float(b["low"]), abs(float(b["high"]) - pc), abs(float(b["low"]) - pc)))
        if i >= 14:
            atr[i] = sum(trs[i - 13 : i + 1]) / 14.0
    rolls, gaps, nogap = 0, [], 0
    roll_by_year = Counter()
    for i in range(1, len(h)):
        d, d0 = days[i], days[i - 1]
        if not (W0 <= d <= W1):
            continue
        m1, m0 = m.get(d), m.get(d0)
        if m1 and m0 and m1 != m0:
            rolls += 1
            roll_by_year[d[:4]] += 1
            r_new, r_old = by.get(m1, {}).get(d0), by.get(m0, {}).get(d0)
            a = atr.get(i - 1)
            if r_new and r_old and traded(r_new) and traded(r_old) and a:
                g = abs(r_new["close"] - r_old["close"]) / a
                gaps.append(g)
            else:
                nogap += 1
    all_gaps += [(c, g) for g in gaps]

    def pct(v, q):
        v = sorted(v)
        return v[min(len(v) - 1, int(round(q * (len(v) - 1))))] if v else None

    res["per_symbol"][c] = {
        "exchange": CODE_EX[c], "start": start, "trading_days_in_window": n,
        "main_identified_days": matched, "main_identified_share": round(matched / n, 5) if n else None,
        "main_row_complete_days": full, "main_row_complete_share": round(full / n, 5) if n else None,
        "any_contract_complete_share": round(anyfull / n, 5) if n else None,
        "unidentified_dates_first20": none_dates[:20], "unidentified_n": len(none_dates),
        "by_year_main_share": {y: round(v[1] / v[0], 4) for y, v in sorted(per_year.items())},
        "by_year_complete_share": {y: round(v[2] / v[0], 4) for y, v in sorted(per_year.items())},
        "engine_stats": {k: mm.stats[c][k] for k in ("none_no_candidate_bar", "none_no_match_within_tick", "none_ambiguous")},
        "cache_zero_volume_days": len(zv), "cache_zero_volume_last": zv[-1] if zv else None,
    }
    res["roll"][c] = {
        "roll_days": rolls, "roll_days_with_gap_measured": len(gaps), "roll_days_gap_unmeasured": nogap,
        "gap_atr14_median": round(statistics.median(gaps), 4) if gaps else None, "gap_atr14_p90": round(pct(gaps, 0.9), 4) if gaps else None,
        "gap_atr14_max": round(max(gaps), 4) if gaps else None, "gap_gt_1atr": sum(1 for g in gaps if g > 1.0),
        "rolls_by_year": dict(sorted(roll_by_year.items())),
    }
g_only = [g for _, g in all_gaps]
res["roll_pooled"] = {
    "roll_days_measured": len(g_only), "median": round(statistics.median(g_only), 4), "p90": round(sorted(g_only)[int(0.9 * (len(g_only) - 1))], 4),
    "max": round(max(g_only), 4), "gt_1atr": sum(1 for g in g_only if g > 1.0), "gt_0_5atr": sum(1 for g in g_only if g > 0.5),
}
print("coverage + roll done", flush=True)

# ---------------- cross validation vs local cache (sina_exact_contract) for dates >= XV0
FIELDS = [("open", "open"), ("high", "high"), ("low", "low"), ("close", "close"), ("settle", "settle"), ("volume", "volume"), ("oi", "open_interest")]
agg = defaultdict(lambda: defaultdict(lambda: {"n": 0, "mismatch": 0, "max_abs": 0.0, "max_rel": 0.0, "sum_signed_rel": 0.0, "examples": []}))
only_off = Counter()
only_loc = Counter()
loc_settle0 = Counter()
n_pairs = Counter()
for p in sorted((ROOT / ".cache" / "contracts").glob("*.json")):
    cid = p.stem
    if cid not in by:
        only_loc[cid[:2]] += 0
        continue
    code = re.match(r"[A-Z]+", cid).group(0)
    ex = CODE_EX.get(code)
    if ex is None:
        continue
    loc = {str(b["date"])[:10]: b for b in json.loads(p.read_text(encoding="utf-8")).get("bars", [])}
    off = by[cid]
    for d, lb in loc.items():
        if d < XV0 or d > W1:
            continue
        ob = off.get(d)
        if ob is None:
            only_loc[ex] += 1
            continue
        n_pairs[ex] += 1
        for fo, fl in FIELDS:
            ov, lv = ob.get(fo), lb.get(fl)
            if ov is None or lv is None:
                continue
            if fo == "settle" and float(lv) == 0.0:
                loc_settle0[ex] += 1
                continue
            a = agg[ex][fo]
            a["n"] += 1
            diff = float(lv) - float(ov)
            if abs(diff) > 1e-9:
                a["mismatch"] += 1
                a["max_abs"] = max(a["max_abs"], abs(diff))
                rel = abs(diff) / abs(float(ov)) if ov else 0.0
                a["max_rel"] = max(a["max_rel"], rel)
                a["sum_signed_rel"] += diff / float(ov) if ov else 0.0
                if len(a["examples"]) < 4:
                    a["examples"].append([cid, d, ov, lv])
    for d, ob in off.items():
        if XV0 <= d <= W1 and d not in loc and traded(ob) and loc:
            only_off[ex] += 1
res["xval"] = {
    "overlap_from": XV0,
    "pairs_by_exchange": dict(n_pairs), "local_only_rows": dict(only_loc), "official_only_rows_in_local_contract_span": dict(only_off),
    "local_settle_zero_rows_skipped": dict(loc_settle0),
    "fields": {ex: {f: dict(v) for f, v in d.items()} for ex, d in agg.items()},
}
print("xval done", flush=True)

# ---------------- implied multiplier = turnover(万元)*1e4 / (volume * settle)
im = defaultdict(lambda: defaultdict(list))
for cid, rows in by.items():
    code = re.match(r"[A-Z]+", cid).group(0)
    for d, r in rows.items():
        if r.get("turnover_wan") and r.get("volume") and r["volume"] >= 2000 and r.get("settle"):
            im[code][d[:4]].append(r["turnover_wan"] * 1e4 / (r["volume"] * r["settle"]))
for c in meta:
    res["implied_mult"][c] = {
        "universe_mult": meta[c]["mult"],
        "by_year_median_ratio": {y: round(statistics.median(v) / meta[c]["mult"], 4) for y, v in sorted(im[c].items()) if len(v) >= 20},
        "years_without_turnover": sorted(set(str(y) for y in range(2016, 2026)) - {y for y, v in im[c].items() if len(v) >= 20}),
    }
(ROOT / "archive" / "R8" / "feasibility_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("written feasibility_results.json")
