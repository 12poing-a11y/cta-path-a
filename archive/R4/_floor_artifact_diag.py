# -*- coding: utf-8 -*-
"""Diagnostic only (does not change any result): how many candidates did the book-aware caps call drop /
shrink although the remaining quota would fit the next lot?  (uniform `floor(lots*scale)` rounding artifact)

Wraps historical_backtest.apply_portfolio_caps during an R4 replay; output archive/R4/floor_artifact_diag.json
"""
import json
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab/shadow"))
import historical_backtest as hb  # noqa: E402

orig = hb.apply_portfolio_caps
rows = []


def wrap(cands, **kw):
    out = orig(cands, **kw)
    # book-aware call == the one whose gross cap was reduced below the full cap
    sel, meta = out
    if kw.get("existing_buckets") is None or not cands:
        return out
    if kw["max_gross_exposure_pct"] >= 50.0 - 1e-9 and kw["max_portfolio_risk_pct"] >= 8.0 - 1e-9:
        return out  # counterfactual call
    eq = kw["equity"]
    gl = eq * kw["max_gross_exposure_pct"] / 100.0
    rl = eq * kw["max_portfolio_risk_pct"] / 100.0
    got = {c["code"]: int(c["lots"]) for c in sel}
    used_g = sum(int(c["lots"]) * c["close"] * c["mult"] for c in sel)
    used_r = sum(int(c["lots"]) * c["atr"] * c["mult"] for c in sel)
    bk = dict(kw["existing_buckets"] or {})
    for c in sel:
        bk[c["bucket"]] = bk.get(c["bucket"], 0) + 1
    for c in cands:
        if got.get(c["code"], 0) >= int(c["lots"]):
            continue
        add = got.get(c["code"], 0) + 1
        g1 = add * c["close"] * c["mult"]
        r1 = add * c["atr"] * c["mult"]
        slot_ok = got.get(c["code"], 0) > 0 or len(sel) < kw["max_positions"]
        bucket_ok = got.get(c["code"], 0) > 0 or bk.get(c["bucket"], 0) < kw["max_per_bucket"]
        fits = (used_g + c["close"] * c["mult"] <= gl + 1e-6) and (used_r + c["atr"] * c["mult"] <= rl + 1e-6)
        rows.append(
            {
                "code": c["code"],
                "lots_requested": int(c["lots"]),
                "lots_given": got.get(c["code"], 0),
                "next_lot_fits_remaining_quota": bool(fits and slot_ok and bucket_ok),
                "slot_ok": bool(slot_ok),
                "bucket_ok": bool(bucket_ok),
                "remaining_gross_pct": round(gl / eq * 100, 2),
                "one_more_lot_gross_pct": round(c["close"] * c["mult"] / eq * 100, 2),
            }
        )
    return out


hb.apply_portfolio_caps = wrap
sys.argv = [
    "replay.py", "--bt", "archive/R0/fresh_bt.json",
    "--snap", "archive/snapshots/bt_input_20261123_da9c8de64ab4.json",
    "--out", str(ROOT / "archive/R4/_diag_replay_tmp.json"),
]
try:
    runpy.run_path(str(ROOT / "lab/shadow/replay.py"), run_name="__main__")
except SystemExit:
    pass
tmp = ROOT / "archive/R4/_diag_replay_tmp.json"
if tmp.exists():
    tmp.unlink()
n = len(rows)
fit = [r for r in rows if r["next_lot_fits_remaining_quota"]]
summary = {
    "book_aware_call_candidate_shortfalls": n,
    "of_which_next_lot_still_fits_quota": len(fit),
    "rows": rows,
}
(ROOT / "archive/R4" / os.environ.get("DIAG_OUT", "floor_artifact_diag.json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("shortfalls", n, "next lot fits", len(fit))
