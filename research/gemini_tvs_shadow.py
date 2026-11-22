# -*- coding: utf-8 -*-
"""Gemini/HTML P0 Dual-Track TVS shadow overlay (research only).

Applies to an existing Path-A equity curve:
- Downside HV (20d semi-deviation, annualized) → target leverage
- Optional IV forward warn from .cache/akshare/option_iv
- ±5% leverage tolerance band
- Scale T+1 PnL only (no lookahead)

Does not modify position_rules / paper_book / seats.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def downside_hv_ann(returns: Sequence[float], *, window: int = 20) -> float | None:
    """Annualized downside semi-deviation of simple returns (negatives only)."""
    xs = [float(r) for r in returns[-window:] if _finite(r) is not None]
    if len(xs) < max(5, window // 2):
        return None
    neg = [r for r in xs if r < 0]
    if len(neg) < 3:
        # Mild regime: use small floor from full sample std of negatives-or-zero
        neg = [min(r, 0.0) for r in xs]
    mu = 0.0  # semi-deviation about 0
    var = sum((r - mu) ** 2 for r in neg) / max(len(neg), 1)
    hv = math.sqrt(max(var, 0.0)) * math.sqrt(252.0)
    return hv if hv > 1e-12 else None


def load_iv_series(root: Path, code: str) -> dict[str, float]:
    """Map YYYY-MM-DD -> IV (fraction) from akshare option_iv cache."""
    folder = Path(root) / ".cache" / "akshare" / "option_iv" / str(code).upper()
    out: dict[str, float] = {}
    if not folder.is_dir():
        return out
    for f in folder.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("missing"):
            continue
        iv = _finite(d.get("iv"))
        raw = str(d.get("date") or f.stem)
        if len(raw) == 8 and raw.isdigit():
            day = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        else:
            day = raw[:10]
        if iv is not None and iv > 0 and len(day) == 10:
            out[day] = iv
    return out


def iv_percentile(history: Sequence[float], current: float) -> float | None:
    xs = [float(x) for x in history if _finite(x) is not None]
    if len(xs) < 20:
        return None
    return sum(1 for x in xs if x <= current) / len(xs)


def apply_tolerance(prev: float, target: float, band: float = 0.05) -> float:
    if abs(target - prev) <= float(band):
        return prev
    return target


def max_dd_pct(equity: Sequence[float]) -> float:
    if not equity:
        return 0.0
    peak = float(equity[0])
    mdd = 0.0
    for e in equity:
        peak = max(peak, float(e))
        if peak > 0:
            mdd = max(mdd, (peak - float(e)) / peak)
    return round(mdd * 100.0, 3)


def run_tvs_overlay(
    equity_curve: Sequence[dict],
    *,
    root: Path | None = None,
    target_vol: float = 0.15,
    hv_window: int = 20,
    max_leverage: float = 1.0,
    iv_warn_pctile: float = 0.90,
    iv_compress: float = 0.50,
    tolerance_band: float = 0.05,
    iv_codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Shadow TVS on Path-A day PnL path."""
    root = Path(root or ".")
    rows = [r for r in equity_curve if r.get("date")]
    if len(rows) < hv_window + 5:
        return {"ok": False, "reason": "short_curve"}

    # Preload IV for codes that appear in the book + optional extras
    codes_seen: set[str] = set()
    for r in rows:
        for c in r.get("codes") or []:
            codes_seen.add(str(c).upper())
    for c in iv_codes or ():
        codes_seen.add(str(c).upper())
    iv_map = {c: load_iv_series(root, c) for c in sorted(codes_seen)}

    base_eq0 = float(rows[0].get("equity") or 0) - float(rows[0].get("pnl") or 0)
    if base_eq0 <= 0:
        base_eq0 = float(rows[0].get("equity") or 200000.0)

    rets: list[float] = []
    lev = 1.0
    eq_base = base_eq0
    eq_tvs = base_eq0
    curve_base = [eq_base]
    curve_tvs = [eq_tvs]
    lev_path: list[dict] = []
    n_adjust = 0
    n_iv_warn = 0
    turnover = 0.0  # sum |Δlev|

    for i, r in enumerate(rows):
        day = str(r["date"])[:10]
        pnl = float(r.get("pnl") or 0.0)
        # Strategy simple return vs prior equity
        prev_eq = curve_base[-1]
        ret = pnl / prev_eq if prev_eq else 0.0
        # Leverage applied is yesterday's decision (T+1)
        applied = lev
        eq_base = eq_base + pnl
        eq_tvs = eq_tvs + pnl * applied
        curve_base.append(eq_base)
        curve_tvs.append(eq_tvs)
        rets.append(ret)

        # Update leverage for next day using info through today
        hv = downside_hv_ann(rets, window=hv_window)
        if hv is None:
            target = 1.0
            iv_mult = 1.0
            iv_note = "hv_warmup"
        else:
            target = min(float(max_leverage), float(target_vol) / hv)
            target = max(0.0, target)
            # IV forward warn: any held code with IV pctile high
            iv_mult = 1.0
            iv_note = ""
            held = [str(c).upper() for c in (r.get("codes") or [])]
            for code in held:
                series = iv_map.get(code) or {}
                # only IV dated <= day
                hist_days = sorted(d for d in series if d <= day)
                if len(hist_days) < 20:
                    continue
                cur = series[hist_days[-1]]
                hist_vals = [series[d] for d in hist_days[-60:]]
                pct = iv_percentile(hist_vals, cur)
                # also compare IV vs recent HV proxy (strategy hv as rough)
                if pct is not None and pct >= float(iv_warn_pctile) and cur > hv:
                    iv_mult = float(iv_compress)
                    iv_note = f"iv_warn:{code}:pct={pct:.2f}"
                    n_iv_warn += 1
                    break
            target *= iv_mult

        new_lev = apply_tolerance(lev, target, band=tolerance_band)
        if abs(new_lev - lev) > 1e-12:
            n_adjust += 1
            turnover += abs(new_lev - lev)
        lev_path.append({
            "date": day,
            "applied_lev": round(applied, 4),
            "target_lev": round(target, 4),
            "next_lev": round(new_lev, 4),
            "downside_hv": None if hv is None else round(hv, 6),
            "iv_note": iv_note,
        })
        lev = new_lev

    def _ret_pct(curve: list[float]) -> float:
        if not curve or curve[0] <= 0:
            return 0.0
        return round(100.0 * (curve[-1] / curve[0] - 1.0), 3)

    return {
        "ok": True,
        "mode": "gemini_p0_tvs_shadow",
        "disclaimer": (
            "Gemini/HTML P0 影子对照：仅把 Dual-Track TVS 叠在已有 Path-A 日PnL上；"
            "不改 position_rules / paper_book / seats。"
        ),
        "params": {
            "target_vol": target_vol,
            "hv_window": hv_window,
            "max_leverage": max_leverage,
            "iv_warn_pctile": iv_warn_pctile,
            "iv_compress": iv_compress,
            "tolerance_band": tolerance_band,
        },
        "window": {"start": rows[0]["date"], "end": rows[-1]["date"], "n_days": len(rows)},
        "baseline": {
            "equity_start": round(curve_base[0], 2),
            "equity_end": round(curve_base[-1], 2),
            "ret_pct": _ret_pct(curve_base),
            "max_dd_pct": max_dd_pct(curve_base),
        },
        "tvs_shadow": {
            "equity_start": round(curve_tvs[0], 2),
            "equity_end": round(curve_tvs[-1], 2),
            "ret_pct": _ret_pct(curve_tvs),
            "max_dd_pct": max_dd_pct(curve_tvs),
            "n_leverage_adjust": n_adjust,
            "leverage_turnover": round(turnover, 4),
            "n_iv_warn": n_iv_warn,
            "final_lev": round(lev, 4),
        },
        "delta": {
            "ret_pct_pts": round(_ret_pct(curve_tvs) - _ret_pct(curve_base), 3),
            "dd_pct_pts": round(max_dd_pct(curve_tvs) - max_dd_pct(curve_base), 3),
        },
        "leverage_tail": lev_path[-8:],
    }


def run_from_historical_backtest(root: Path | None = None, **kwargs) -> dict[str, Any]:
    root = Path(root or ".")
    path = root / "historical_backtest_latest.json"
    hb = json.loads(path.read_text(encoding="utf-8"))
    out = run_tvs_overlay(hb.get("equity_curve") or [], root=root, **kwargs)
    out["source"] = str(path)
    out["path_a_meta"] = {
        "ret_pct": hb.get("ret_pct"),
        "max_dd_pct": hb.get("max_dd_pct"),
        "start": hb.get("start"),
        "end": hb.get("end"),
        "mode": hb.get("mode"),
    }
    return out


def split_equity_curve(
    equity_curve: Sequence[dict],
    *,
    split_date: str | None = None,
    is_frac: float = 0.60,
) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Split Path-A equity curve into IS / OOS. No overlap."""
    rows = [r for r in equity_curve if r.get("date")]
    if len(rows) < 40:
        return [], [], {"ok": False, "reason": "short_curve", "n": len(rows)}
    if split_date:
        cut = str(split_date)[:10]
        is_rows = [r for r in rows if str(r["date"])[:10] <= cut]
        oos_rows = [r for r in rows if str(r["date"])[:10] > cut]
    else:
        if not 0.2 <= float(is_frac) <= 0.8:
            raise ValueError("is_frac must be in [0.2, 0.8]")
        n_is = max(20, int(round(len(rows) * float(is_frac))))
        n_is = min(n_is, len(rows) - 20)
        is_rows = list(rows[:n_is])
        oos_rows = list(rows[n_is:])
        cut = str(is_rows[-1]["date"])[:10]
    meta = {
        "ok": len(is_rows) >= 20 and len(oos_rows) >= 20,
        "split_date": cut,
        "n_is": len(is_rows),
        "n_oos": len(oos_rows),
        "is_start": str(is_rows[0]["date"])[:10] if is_rows else None,
        "is_end": str(is_rows[-1]["date"])[:10] if is_rows else None,
        "oos_start": str(oos_rows[0]["date"])[:10] if oos_rows else None,
        "oos_end": str(oos_rows[-1]["date"])[:10] if oos_rows else None,
    }
    return is_rows, oos_rows, meta


def score_is_candidate(result: dict, *, dd_slack: float = 1.0) -> float | None:
    """IS selection score: prefer ret lift; penalize DD worsening beyond slack."""
    if not result.get("ok"):
        return None
    base = result.get("baseline") or {}
    tvs = result.get("tvs_shadow") or {}
    d_ret = float(tvs.get("ret_pct") or 0) - float(base.get("ret_pct") or 0)
    d_dd = float(tvs.get("max_dd_pct") or 0) - float(base.get("max_dd_pct") or 0)
    if d_dd > float(dd_slack):
        return None  # ineligible
    return d_ret - 0.35 * max(0.0, d_dd)


def select_params_on_is(
    is_rows: Sequence[dict],
    *,
    root: Path,
    target_vols: Sequence[float] = (0.10, 0.15, 0.20),
    bands: Sequence[float] = (0.0, 0.05),
    dd_slack: float = 1.0,
    fixed_kwargs: dict | None = None,
) -> dict[str, Any]:
    """Grid-search TVS params on IS only; freeze winner for OOS."""
    fixed_kwargs = dict(fixed_kwargs or {})
    grid = []
    best = None
    best_score = None
    for tv in target_vols:
        for band in bands:
            r = run_tvs_overlay(
                is_rows,
                root=root,
                target_vol=float(tv),
                tolerance_band=float(band),
                **fixed_kwargs,
            )
            sc = score_is_candidate(r, dd_slack=dd_slack)
            item = {
                "target_vol": float(tv),
                "tolerance_band": float(band),
                "score": sc,
                "eligible": sc is not None,
                "baseline": r.get("baseline"),
                "tvs_shadow": r.get("tvs_shadow"),
                "delta": r.get("delta"),
            }
            grid.append(item)
            if sc is None:
                continue
            if best_score is None or sc > best_score:
                best_score = sc
                best = item
    return {
        "ok": best is not None,
        "selected": best,
        "grid": grid,
        "selection_rule": "max(d_ret - 0.35*max(0,d_dd)) with d_dd<=dd_slack",
        "dd_slack": dd_slack,
    }


def run_independent_oos(
    equity_curve: Sequence[dict],
    *,
    root: Path | None = None,
    split_date: str | None = None,
    is_frac: float = 0.60,
    target_vols: Sequence[float] = (0.10, 0.15, 0.20),
    bands: Sequence[float] = (0.0, 0.05),
    dd_slack: float = 1.0,
) -> dict[str, Any]:
    """IS select → freeze → OOS evaluate. OOS overlay restarts leverage at 1.0."""
    root = Path(root or ".")
    is_rows, oos_rows, split_meta = split_equity_curve(
        equity_curve, split_date=split_date, is_frac=is_frac,
    )
    if not split_meta.get("ok"):
        return {
            "ok": False,
            "reason": "split_failed",
            "split": split_meta,
            "mode": "gemini_p0_tvs_independent_oos",
        }
    selection = select_params_on_is(
        is_rows,
        root=root,
        target_vols=target_vols,
        bands=bands,
        dd_slack=dd_slack,
    )
    if not selection.get("ok"):
        return {
            "ok": False,
            "reason": "no_eligible_is_params",
            "split": split_meta,
            "is_selection": selection,
            "mode": "gemini_p0_tvs_independent_oos",
        }
    sel = selection["selected"]
    params = {
        "target_vol": sel["target_vol"],
        "tolerance_band": sel["tolerance_band"],
        "max_leverage": 1.0,
        "hv_window": 20,
        "iv_warn_pctile": 0.90,
        "iv_compress": 0.50,
    }
    # Full-sample peek (contaminated) for reference only
    full_peek = run_tvs_overlay(equity_curve, root=root, **params)
    oos = run_tvs_overlay(oos_rows, root=root, **params)
    is_frozen = run_tvs_overlay(is_rows, root=root, **params)

    oos_pass = bool(
        oos.get("ok")
        and float((oos.get("delta") or {}).get("ret_pct_pts") or 0) >= 0
        and float((oos.get("delta") or {}).get("dd_pct_pts") or 0) <= 0.5
    )
    return {
        "ok": True,
        "mode": "gemini_p0_tvs_independent_oos",
        "disclaimer": (
            "独立 OOS：仅在 IS 选参并冻结；OOS 段杠杆从 1.0 重启、只用当日及以前信息；"
            "full_sample_peek 仅对照、不作验收；不改 Path-A / paper_book / seats。"
        ),
        "split": split_meta,
        "is_selection": selection,
        "frozen_params": params,
        "is_frozen_eval": {
            "baseline": is_frozen.get("baseline"),
            "tvs_shadow": is_frozen.get("tvs_shadow"),
            "delta": is_frozen.get("delta"),
        },
        "oos_eval": {
            "baseline": oos.get("baseline"),
            "tvs_shadow": oos.get("tvs_shadow"),
            "delta": oos.get("delta"),
        },
        "full_sample_peek_contaminated": {
            "baseline": full_peek.get("baseline"),
            "tvs_shadow": full_peek.get("tvs_shadow"),
            "delta": full_peek.get("delta"),
            "note": "contaminated_not_for_acceptance",
        },
        "oos_acceptance": {
            "pass": oos_pass,
            "rule": "OOS d_ret>=0 and d_dd<=0.5pt vs OOS baseline",
            "promote_path_a": False,
        },
    }


def run_independent_oos_from_historical(
    root: Path | None = None,
    **kwargs,
) -> dict[str, Any]:
    root = Path(root or ".")
    path = root / "historical_backtest_latest.json"
    hb = json.loads(path.read_text(encoding="utf-8"))
    out = run_independent_oos(hb.get("equity_curve") or [], root=root, **kwargs)
    out["source"] = str(path)
    out["path_a_meta"] = {
        "ret_pct": hb.get("ret_pct"),
        "max_dd_pct": hb.get("max_dd_pct"),
        "start": hb.get("start"),
        "end": hb.get("end"),
        "mode": hb.get("mode"),
    }
    return out
