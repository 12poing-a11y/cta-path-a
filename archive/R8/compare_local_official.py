# -*- coding: utf-8 -*-
"""R8 follow-up item 3 (read-only, no strategy run).

(1) Value cross-check of EVERY local per-contract bar the engine's CacheContractStore can see
    (.cache/contracts first, else .cache/gamma_wall/raw, else .cache/sina/*/) against the official data,
    split by local source: OHLC/volume agreement.
(2) Like-for-like main-contract map: official values restricted to the (contract, date) pairs the local store has,
    vs the local store, windows 2024-09-01..2025-12-31 and 2018-01-01..2025-12-31.  Compares main[d] and roll events.
Writes archive/R8/local_vs_official_xval.json and archive/R8/main_official_vs_local.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import CODE_EX, load_all  # noqa: E402
from research.data_quality.contract_store import BundleContractStore, CacheContractStore  # noqa: E402
from research.data_quality.main_map import build_main_map  # noqa: E402

W1 = "2025-12-31"
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
by = load_all()
qd = {d for v in by.values() for d in v}
loc = CacheContractStore(ROOT)
stable = {p.stem for p in (ROOT / ".cache" / "contracts").glob("*.json")}
gw_dir = ROOT / ".cache" / "gamma_wall" / "raw"
gw = {p.name.replace("_daily.json", "") for p in gw_dir.glob("*_daily.json")} if gw_dir.is_dir() else set()


def src_of(c):
    return "contracts" if c in stable else ("gamma_wall" if c in gw else "sina")


def traded(r):
    return all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))


# ---------------------------------------------------------------- (1) value cross-check, all local sources
avail = {}
for c in by:
    r = loc.by_date(c)
    if r:
        avail[c] = r
xv = defaultdict(lambda: defaultdict(lambda: {"n": 0, "price_mismatch": 0, "vol_mismatch": 0, "vol_local_lower": 0, "vol_local_higher": 0, "max_abs_price": 0.0, "examples": []}))
by_year = defaultdict(lambda: [0, 0])
for c, rows in avail.items():
    s = src_of(c)
    for d, b in rows.items():
        if d > W1 or d not in by[c]:
            continue
        o = by[c][d]
        x = xv[s][CODE_EX[re.match(r"[A-Z]+", c).group(0)]]
        x["n"] += 1
        pm = max(abs((b.get(k) or 0) - (o.get(k) or 0)) for k in ("open", "high", "low", "close"))
        if pm > 1e-9:
            x["price_mismatch"] += 1
            x["max_abs_price"] = max(x["max_abs_price"], pm)
            if len(x["examples"]) < 4:
                x["examples"].append([c, d, {k: [b.get(k), o.get(k)] for k in ("open", "high", "low", "close")}])
        lv, ov = b.get("volume") or 0, o.get("volume") or 0
        by_year[(s, d[:4])][0] += 1
        if lv != ov:
            x["vol_mismatch"] += 1
            by_year[(s, d[:4])][1] += 1
            if lv < ov:
                x["vol_local_lower"] += 1
            else:
                x["vol_local_higher"] += 1
out1 = {s: {ex: dict(v) for ex, v in d.items()} for s, d in xv.items()}
out1["volume_mismatch_share_by_source_year"] = {f"{s}:{y}": round(v[1] / v[0], 4) for (s, y), v in sorted(by_year.items())}
out1["n_local_contracts_by_source"] = dict(Counter(src_of(c) for c in avail))
(ROOT / "archive" / "R8" / "local_vs_official_xval.json").write_text(json.dumps(out1, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("(1) local contracts by source:", out1["n_local_contracts_by_source"])
for s, d in xv.items():
    tn = sum(v["n"] for v in d.values())
    print(" source", s, "pairs", tn, "price_mismatch", sum(v["price_mismatch"] for v in d.values()), "vol_mismatch", sum(v["vol_mismatch"] for v in d.values()),
          "(lower", sum(v["vol_local_lower"] for v in d.values()), "higher", sum(v["vol_local_higher"] for v in d.values()), ")")
    for ex, v in d.items():
        if v["price_mismatch"]:
            print("   price mismatches", ex, v["price_mismatch"], "max_abs", v["max_abs_price"], v["examples"][:2])
print(" vol mismatch share by source:year", out1["volume_mismatch_share_by_source_year"])

# ---------------------------------------------------------------- (2) like-for-like main-map comparison
hists = {}
for c in meta:
    bars = json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))
    hists[c] = [b for b in bars if "2015-06-01" <= str(b["date"])[:10] <= W1]
common = {}
for c, ld in avail.items():
    rows = [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(by[c].items()) if d in ld and traded(r)]
    if rows:
        common[c] = rows
cm_store = BundleContractStore(common)
# the local side as the engine sees it (same pairs, local values)
loc_bundle = {c: [dict(date=d, open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b.get("volume")) for d, b in sorted(avail[c].items()) if d in by[c] and d <= W1 and all((b.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))] for c in common}
loc_bundle = {c: v for c, v in loc_bundle.items() if v}
lc_store = BundleContractStore(loc_bundle)


def rolls(mp, days):
    out, last = [], None
    for d in days:
        cur = mp.get(d) or last
        if last and cur and cur != last:
            out.append((d, last, cur))
        last = cur or last
    return out


result = {}
for name, w0 in (("2024-09-01..2025-12-31", "2024-09-01"), ("2018-01-01..2025-12-31", "2018-01-01")):
    sb = {c: {"hist": [b for b in hists[c] if w0 <= str(b["date"])[:10] <= W1], "meta": {"tick": meta[c]["tick"]}} for c in meta}
    m_off = build_main_map(sb, root=cm_store)
    m_loc = build_main_map(sb, root=lc_store)
    m_full = build_main_map(sb, root=BundleContractStore({c: [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume")) for d, r in sorted(rows.items()) if traded(r)] for c, rows in by.items()}))
    tot = Counter()
    diff_rows, roll_rows = [], []
    per = {}
    for c in sorted(meta):
        days = [str(b["date"])[:10] for b in sb[c]["hist"] if str(b["date"])[:10] in qd]
        a, b, f = m_off.maps[c], m_loc.maps[c], m_full.maps[c]
        dd = [(d, a.get(d), b.get(d)) for d in days if a.get(d) != b.get(d)]
        ra, rb = rolls(a, days), rolls(b, days)
        oo, ol = sorted(set(ra) - set(rb)), sorted(set(rb) - set(ra))
        per[c] = {"days": len(days), "identified_official_all": sum(1 for d in days if f.get(d)), "identified_official_on_local_set": sum(1 for d in days if a.get(d)), "identified_local": sum(1 for d in days if b.get(d)),
                  "main_differs_days": len(dd), "roll_events_official_on_local_set": len(ra), "roll_events_local": len(rb), "roll_only_official": [list(x) for x in oo], "roll_only_local": [list(x) for x in ol]}
        for k, v in (("symbol_days", len(days)), ("identified_official_all", per[c]["identified_official_all"]), ("identified_official_on_local_set", per[c]["identified_official_on_local_set"]),
                     ("identified_local", per[c]["identified_local"]), ("days_main_differs", len(dd)), ("roll_events_official_on_local_set", len(ra)), ("roll_events_local", len(rb)),
                     ("roll_events_not_in_both", len(oo) + len(ol))):
            tot[k] += v
        diff_rows += [(c, *x) for x in dd]
        roll_rows += [(c, "official_only", *x) for x in oo] + [(c, "local_only", *x) for x in ol]
    result[name] = {"totals": dict(tot), "per_symbol": per, "main_differs_rows": [list(r) for r in diff_rows], "roll_differs_rows": [list(r) for r in roll_rows]}
    print("\n(2) window", name, dict(tot))
    print("  main differs rows:", len(diff_rows))
    for r in diff_rows[:60]:
        print("   ", r)
    print("  roll events not in both:", len(roll_rows))
    for r in roll_rows[:60]:
        print("   ", r)
(ROOT / "archive" / "R8" / "main_official_vs_local.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
