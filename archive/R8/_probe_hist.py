# -*- coding: utf-8 -*-
"""Read-only probe: coverage of .cache/history/{CODE}0.json for the 27 universe symbols over 2016-01-01..2025-12-31.
Writes archive/R8/long_coverage_probe.json (numbers only)."""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
W0, W1 = "2016-01-01", "2025-12-31"
WARMUP = 60  # historical_backtest.WARMUP
ATR_LONG = 100
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
codes = [u["code"] for u in uni["symbols"]]
meta = {u["code"]: u for u in uni["symbols"]}
data = {}
for c in codes:
    raw = json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))
    data[c] = raw
fields = Counter()
for c, bars in data.items():
    for k in bars[0].keys():
        fields[k] += 1
print("bar fields (symbols having it):", dict(fields))
print("first bar sample:", data[codes[0]][0])
print("last bar sample:", data[codes[0]][-1])

def d10(b):
    return str(b.get("date") or b.get("trade_date") or "")[:10]

cal = sorted({d10(b) for bars in data.values() for b in bars if W0 <= d10(b) <= W1})
print("master calendar days in window:", len(cal), cal[0], cal[-1])
cal_set = set(cal)
rows = {}
for c, bars in sorted(data.items()):
    ds = [d10(b) for b in bars]
    inwin = [b for b in bars if W0 <= d10(b) <= W1]
    wd = [d10(b) for b in inwin]
    first_all, last_all = ds[0], ds[-1]
    dup = len(ds) - len(set(ds))
    # index of WARMUP-th bar counted from the symbol's first bar (engine: i >= WARMUP)
    idx60 = d10(bars[WARMUP]) if len(bars) > WARMUP else None
    idx100 = d10(bars[ATR_LONG]) if len(bars) > ATR_LONG else None
    first_trade_day = max(idx60 or "", W0) if idx60 else None
    missing_vs_cal = [d for d in cal if d >= max(first_all, W0) and d not in set(wd)]
    # longest run of consecutive master-calendar days missing
    longest, cur = 0, 0
    inset = set(wd)
    for d in cal:
        if d < max(first_all, W0):
            continue
        if d not in inset:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    nonpos = sum(1 for b in inwin if not (b.get("close") and b.get("high") and b.get("low") and b.get("open")))
    settle_n = sum(1 for b in inwin if b.get("settle") not in (None, 0))
    oi_n = sum(1 for b in inwin if (b.get("oi") or b.get("open_interest")) not in (None, 0))
    vol0 = sum(1 for b in inwin if not b.get("volume"))
    rows[c] = {
        "bucket": meta[c]["bucket"], "mult": meta[c]["mult"], "first_bar": first_all, "last_bar": last_all,
        "bars_total": len(bars), "bars_in_window": len(inwin), "dup_dates": dup,
        "listed_after_window_start": first_all > W0,
        "warmup_bar_date": idx60, "atr100_bar_date": idx100, "first_tradable_day_in_window": first_trade_day,
        "missing_master_days_after_listing": len(missing_vs_cal), "longest_missing_run": longest,
        "bars_with_null_ohlc": nonpos, "bars_with_settle": settle_n, "bars_with_oi": oi_n, "zero_volume_bars": vol0,
    }
(ROOT / "archive" / "R8" / "long_coverage_probe.json").write_text(json.dumps({"calendar_days": len(cal), "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("code first_bar last_bar n_win listed>2016 warmup60 firstTradable miss longestGap nullOHLC settle oi zeroVol")
for c, r in rows.items():
    print(c, r["first_bar"], r["last_bar"], r["bars_in_window"], r["listed_after_window_start"], r["warmup_bar_date"], r["first_tradable_day_in_window"],
          r["missing_master_days_after_listing"], r["longest_missing_run"], r["bars_with_null_ohlc"], r["bars_with_settle"], r["bars_with_oi"], r["zero_volume_bars"])
