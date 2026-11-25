# -*- coding: utf-8 -*-
"""Read-only STATIC estimate of candidate C's monthly symbol pool over 2016-01..2025-12 (no backtest, no engine).

Rule being estimated (user spec): on the first trading day of month m, pool = { i : N_i <= 25% x E }, with
N_i = 1-lot notional = prior-month-end settle x mult, E = equity at prior month-end.
The real C uses the ACTUAL equity (path dependent); here E is held at fixed levels, so this is an approximation of
which symbols would be excluded.  Multipliers: only the CURRENT mult exists in universe.json (no history) -> used for all years.
Where the prior-month-end settle is missing, close is used for this static estimate only and the month is counted in
`settle_missing_months` (the frozen rule must say what to do about it).
Writes archive/R8/long_c_pool_static.json
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
W0, W1 = "2016-01", "2025-12"
WARMUP = 60
LEVELS = [300_000, 800_000, 1_000_000, 1_200_000]
FRAC = 0.25
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
bars = {c: json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8")) for c in meta}
months = []
y, m = 2016, 1
while f"{y}-{m:02d}" <= W1:
    months.append(f"{y}-{m:02d}")
    m += 1
    if m == 13:
        y, m = y + 1, 1


def prev_month(ym):
    y, m = int(ym[:4]), int(ym[5:])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


# per symbol: last bar of each month, count of bars up to that month-end
info = {}
for c, bs in bars.items():
    last, cnt = {}, {}
    for i, b in enumerate(bs):
        ym = str(b["date"])[:7]
        last[ym] = b
        cnt[ym] = i + 1
    info[c] = (last, cnt)

res = {}
settle_missing = Counter()
for E in LEVELS:
    per_month = {}
    for ym in months:
        pm = prev_month(ym)
        pool, excl, notyet = [], [], []
        for c in meta:
            last, cnt = info[c]
            if pm not in last or cnt[pm] <= WARMUP:
                notyet.append(c)
                continue
            b = last[pm]
            s = b.get("settle")
            used = "settle"
            if s in (None, 0):
                s, used = b.get("close"), "close_fallback"
                if E == LEVELS[0]:
                    settle_missing[c] += 1
            n = float(s) * float(meta[c]["mult"])
            (pool if n <= FRAC * E else excl).append(c)
        per_month[ym] = {"pool": pool, "excluded_by_notional": excl, "not_tradable_yet": notyet}
    # summaries
    ex_months = Counter()
    elig_months = Counter()
    for ym, v in per_month.items():
        for c in v["excluded_by_notional"]:
            ex_months[c] += 1
        for c in v["pool"] + v["excluded_by_notional"]:
            elig_months[c] += 1
    buckets = defaultdict(set)
    for c in meta:
        buckets[meta[c]["bucket"]].add(c)
    empty_nonferrous = sum(1 for v in per_month.values() if not (set(v["pool"]) & buckets["有色"]))
    pool_sizes = [len(v["pool"]) for v in per_month.values()]
    n_buckets = [len({meta[c]["bucket"] for c in v["pool"]}) for v in per_month.values()]
    res[str(E)] = {
        "months": len(months),
        "excluded_months_by_symbol": {c: ex_months[c] for c in meta},
        "eligible_months_by_symbol": {c: elig_months[c] for c in meta},
        "pool_size": {"min": min(pool_sizes), "median": sorted(pool_sizes)[len(pool_sizes) // 2], "max": max(pool_sizes)},
        "buckets_covered": {"min": min(n_buckets), "median": sorted(n_buckets)[len(n_buckets) // 2], "max": max(n_buckets)},
        "months_nonferrous_bucket_empty": empty_nonferrous,
        "months_pool_empty": sum(1 for s in pool_sizes if s == 0),
        "per_month": per_month,
    }
out = {"rule": "N_i = prior-month-end settle x CURRENT mult <= 25% x E_fixed", "settle_missing_prior_month_end_months": dict(settle_missing),
       "nonferrous_symbols": sorted(buckets["有色"]), "bucket_of": {c: meta[c]["bucket"] for c in meta}, "levels": res}
(ROOT / "archive" / "R8" / "long_c_pool_static.json").write_text(json.dumps(out, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
print("settle-missing prior-month-end months (symbol: n):", dict(settle_missing))
for E in LEVELS:
    r = res[str(E)]
    print(f"\nE={E:,}: pool size {r['pool_size']}, buckets covered {r['buckets_covered']}, "
          f"nonferrous-empty months {r['months_nonferrous_bucket_empty']}/120, pool-empty months {r['months_pool_empty']}")
    print(" excluded months / eligible months:", {c: f"{r['excluded_months_by_symbol'][c]}/{r['eligible_months_by_symbol'][c]}" for c in meta if r["excluded_months_by_symbol"][c]})
