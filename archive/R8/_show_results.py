import json
from pathlib import Path

r = json.loads((Path(__file__).resolve().parent / "feasibility_results.json").read_text(encoding="utf-8"))
print("phantom days:", r["phantom_days_in_cache_calendar"])
print("official trading days missing from cache calendar:", r["official_trading_days_missing_from_cache_calendar"])
print("\ncode ex start days main_id% complete% anyfull% unid_n  engine_stats")
for c, s in r["per_symbol"].items():
    print(c, s["exchange"], s["start"], s["trading_days_in_window"], f"{s['main_identified_share']*100:.2f}", f"{s['main_row_complete_share']*100:.2f}",
          f"{s['any_contract_complete_share']*100:.2f}", s["unidentified_n"], s["engine_stats"], "zv", s["cache_zero_volume_days"], s["cache_zero_volume_last"])
print("\nmain share by year (min over symbols):")
years = sorted({y for s in r["per_symbol"].values() for y in s["by_year_main_share"]})
for y in years:
    vals = {c: s["by_year_main_share"].get(y) for c, s in r["per_symbol"].items() if s["by_year_main_share"].get(y) is not None}
    low = sorted(vals.items(), key=lambda kv: kv[1])[:4]
    print(y, "min", low)
print("\nroll pooled:", r["roll_pooled"])
for c, s in r["roll"].items():
    print(c, s["roll_days"], s["roll_days_with_gap_measured"], s["gap_atr14_median"], s["gap_atr14_p90"], s["gap_atr14_max"], s["gap_gt_1atr"])
print("\nxval pairs:", r["xval"]["pairs_by_exchange"], "local-only:", r["xval"]["local_only_rows"], "official-only:", r["xval"]["official_only_rows_in_local_contract_span"], "settle0:", r["xval"]["local_settle_zero_rows_skipped"])
for ex, d in r["xval"]["fields"].items():
    for f, v in d.items():
        print(ex, f, "n", v["n"], "mismatch", v["mismatch"], "max_abs", v["max_abs"], "max_rel", round(v["max_rel"], 5), "mean_signed_rel", round(v["sum_signed_rel"] / v["mismatch"], 5) if v["mismatch"] else 0, v["examples"][:2])
print("\nimplied multiplier ratio by year (vs universe):")
for c, s in r["implied_mult"].items():
    print(c, s["universe_mult"], s["by_year_median_ratio"], "no-turnover:", s["years_without_turnover"])
