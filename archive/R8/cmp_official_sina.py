# -*- coding: utf-8 -*-
"""Read-only: per-contract, per-day comparison of exchange-official raw bars (archive/R8/raw_contract, via contract_loader)
against Sina exact-contract cache (.cache/contracts, source sina_exact_contract) for the last two years.
Also: Sina continuous main (.cache/history, close only) vs official main-contract close as identified by the R8 main map.
Output: archive/R8/ATTRIB/cmp_official_sina.json (summary) ; prints a short report."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from contract_loader import load_all  # noqa: E402

W0, W1 = "2024-11-26", "2026-11-25"
FIELDS = ("open", "high", "low", "close", "settle", "volume", "oi")


def load_sina_contracts():
    out = defaultdict(dict)
    d = ROOT / ".cache" / "contracts"
    sample = None
    for p in sorted(d.glob("*.json")):
        code = p.stem.upper()
        raw = json.loads(p.read_text(encoding="utf-8"))
        if sample is None:
            sample = (p.name, type(raw).__name__, (list(raw.keys())[:8] if isinstance(raw, dict) else (raw[0] if raw else None)))
        bars = raw.get("bars", raw) if isinstance(raw, dict) else raw
        if isinstance(bars, dict):
            items = bars.items()
        else:
            items = ((b.get("date"), b) for b in bars)
        for dt, b in items:
            dt = str(dt)[:10]
            if not (W0 <= dt <= W1):
                continue
            out[code][dt] = b
    return out, sample


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    off = load_all()
    sina, sample = load_sina_contracts()
    print("sina sample:", sample, flush=True)
    key_map = {"oi": ("oi", "open_interest", "openInterest")}
    stats = Counter()
    diffs = {f: [] for f in FIELDS}
    examples = []
    for code, dd in off.items():
        if code not in sina:
            stats["contract_not_in_sina"] += 1
            continue
        for dt, orow in dd.items():
            if not (W0 <= dt <= W1):
                continue
            srow = sina[code].get(dt)
            if srow is None:
                stats["official_day_missing_in_sina"] += 1
                continue
            stats["paired"] += 1
            for f in FIELDS:
                ov = num(orow.get(f))
                sv = num(srow.get(f))
                if sv is None and f == "oi":
                    for k in key_map["oi"][1:]:
                        if srow.get(k) is not None:
                            sv = num(srow.get(k))
                            break
                if ov is None or sv is None:
                    stats[f"{f}:missing_one_side"] += 1
                    continue
                if ov == 0 and sv == 0:
                    stats[f"{f}:both_zero"] += 1
                    continue
                if ov == 0:  # official zero/blank, Sina has a value (thin or unpublished official row)
                    stats[f"{f}:official_zero_sina_nonzero"] += 1
                    continue
                if sv == 0:
                    stats[f"{f}:sina_zero_official_nonzero"] += 1
                    continue
                rel = (sv - ov) / ov
                diffs[f].append(rel)
                stats[f"{f}:exact"] += (sv == ov)
                if sv != ov and len(examples) < 25 and f in ("close", "volume"):
                    examples.append({"contract": code, "date": dt, "field": f, "official": ov, "sina": sv})
    summ = {}
    for f in FIELDS:
        v = diffs[f]
        n = len(v)
        if not n:
            summ[f] = None
            continue
        a = sorted(abs(x) for x in v)
        summ[f] = {"n_both_nonzero": n, "exact_share": round(stats[f"{f}:exact"] / n, 4),
                   "median_abs_rel": round(a[n // 2], 6), "p95_abs_rel": round(a[int(n * 0.95)], 6),
                   "max_abs_rel": round(a[-1], 4),
                   "share_gt_0.5pct": round(sum(1 for x in a if x > 0.005) / n, 4),
                   "share_gt_2pct": round(sum(1 for x in a if x > 0.02) / n, 4),
                   "mean_signed_rel": round(sum(v) / n, 6),
                   "official_zero_sina_nonzero": stats[f"{f}:official_zero_sina_nonzero"],
                   "sina_zero_official_nonzero": stats[f"{f}:sina_zero_official_nonzero"]}
    res = {"window": [W0, W1], "stats": dict(stats), "per_field": summ, "examples": examples}
    (HERE / "ATTRIB").mkdir(exist_ok=True)
    (HERE / "ATTRIB" / "cmp_official_sina.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
