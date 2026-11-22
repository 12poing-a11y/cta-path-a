# -*- coding: utf-8 -*-
"""Per-symbol Dual-Track TVS shadow (Gemini P0 refinement).

Rebuilds approximate per-code daily MTM from Path-A closed_pnls + CODE0 closes,
calibrates each day to official book PnL, then applies per-symbol downside-HV
leverage (T+1) with optional IV warn and tolerance band.

Shadow only — no position_rules / paper_book / seats writes.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from research.gemini_tvs_shadow import (
    apply_tolerance,
    downside_hv_ann,
    iv_percentile,
    load_iv_series,
    max_dd_pct,
    split_equity_curve,
)


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _dir_sign(direction: str) -> int:
    d = str(direction or "")
    if "空" in d or d.lower() in {"short", "sell", "-1"}:
        return -1
    return 1


def _load_closes(root: Path, code: str) -> dict[str, float]:
    from desk.local_bars import load_local_bars

    bars, _ = load_local_bars(root, code)
    out: dict[str, float] = {}
    for b in bars:
        day = str(b.get("date") or "")[:10]
        px = _finite(b.get("close"))
        if len(day) == 10 and px is not None and px > 0:
            out[day] = px
    return out


def _universe_mult(root: Path) -> dict[str, float]:
    from desk.loaders import load_universe

    uni = load_universe(root) or {}
    out: dict[str, float] = {}
    for s in uni.get("symbols") or []:
        if isinstance(s, dict) and s.get("code"):
            m = _finite(s.get("mult") or s.get("multiplier"))
            if m and m > 0:
                out[str(s["code"]).upper()] = float(m)
    return out


def reconstruct_symbol_day_pnls(
    closed_pnls: Sequence[dict],
    *,
    root: Path,
    calendar: Sequence[str],
) -> dict[str, dict[str, float]]:
    """date -> {code: mtm_pnl_yuan} from trade intervals + continuous closes."""
    mult = _universe_mult(root)
    closes_cache: dict[str, dict[str, float]] = {}
    cal = [str(d)[:10] for d in calendar]
    cal_set = set(cal)
    day_code: dict[str, dict[str, float]] = {d: {} for d in cal}

    for tr in closed_pnls or []:
        code = str(tr.get("code") or "").upper()
        if not code:
            continue
        m = mult.get(code)
        if not m:
            continue
        if code not in closes_cache:
            closes_cache[code] = _load_closes(root, code)
        closes = closes_cache[code]
        entry_day = str(tr.get("entry_date") or "")[:10]
        exit_day = str(tr.get("date") or "")[:10]
        entry = _finite(tr.get("entry"))
        exit_px = _finite(tr.get("exit"))
        lots = int(tr.get("lots") or 0)
        if lots <= 0 or entry is None or exit_px is None:
            continue
        if entry_day not in cal_set and exit_day not in cal_set:
            # still allow if spans calendar
            pass
        sign = _dir_sign(str(tr.get("direction") or ""))
        # trading days between entry and exit inclusive within calendar
        span = [d for d in cal if entry_day <= d <= exit_day]
        if not span:
            continue
        prev_px = entry
        for d in span:
            if d == exit_day:
                px = exit_px
            else:
                px = closes.get(d)
                if px is None:
                    continue
            pnl = sign * lots * (px - prev_px) * m
            day_code[d][code] = day_code[d].get(code, 0.0) + pnl
            prev_px = px
    return day_code


def calibrate_to_book(
    day_code: dict[str, dict[str, float]],
    equity_curve: Sequence[dict],
) -> dict[str, dict[str, float]]:
    """Scale each day's symbol pnls so they sum to official book pnl."""
    out: dict[str, dict[str, float]] = {}
    for r in equity_curve:
        day = str(r.get("date") or "")[:10]
        book = float(r.get("pnl") or 0.0)
        parts = dict(day_code.get(day) or {})
        s = sum(parts.values())
        if not parts:
            # flat day or no reconstruction — keep empty (book pnl lost to residual)
            out[day] = {}
            continue
        if abs(s) < 1e-9:
            # cannot scale; equal-split book pnl across codes present that day
            codes = list(parts.keys()) or [str(c).upper() for c in (r.get("codes") or [])]
            if not codes:
                out[day] = {}
                continue
            share = book / len(codes)
            out[day] = {c: share for c in codes}
        else:
            k = book / s
            out[day] = {c: v * k for c, v in parts.items()}
    return out


def run_per_symbol_tvs(
    equity_curve: Sequence[dict],
    symbol_day_pnls: dict[str, dict[str, float]],
    *,
    root: Path | None = None,
    target_vol: float = 0.15,
    hv_window: int = 20,
    max_leverage: float = 1.0,
    tolerance_band: float = 0.05,
    iv_warn_pctile: float = 0.90,
    iv_compress: float = 0.50,
) -> dict[str, Any]:
    """Apply per-symbol T+1 leverage to calibrated symbol day pnls."""
    root = Path(root or ".")
    rows = [r for r in equity_curve if r.get("date")]
    if len(rows) < hv_window + 5:
        return {"ok": False, "reason": "short_curve"}

    codes = sorted({c for parts in symbol_day_pnls.values() for c in parts})
    iv_map = {c: load_iv_series(root, c) for c in codes}

    # per-code return history for HV (pnl / capital_slice proxy: use pnl series normalized)
    # Use price returns when available; fallback to symbol pnl sign series.
    from desk.local_bars import load_local_bars

    price_rets: dict[str, list[tuple[str, float]]] = {}
    for c in codes:
        bars, _ = load_local_bars(root, c)
        closes = []
        for b in bars:
            d = str(b.get("date") or "")[:10]
            px = _finite(b.get("close"))
            if len(d) == 10 and px and px > 0:
                closes.append((d, px))
        rr = []
        for i in range(1, len(closes)):
            rr.append((closes[i][0], closes[i][1] / closes[i - 1][1] - 1.0))
        price_rets[c] = rr

    def hv_asof(code: str, day: str) -> float | None:
        hist = [r for d, r in price_rets.get(code, []) if d <= day]
        return downside_hv_ann(hist, window=hv_window)

    lev: dict[str, float] = {c: 1.0 for c in codes}
    base0 = float(rows[0].get("equity") or 0) - float(rows[0].get("pnl") or 0)
    if base0 <= 0:
        base0 = 200000.0
    eq_base = base0
    eq_tvs = base0
    curve_base = [eq_base]
    curve_tvs = [eq_tvs]
    n_adjust = 0
    n_iv_warn = 0
    turnover = 0.0
    residual = 0.0

    for r in rows:
        day = str(r["date"])[:10]
        book_pnl = float(r.get("pnl") or 0.0)
        parts = symbol_day_pnls.get(day) or {}
        parts_sum = sum(parts.values())
        residual += book_pnl - parts_sum

        # Apply yesterday's leverages
        tvs_pnl = 0.0
        for c, pnl in parts.items():
            tvs_pnl += float(pnl) * float(lev.get(c, 1.0))
        # Any unallocated book residual stays unlevered (lev=1)
        tvs_pnl += book_pnl - parts_sum

        eq_base += book_pnl
        eq_tvs += tvs_pnl
        curve_base.append(eq_base)
        curve_tvs.append(eq_tvs)

        # Update next leverages for codes seen today or recently held
        held = set(parts) | {str(c).upper() for c in (r.get("codes") or [])}
        for c in held:
            hv = hv_asof(c, day)
            if hv is None:
                target = 1.0
                note = ""
            else:
                target = max(0.0, min(float(max_leverage), float(target_vol) / hv))
                note = ""
                series = iv_map.get(c) or {}
                hist_days = [d for d in series if d <= day]
                if len(hist_days) >= 20:
                    cur = series[hist_days[-1]]
                    hist_vals = [series[d] for d in hist_days[-60:]]
                    pct = iv_percentile(hist_vals, cur)
                    if pct is not None and pct >= float(iv_warn_pctile) and cur > hv:
                        target *= float(iv_compress)
                        note = "iv_warn"
                        n_iv_warn += 1
            new_lev = apply_tolerance(lev.get(c, 1.0), target, band=tolerance_band)
            if abs(new_lev - lev.get(c, 1.0)) > 1e-12:
                n_adjust += 1
                turnover += abs(new_lev - lev.get(c, 1.0))
            lev[c] = new_lev
            _ = note

    def _ret(curve: list[float]) -> float:
        if not curve or curve[0] <= 0:
            return 0.0
        return round(100.0 * (curve[-1] / curve[0] - 1.0), 3)

    return {
        "ok": True,
        "mode": "gemini_per_symbol_tvs_shadow",
        "disclaimer": (
            "分品种 TVS 影子：日PnL按成交重构后校准到官方曲线；杠杆按品种下行HV、T+1生效；"
            "不改 Path-A / paper_book / seats。"
        ),
        "params": {
            "target_vol": target_vol,
            "hv_window": hv_window,
            "max_leverage": max_leverage,
            "tolerance_band": tolerance_band,
            "iv_warn_pctile": iv_warn_pctile,
            "iv_compress": iv_compress,
        },
        "window": {"start": rows[0]["date"], "end": rows[-1]["date"], "n_days": len(rows)},
        "tracking": {
            "residual_pnl_sum": round(residual, 2),
            "n_codes": len(codes),
        },
        "baseline": {
            "equity_start": round(curve_base[0], 2),
            "equity_end": round(curve_base[-1], 2),
            "ret_pct": _ret(curve_base),
            "max_dd_pct": max_dd_pct(curve_base),
        },
        "tvs_shadow": {
            "equity_start": round(curve_tvs[0], 2),
            "equity_end": round(curve_tvs[-1], 2),
            "ret_pct": _ret(curve_tvs),
            "max_dd_pct": max_dd_pct(curve_tvs),
            "n_leverage_adjust": n_adjust,
            "leverage_turnover": round(turnover, 4),
            "n_iv_warn": n_iv_warn,
        },
        "delta": {
            "ret_pct_pts": round(_ret(curve_tvs) - _ret(curve_base), 3),
            "dd_pct_pts": round(max_dd_pct(curve_tvs) - max_dd_pct(curve_base), 3),
        },
    }


def score_candidate(result: dict, *, dd_slack: float = 1.0) -> float | None:
    if not result.get("ok"):
        return None
    d_ret = float((result.get("delta") or {}).get("ret_pct_pts") or 0)
    d_dd = float((result.get("delta") or {}).get("dd_pct_pts") or 0)
    if d_dd > float(dd_slack):
        return None
    return d_ret - 0.35 * max(0.0, d_dd)


def run_per_symbol_oos(
    *,
    root: Path | None = None,
    is_frac: float = 0.60,
    split_date: str | None = None,
    target_vols: Sequence[float] = (0.10, 0.15, 0.20),
    bands: Sequence[float] = (0.0, 0.05),
) -> dict[str, Any]:
    root = Path(root or ".")
    hb = json.loads((root / "historical_backtest_latest.json").read_text(encoding="utf-8"))
    curve = hb.get("equity_curve") or []
    calendar = [str(r["date"])[:10] for r in curve]
    raw = reconstruct_symbol_day_pnls(hb.get("closed_pnls") or [], root=root, calendar=calendar)
    calibrated = calibrate_to_book(raw, curve)

    is_rows, oos_rows, split = split_equity_curve(curve, split_date=split_date, is_frac=is_frac)
    if not split.get("ok"):
        return {"ok": False, "reason": "split_failed", "split": split}

    is_days = {str(r["date"])[:10] for r in is_rows}
    oos_days = {str(r["date"])[:10] for r in oos_rows}
    is_sym = {d: calibrated[d] for d in is_days if d in calibrated}
    oos_sym = {d: calibrated[d] for d in oos_days if d in calibrated}

    grid = []
    best = None
    best_sc = None
    for tv in target_vols:
        for band in bands:
            r = run_per_symbol_tvs(
                is_rows, is_sym, root=root, target_vol=float(tv), tolerance_band=float(band),
            )
            sc = score_candidate(r)
            item = {
                "target_vol": float(tv),
                "tolerance_band": float(band),
                "score": sc,
                "delta": r.get("delta"),
                "tvs_shadow": r.get("tvs_shadow"),
            }
            grid.append(item)
            if sc is None:
                continue
            if best_sc is None or sc > best_sc:
                best_sc = sc
                best = item

    if best is None:
        # fallback: 15% / 5%
        best = {"target_vol": 0.15, "tolerance_band": 0.05, "score": None}

    params = {
        "target_vol": best["target_vol"],
        "tolerance_band": best["tolerance_band"],
        "max_leverage": 1.0,
        "hv_window": 20,
    }
    full = run_per_symbol_tvs(curve, calibrated, root=root, **params)
    is_eval = run_per_symbol_tvs(is_rows, is_sym, root=root, **params)
    oos_eval = run_per_symbol_tvs(oos_rows, oos_sym, root=root, **params)
    oos_pass = bool(
        oos_eval.get("ok")
        and float((oos_eval.get("delta") or {}).get("ret_pct_pts") or 0) >= 0
        and float((oos_eval.get("delta") or {}).get("dd_pct_pts") or 0) <= 0.5
    )
    return {
        "ok": True,
        "mode": "gemini_per_symbol_tvs_independent_oos",
        "disclaimer": full.get("disclaimer"),
        "split": split,
        "is_selection": {"selected": best, "grid": grid},
        "frozen_params": params,
        "full_sample": {
            "baseline": full.get("baseline"),
            "tvs_shadow": full.get("tvs_shadow"),
            "delta": full.get("delta"),
            "tracking": full.get("tracking"),
        },
        "is_eval": {
            "baseline": is_eval.get("baseline"),
            "tvs_shadow": is_eval.get("tvs_shadow"),
            "delta": is_eval.get("delta"),
        },
        "oos_eval": {
            "baseline": oos_eval.get("baseline"),
            "tvs_shadow": oos_eval.get("tvs_shadow"),
            "delta": oos_eval.get("delta"),
        },
        "oos_acceptance": {
            "pass": oos_pass,
            "rule": "OOS d_ret>=0 and d_dd<=0.5pt",
            "promote_path_a": False,
        },
        "path_a_meta": {
            "ret_pct": hb.get("ret_pct"),
            "max_dd_pct": hb.get("max_dd_pct"),
            "start": hb.get("start"),
            "end": hb.get("end"),
        },
    }
