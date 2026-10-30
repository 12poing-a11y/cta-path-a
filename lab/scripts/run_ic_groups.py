# -*- coding: utf-8 -*-
"""Daily RankIC + quintile long-short for lab factors (IS and OOS separately)."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS.parents[1]))
from lab_common import (  # noqa: E402
    FACTOR_COLS,
    LAB,
    attach_fwd_ret,
    load_closes,
    load_panel_rows,
    mean_std,
    oos_split,
    run_meta,
    save_json,
    spearman,
    window_mask,
)


def _ic_series(rows: list[dict], factor: str) -> list[float]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get(factor) is None or r.get("fwd_ret") is None:
            continue
        by_day[r["date"]].append(r)
    ics: list[float] = []
    for day in sorted(by_day):
        bucket = by_day[day]
        if len(bucket) < 5:
            continue
        xs = [float(r[factor]) for r in bucket]
        ys = [float(r["fwd_ret"]) for r in bucket]
        ic = spearman(xs, ys)
        if ic is not None:
            ics.append(ic)
    return ics


def _quintile_ls(rows: list[dict], factor: str) -> dict:
    """Equal-weight top quintile long / bottom short, next-day return, daily."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get(factor) is None or r.get("fwd_ret") is None:
            continue
        by_day[r["date"]].append(r)
    rets: list[float] = []
    dates: list[str] = []
    for day in sorted(by_day):
        bucket = sorted(by_day[day], key=lambda r: float(r[factor]))
        n = len(bucket)
        if n < 10:
            continue
        k = max(1, n // 5)
        bottom = bucket[:k]
        top = bucket[-k:]
        long_r = sum(float(r["fwd_ret"]) for r in top) / len(top)
        short_r = sum(float(r["fwd_ret"]) for r in bottom) / len(bottom)
        # Default: higher factor → long (mom). Vol/expand factors invert later if needed.
        rets.append(long_r - short_r)
        dates.append(day)
    if not rets:
        return {"ok": False, "n_days": 0}
    eq = [1.0]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    mu, sd = mean_std(rets)
    ann = None if mu is None else mu * 252 * 100.0
    vol = None if sd is None else sd * (252**0.5) * 100.0
    sharpe = None if (mu is None or sd in (None, 0)) else (mu * 252) / (sd * (252**0.5))
    peak = eq[0]
    dd = 0.0
    for e in eq:
        peak = max(peak, e)
        if peak > 0:
            dd = max(dd, (peak - e) / peak)
    return {
        "ok": True,
        "n_days": len(rets),
        "start": dates[0],
        "end": dates[-1],
        "ret_pct": round((eq[-1] / eq[0] - 1.0) * 100.0, 3),
        "ann_pct": None if ann is None else round(ann, 3),
        "vol_ann_pct": None if vol is None else round(vol, 3),
        "sharpe": None if sharpe is None else round(sharpe, 3),
        "max_dd_pct": round(dd * 100.0, 3),
        "direction": "long_high_short_low",
    }


# Factors where high value is typically adverse for trend chase → report both raw and flipped.
FLIP_CANDIDATES = {"vol_ratio_sl", "vol_s", "vol_m", "vol_l"}


def _summarize(rows: list[dict], label: str) -> dict:
    factors = {}
    for col in FACTOR_COLS:
        ics = _ic_series(rows, col)
        mu, sd = mean_std(ics)
        icir = None
        if mu is not None and sd not in (None, 0):
            icir = (mu / sd) * (252**0.5)
        ls = _quintile_ls(rows, col)
        # Also flipped LS for risk-ish factors
        flipped = None
        if col in FLIP_CANDIDATES and ls.get("ok"):
            # rebuild with inverted factor
            inv_rows = [{**r, col: (-float(r[col]) if r.get(col) is not None else None)} for r in rows]
            flipped = _quintile_ls(inv_rows, col)
            flipped["direction"] = "long_low_short_high"
        factors[col] = {
            "n_ic_days": len(ics),
            "ic_mean": None if mu is None else round(mu, 5),
            "ic_std": None if sd is None else round(sd, 5),
            "icir_ann": None if icir is None else round(icir, 3),
            "quintile_ls": ls,
            "quintile_ls_flipped": flipped,
        }
    return {"window": label, "n_rows": len(rows), "factors": factors}


def main() -> int:
    split = oos_split()
    is_start, is_end = split["in_sample"]["start"], split["in_sample"]["end"]
    oos_start = split["out_of_sample"]["start"]
    oos_end = split["out_of_sample"].get("end")

    rows = attach_fwd_ret(load_panel_rows(), load_closes())
    is_rows = [r for r in rows if window_mask(r["date"], is_start, is_end)]
    oos_rows = [r for r in rows if window_mask(r["date"], oos_start, oos_end)]

    report = {
        "ok": True,
        "meta": run_meta({"script": "run_ic_groups.py"}),
        "in_sample": _summarize(is_rows, "IS"),
        "out_of_sample": _summarize(oos_rows, "OOS"),
        "disclaimer": "RankIC 与五分组多空为研究冒烟/初筛；未含完整手续费滑点；不改 Path-A 入场。",
    }
    out = LAB / "research" / "ic" / "ic_groups_latest.json"
    save_json(out, report)
    # Compact table print
    print("factor\tIS_IC\tIS_ICIR\tOOS_IC\tOOS_ICIR\tOOS_LS_ret%")
    for col in FACTOR_COLS:
        a = report["in_sample"]["factors"][col]
        b = report["out_of_sample"]["factors"][col]
        ls = b["quintile_ls"]
        print(
            f"{col}\t{a['ic_mean']}\t{a['icir_ann']}\t{b['ic_mean']}\t{b['icir_ann']}\t"
            f"{ls.get('ret_pct') if ls.get('ok') else None}"
        )
    print(f"[ic] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
