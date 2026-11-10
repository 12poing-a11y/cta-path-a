# -*- coding: utf-8 -*-
"""A+B strategy capital blend: discrete weights on existing equity curves.

B context comes from strategy_indicator_ablation_latest.json (no re-run).
Paper research only — does not change entry_filter / paper_book.

Usage:
  python scripts/strategy_blend_grid.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "data" / "ablation" / "strategy_blend_latest.json"
ABLATION_PATH = ROOT / "data" / "ablation" / "strategy_indicator_ablation_latest.json"
TZ = ZoneInfo("Asia/Shanghai")

OBSERVE_ID = "proxy_observe_f_short_mom"
OBSERVE_CAP = 0.10
# Desk/全表 quality bar: drop negative ret or drawdown above cap.
MIN_RET_PCT = 0.0
MAX_DD_PCT = 15.0

DISCLAIMER = (
    "纸面研究：A=离散资金配比，B=消融上下文只读；"
    "代理曲线无 Path-A 成本/席位/ATR，跨族不可直接当实盘预期；"
    "观察袖套权重硬帽≤10%；全表仅保留收益>0且最大回撤≤15%的组合；"
    "不改 entry_filter / paper_book。"
)

# id → display name (fallback)
NAME_OF = {
    "path_a": "路径A",
    "proxy_cwft": "本地代理·CWFT",
    "proxy_long_short_cwft": "本地代理·Long/Short CWFT",
    "proxy_frontnext_st": "本地代理·C_frontnext&ShortTrend",
    OBSERVE_ID: "观察袖套·F+短动量",
}

PROXY_FULL = ("proxy_cwft", "proxy_long_short_cwft", "proxy_frontnext_st")


def _ew(ids: tuple[str, ...] | list[str], total: float) -> dict[str, float]:
    n = len(ids)
    if n == 0 or total <= 0:
        return {}
    w = total / n
    return {i: w for i in ids}


def default_schemes() -> list[dict[str, Any]]:
    """Fixed discrete weight grid (plan §默认组合宇宙)."""
    return [
        {
            "id": "path_a_100",
            "label": "100% 路径A",
            "weights": {"path_a": 1.0},
            "risk_note": "",
        },
        {
            "id": "pa95_obs5",
            "label": "路径A 95% + 观察袖套 5%",
            "weights": {"path_a": 0.95, OBSERVE_ID: 0.05},
            "risk_note": "",
        },
        {
            "id": "pa90_obs10",
            "label": "路径A 90% + 观察袖套 10%",
            "weights": {"path_a": 0.90, OBSERVE_ID: 0.10},
            "risk_note": "",
        },
        {
            "id": "pa70_proxy30",
            "label": "路径A 70% + 三完整代理等权 30%",
            "weights": {"path_a": 0.70, **_ew(PROXY_FULL, 0.30)},
            "risk_note": "",
        },
        {
            "id": "pa60_proxy30_obs10",
            "label": "路径A 60% + 三完整代理 30% + 观察袖套 10%",
            "weights": {"path_a": 0.60, **_ew(PROXY_FULL, 0.30), OBSERVE_ID: 0.10},
            "risk_note": "",
        },
        {
            "id": "proxy4_ew",
            "label": "四代理（含观察）等权",
            "weights": _ew((*PROXY_FULL, OBSERVE_ID), 1.0),
            "risk_note": "高风险研究对照：无路径A锚、观察袖套占25%>10%帽 → 剔除",
        },
    ]


def validate_weights(weights: dict[str, float], *, observe_cap: float = OBSERVE_CAP) -> str | None:
    """Return error string if invalid; None if ok."""
    if not weights:
        return "空权重"
    total = sum(float(v) for v in weights.values())
    if abs(total - 1.0) > 1e-6:
        return f"权重和={total:.6f}≠1"
    for k, v in weights.items():
        if float(v) < -1e-12:
            return f"{k} 权重为负"
    obs = float(weights.get(OBSERVE_ID) or 0.0)
    if obs > observe_cap + 1e-12:
        return f"观察袖套权重 {obs:.0%}>{observe_cap:.0%}帽"
    return None


def equity_to_returns(equity: pd.Series) -> pd.Series:
    eq = pd.to_numeric(equity, errors="coerce")
    return eq.pct_change().dropna()


def blend_daily_returns(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted sum of aligned daily returns; columns must cover weights keys."""
    cols = [c for c in weights if c in returns.columns]
    if not cols:
        return pd.Series(dtype=float)
    sub = returns[cols].dropna(how="any")
    if sub.empty:
        return pd.Series(dtype=float)
    w = pd.Series({c: float(weights[c]) / sum(float(weights[x]) for x in cols) for c in cols})
    return (sub * w).sum(axis=1)


def metrics_from_returns(rets: pd.Series) -> dict[str, Any]:
    if rets is None or rets.empty:
        return {"ret_pct": None, "max_dd_pct": None, "calmar": None, "n_days": 0}
    eq = (1.0 + rets).cumprod()
    ret_pct = float(eq.iloc[-1] / eq.iloc[0] - 1.0) * 100.0 if len(eq) else None
    # peak-to-trough on equity index starting at 1
    peak = eq.cummax()
    dd = (eq / peak - 1.0) * 100.0
    max_dd_pct = float(abs(dd.min())) if len(dd) else None
    calmar = None
    if ret_pct is not None and max_dd_pct and max_dd_pct > 1e-9:
        calmar = round(ret_pct / max_dd_pct, 3)
    elif ret_pct is not None and (max_dd_pct is None or max_dd_pct <= 1e-9):
        calmar = None
    return {
        "ret_pct": None if ret_pct is None else round(ret_pct, 3),
        "max_dd_pct": None if max_dd_pct is None else round(max_dd_pct, 3),
        "calmar": calmar,
        "n_days": int(len(rets)),
        "start": str(rets.index.min().date()) if len(rets) else None,
        "end": str(rets.index.max().date()) if len(rets) else None,
    }


def load_curve_map(root: Path) -> dict[str, pd.DataFrame]:
    """Load equity DataFrames for blend universe via registry + known files."""
    from desk.loaders import equity_curve_df, load_json
    from desk.strategies.registry import all_strategies

    want = {"path_a", *PROXY_FULL, OBSERVE_ID}
    out: dict[str, pd.DataFrame] = {}
    for spec in all_strategies(root):
        if spec.id not in want:
            continue
        path = spec.resolve_curve(root)
        if path is None or not path.is_file():
            continue
        payload = load_json(path)
        df = equity_curve_df(payload)
        if not df.empty and "equity" in df.columns:
            out[spec.id] = df
    # Fallback paths if registry miss
    fallback = {
        "path_a": root / "historical_backtest_latest.json",
        "proxy_cwft": root / "external" / "strategies" / "proxy_cwft.json",
        "proxy_long_short_cwft": root / "external" / "strategies" / "proxy_long_short_cwft.json",
        "proxy_frontnext_st": root / "external" / "strategies" / "proxy_frontnext_st.json",
        OBSERVE_ID: root / "external" / "strategies" / f"{OBSERVE_ID}.json",
    }
    for sid, path in fallback.items():
        if sid in out or not path.is_file():
            continue
        df = equity_curve_df(load_json(path))
        if not df.empty and "equity" in df.columns:
            out[sid] = df
    return out


def aligned_returns(curves: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Inner-join daily returns across strategies."""
    from desk.loaders import align_curves

    aligned = align_curves(curves, normalize=False, equity_col="equity")
    if aligned.empty:
        return pd.DataFrame()
    # Drop rows with any NaN so weights stay on common calendar
    aligned = aligned.dropna(how="any")
    if aligned.empty or len(aligned) < 2:
        return pd.DataFrame()
    rets = aligned.pct_change().dropna(how="any")
    return rets


def run_blend_grid(
    returns: pd.DataFrame,
    schemes: list[dict[str, Any]] | None = None,
    *,
    observe_cap: float = OBSERVE_CAP,
) -> list[dict[str, Any]]:
    schemes = schemes if schemes is not None else default_schemes()
    rows: list[dict[str, Any]] = []
    for sch in schemes:
        wid = str(sch["id"])
        label = str(sch["label"])
        weights = {str(k): float(v) for k, v in (sch.get("weights") or {}).items()}
        risk_note = str(sch.get("risk_note") or "")
        err = validate_weights(weights, observe_cap=observe_cap)
        if err:
            rows.append(
                {
                    "blend_id": wid,
                    "label": label,
                    "weights": weights,
                    "weights_zh": _weights_zh(weights),
                    "ok": False,
                    "error": err,
                    "risk_note": risk_note or err,
                    "ret_pct": None,
                    "max_dd_pct": None,
                    "calmar": None,
                    "n_days": 0,
                }
            )
            continue
        missing = [k for k in weights if k not in returns.columns]
        if missing:
            rows.append(
                {
                    "blend_id": wid,
                    "label": label,
                    "weights": weights,
                    "weights_zh": _weights_zh(weights),
                    "ok": False,
                    "error": f"缺曲线: {','.join(missing)}",
                    "risk_note": risk_note,
                    "ret_pct": None,
                    "max_dd_pct": None,
                    "calmar": None,
                    "n_days": 0,
                }
            )
            continue
        blended = blend_daily_returns(returns, weights)
        m = metrics_from_returns(blended)
        rows.append(
            {
                "blend_id": wid,
                "label": label,
                "weights": weights,
                "weights_zh": _weights_zh(weights),
                "ok": True,
                "error": "",
                "risk_note": risk_note,
                **m,
            }
        )
    return rows


def _weights_zh(weights: dict[str, float]) -> str:
    parts = []
    for k, v in weights.items():
        parts.append(f"{NAME_OF.get(k, k)} {v:.0%}")
    return " + ".join(parts)


def load_b_context(root: Path) -> dict[str, Any]:
    path = root / "data" / "ablation" / "strategy_indicator_ablation_latest.json"
    if not path.is_file():
        return {
            "available": False,
            "note": "缺少消融快照，请先跑 python scripts/strategy_indicator_ablation.py",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "note": "消融 JSON 无法解析"}
    summary = data.get("summary") or {}
    return {
        "available": True,
        "asof": data.get("asof"),
        "grid_mode": data.get("grid_mode"),
        "top_pairs_by_ret": (summary.get("top_pairs_by_ret") or [])[:5],
        "top_pairs_by_calmar": (summary.get("top_pairs_by_calmar") or [])[:5],
        "best_full_strategies": (summary.get("best_full_strategies") or [])[:5],
    }


def passes_quality(
    row: dict[str, Any],
    *,
    min_ret_pct: float = MIN_RET_PCT,
    max_dd_pct: float = MAX_DD_PCT,
) -> bool:
    """Keep only successful blends with positive ret and drawdown within cap."""
    if not row.get("ok"):
        return False
    try:
        ret = float(row["ret_pct"])
        dd = float(row["max_dd_pct"])
    except (TypeError, ValueError, KeyError):
        return False
    if ret <= min_ret_pct:
        return False
    if dd > max_dd_pct:
        return False
    return True


def filter_quality_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if passes_quality(r)]


def _rank_ok(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    ok = [r for r in filter_quality_rows(rows) if r.get(key) is not None]
    return sorted(ok, key=lambda r: float(r[key]), reverse=True)


def build_payload(root: Path) -> dict[str, Any]:
    curves = load_curve_map(root)
    rets = aligned_returns(curves)
    rows_all = run_blend_grid(rets)
    rows = filter_quality_rows(rows_all)
    dropped = [
        {
            "blend_id": r.get("blend_id"),
            "label": r.get("label"),
            "ret_pct": r.get("ret_pct"),
            "max_dd_pct": r.get("max_dd_pct"),
            "ok": r.get("ok"),
            "error": r.get("error") or "",
            "reason": (
                r.get("error")
                if not r.get("ok")
                else (
                    "负收益"
                    if (r.get("ret_pct") is not None and float(r["ret_pct"]) <= MIN_RET_PCT)
                    else (f"回撤>{MAX_DD_PCT:g}%" if r.get("max_dd_pct") is not None else "指标缺失")
                )
            ),
        }
        for r in rows_all
        if not passes_quality(r)
    ]
    by_cal = _rank_ok(rows_all, "calmar")
    by_ret = _rank_ok(rows_all, "ret_pct")
    b_ctx = load_b_context(root)
    return {
        "ok": bool(by_cal or by_ret),
        "asof": datetime.now(tz=TZ).strftime("%Y-%m-%d %H:%M"),
        "disclaimer": DISCLAIMER,
        "observe_id": OBSERVE_ID,
        "observe_cap": OBSERVE_CAP,
        "min_ret_pct": MIN_RET_PCT,
        "max_dd_pct_cap": MAX_DD_PCT,
        "curves_loaded": sorted(curves.keys()),
        "n_common_days": int(len(rets)) if not rets.empty else 0,
        "b_context": b_ctx,
        "n_rows": len(rows),
        "n_dropped": len(dropped),
        "rows": rows,
        "dropped": dropped,
        "best_by_calmar": [
            {
                "blend_id": r["blend_id"],
                "label": r["label"],
                "weights_zh": r["weights_zh"],
                "ret_pct": r["ret_pct"],
                "max_dd_pct": r["max_dd_pct"],
                "calmar": r["calmar"],
            }
            for r in by_cal[:5]
        ],
        "best_by_ret": [
            {
                "blend_id": r["blend_id"],
                "label": r["label"],
                "weights_zh": r["weights_zh"],
                "ret_pct": r["ret_pct"],
                "max_dd_pct": r["max_dd_pct"],
                "calmar": r["calmar"],
            }
            for r in by_ret[:5]
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Strategy capital blend grid (A after B)")
    ap.parse_args()
    payload = build_payload(ROOT)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[blend] wrote {OUT_PATH.relative_to(ROOT)} rows={payload.get('n_rows')} days={payload.get('n_common_days')}")
    print("[blend] curves:", payload.get("curves_loaded"))
    if not payload.get("b_context", {}).get("available"):
        print("[blend] B context:", payload.get("b_context", {}).get("note"))
    print("[blend] best by Calmar:")
    for r in payload.get("best_by_calmar") or []:
        print(f"  {r['label']}: calmar={r['calmar']} ret={r['ret_pct']} dd={r['max_dd_pct']}")
    print("[blend] best by ret:")
    for r in payload.get("best_by_ret") or []:
        print(f"  {r['label']}: ret={r['ret_pct']} calmar={r['calmar']} dd={r['max_dd_pct']}")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
