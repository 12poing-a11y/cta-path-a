# -*- coding: utf-8 -*-
"""R4 step 0 (read-only): how often did R6c breach gross 50% / ATR-risk 8% on entry days?

Input : archive/R6/replay_after_R6c.json (+ the frozen snapshot for closes / adjusted ATR)
Output: archive/R4/prefix_R6c_caps.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab/shadow"))
import replay as R  # noqa: E402
from research.data_quality.adjusted import build_adjusted_pack  # noqa: E402
from research.data_quality.main_map import build_main_map  # noqa: E402

rc = json.loads((ROOT / "archive/R6/replay_after_R6c.json").read_text(encoding="utf-8"))
snap = json.loads((ROOT / "archive/snapshots/bt_input_20261123_da9c8de64ab4.json").read_text(encoding="utf-8"))
_p, pack = R.make_pack(snap_obj=snap)
series = pack[0]
mm = build_main_map(series, root=ROOT, start=None)
adj = build_adjusted_pack(series, mm, root=ROOT)
idx = {c: {b["date"]: i for i, b in enumerate(s["hist"])} for c, s in series.items()}
mult = {c: float(s["meta"]["mult"]) for c, s in series.items()}
bucket = {c: s["meta"].get("bucket") for c, s in series.items()}

curve = rc["equity_curve"]
days = [c["date"] for c in curve]
eq_end = {c["date"]: c["equity"] for c in curve}
GROSS_CAP, RISK_CAP = float(rc["max_gross_exposure_pct"]), float(rc["max_portfolio_risk_pct"])

# per-day book: code -> lots, from the trade list (a position sits in `pos` from the signal day,
# i.e. the last curve day before its entry_date, through its exit date)
trades = list(rc["closed_pnls"])
fp = rc.get("final_positions") or {}
for code, p in (fp.items() if isinstance(fp, dict) else []):
    trades.append({"code": code, "entry_date": p["entry_date"], "date": days[-1] + "~open", "lots": p["lots"],
                   "direction": p["direction"], "entry": p["entry"], "stop": p["stop"], "R": None, "open": True})


def sig_day(entry_date):
    prev = [d for d in days if d < entry_date]
    return prev[-1] if prev else days[0]


book = {d: {} for d in days}
for t in trades:
    s0 = sig_day(t["entry_date"])
    end = t["date"] if not t.get("open") else days[-1]
    for d in days:
        if s0 <= d <= end:
            book[d][t["code"]] = t

rows = []
prev_codes: set = set()
for k, d in enumerate(days):
    cur = set(book[d])
    added = sorted(cur - prev_codes)
    prev_codes = cur
    if not added:
        continue
    sizing_eq = eq_end[days[k - 1]] if k > 0 else rc["equity_start"]
    g = r = 0.0
    parts = []
    for code, t in book[d].items():
        i = idx[code][d]
        close = series[code]["hist"][i]["close"]
        a = adj[code].atr14(i) or 0.0
        n = abs(int(t["lots"]))
        g += n * close * mult[code]
        r += n * a * mult[code]
        parts.append({"code": code, "lots": n, "new": code in added, "bucket": bucket[code],
                      "notional_pct": round(n * close * mult[code] / sizing_eq * 100, 2),
                      "risk_pct": round(n * a * mult[code] / sizing_eq * 100, 2)})
    rows.append({
        "date": d,
        "added": added,
        "held_codes": sorted(cur),
        "sizing_equity": round(sizing_eq, 2),
        "curve_gross_pct": curve[k]["gross_pct"],
        "gross_pct_sizing_eq": round(g / sizing_eq * 100, 2),
        "atr_risk_pct_sizing_eq": round(r / sizing_eq * 100, 2),
        "gross_gt50": g / sizing_eq * 100 > GROSS_CAP + 1e-9,
        "risk_gt8": r / sizing_eq * 100 > RISK_CAP + 1e-9,
        "positions": parts,
    })

n = len(rows)
out = {
    "source": "archive/R6/replay_after_R6c.json",
    "entry_days": n,
    "caps": {"gross_pct": GROSS_CAP, "risk_pct": RISK_CAP},
    "days_gross_gt50_sizing_eq": sum(r["gross_gt50"] for r in rows),
    "days_gross_gt50_curve": sum(1 for r in rows if r["curve_gross_pct"] > GROSS_CAP + 1e-9),
    "days_risk_gt8": sum(r["risk_gt8"] for r in rows),
    "days_either_gt": sum(1 for r in rows if r["gross_gt50"] or r["risk_gt8"]),
    "max_gross_pct_sizing_eq": max(r["gross_pct_sizing_eq"] for r in rows),
    "max_gross_pct_curve": max(r["curve_gross_pct"] for r in rows),
    "max_atr_risk_pct": max(r["atr_risk_pct_sizing_eq"] for r in rows),
    "worst_days": sorted(rows, key=lambda r: -r["gross_pct_sizing_eq"])[:5],
    "rows": rows,
}
(ROOT / "archive/R4/prefix_R6c_caps.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print({k: v for k, v in out.items() if k not in ("rows", "worst_days")})
for r in out["worst_days"]:
    print(r["date"], r["added"], r["held_codes"], "gross", r["gross_pct_sizing_eq"], "curve", r["curve_gross_pct"], "risk", r["atr_risk_pct_sizing_eq"])
print("over-limit days:")
for r in rows:
    if r["gross_gt50"] or r["risk_gt8"]:
        print(r["date"], r["added"], r["held_codes"], r["gross_pct_sizing_eq"], r["curve_gross_pct"], r["atr_risk_pct_sizing_eq"])
