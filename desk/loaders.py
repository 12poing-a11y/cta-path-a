# -*- coding: utf-8 -*-
"""Load strategy JSON artifacts into desk-friendly frames / KPI dicts."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from desk.strategies.base import Availability, StrategySpec
from desk.strategies.registry import REPO_ROOT, all_strategies

# Ensure repo root imports (option_hedge, etc.) work when streamlit cwd varies
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def strategy_availability(spec: StrategySpec, root: Path | None = None) -> Availability:
    root = root or REPO_ROOT
    if spec.placeholder and spec.loader is None:
        curve = spec.resolve_curve(root)
        if curve is None or not curve.is_file():
            return "placeholder"
    data = load_strategy_payload(spec, root)
    if data is None or data.get("_desk_missing"):
        if spec.placeholder:
            return "placeholder"
        return "missing"
    if spec.placeholder or data.get("placeholder"):
        # Explicit track slots with no report numbers yet.
        has_metric = any(
            data.get(k) is not None
            for k in ("ret_ann_pct", "ret_pct", "sharpe", "calmar", "max_dd_pct", "equity_curve")
        )
        if not has_metric:
            return "placeholder"
    curve = data.get("equity_curve")
    if isinstance(curve, list) and len(curve) > 0:
        return "ready"
    # benchmark / KPI-only artifacts
    if _extract_kpis(data, spec.id):
        return "kpi_only"
    if spec.placeholder:
        return "placeholder"
    return "missing"


def load_strategy_payload(spec: StrategySpec, root: Path | None = None) -> dict[str, Any] | None:
    root = root or REPO_ROOT
    if spec.loader is not None:
        return spec.loader(root, spec)
    path = spec.resolve_curve(root)
    if path is None:
        return None
    data = load_json(path)
    if data is None:
        return None
    out = dict(data)
    try:
        out["_desk_source"] = str(path.relative_to(root))
    except ValueError:
        out["_desk_source"] = str(path)
    return out


def equity_curve_df(data: dict[str, Any] | None) -> pd.DataFrame:
    if not data:
        return pd.DataFrame()
    rows = data.get("equity_curve") or []
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    # Keep one row per calendar day (proxy dumps sometimes repeat the first day).
    df = df.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if "equity" in df.columns:
        df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    if "dd_pct" in df.columns:
        df["dd_pct"] = pd.to_numeric(df["dd_pct"], errors="coerce")
    if "pnl" in df.columns:
        df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    # optional gross equity field if engines add it later
    for col in ("equity_gross", "gross_equity"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def sleeve_pnl_series(data: dict[str, Any] | None) -> pd.DataFrame:
    """Cumulative sleeve PnL from equity_curve sleeve_pnl points if present."""
    if not data:
        return pd.DataFrame()
    rows = data.get("equity_curve") or []
    if not rows:
        return pd.DataFrame()
    out_rows = []
    for r in rows:
        sp = r.get("sleeve_pnl")
        if not isinstance(sp, dict):
            continue
        item = {"date": r.get("date")}
        item.update({k: float(v) for k, v in sp.items()})
        out_rows.append(item)
    if not out_rows:
        # fall back to window KPI sleeve totals (single row)
        win = (data.get("window") or {}).get("benchmark") or data.get("full_after_250_warmup") or {}
        pnl = win.get("pnl_by_sleeve")
        if isinstance(pnl, dict):
            return pd.DataFrame([{"sleeve": k, "pnl": float(v)} for k, v in pnl.items()])
        return pd.DataFrame()
    df = pd.DataFrame(out_rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _extract_kpis(data: dict[str, Any], strategy_id: str = "") -> dict[str, Any]:
    """Normalize KPI fields across Path-A backtest and benchmark JSON."""
    kpis: dict[str, Any] = {}
    if strategy_id == "benchmark" or "window" in data:
        win = (data.get("window") or {}).get("benchmark") or {}
        if win:
            kpis = {
                "start": win.get("start"),
                "end": win.get("end"),
                "trade_days": win.get("trade_days"),
                "equity_end": win.get("equity_end"),
                "ret_pct": win.get("ret_pct"),
                "max_dd_pct": win.get("max_dd_pct"),
                "cost_yuan": win.get("cost_yuan"),
                "pnl_by_sleeve": win.get("pnl_by_sleeve"),
                "scope": "window",
            }
        # if curve exists, prefer curve-end stats when present at top level
        if data.get("equity_curve") and data.get("ret_pct") is not None:
            kpis.update(
                {
                    "ret_pct": data.get("ret_pct", kpis.get("ret_pct")),
                    "max_dd_pct": data.get("max_dd_pct", kpis.get("max_dd_pct")),
                    "equity_end": data.get("equity_end", kpis.get("equity_end")),
                }
            )
    else:
        for key in (
            "start",
            "end",
            "trade_days",
            "equity_start",
            "equity_end",
            "ret_pct",
            "ret_ann_pct",
            "max_dd_pct",
            "gross_ret_pct",
            "gross_max_dd_pct",
            "sharpe",
            "calmar",
            "week_ret_pct",
            "ytd_ret_pct",
            "cost_yuan",
            "premium_yuan",
            "hedge_payoff_yuan",
            "hedge_net_yuan",
            "option_hedge",
            "premium_atr_mult",
            "strike_atr_mult",
            "family",
            "track_source",
            "proxy_of",
        ):
            if key in data and data[key] is not None:
                kpis[key] = data[key]
    if data.get("_desk_source"):
        kpis["source"] = data["_desk_source"]
    return kpis


def strategy_kpis(spec: StrategySpec, root: Path | None = None) -> dict[str, Any]:
    data = load_strategy_payload(spec, root)
    if not data or data.get("_desk_missing"):
        return {}
    return _extract_kpis(data, spec.id)


def load_l1_report(root: Path | None = None) -> dict[str, Any] | None:
    root = root or REPO_ROOT
    return load_json(root / "l1_report.json")


def load_universe(root: Path | None = None) -> dict[str, Any] | None:
    root = root or REPO_ROOT
    return load_json(root / "universe.json")


def option_hedge_defaults(root: Path | None = None) -> dict[str, float]:
    uni = load_universe(root) or {}
    oh = ((uni.get("observe") or {}).get("option_hedge")) or {}
    return {
        "premium_atr_mult": float(oh.get("premium_atr_mult") if oh.get("premium_atr_mult") is not None else 0.6),
        "strike_atr_mult": float(oh.get("strike_atr_mult") if oh.get("strike_atr_mult") is not None else 0.0),
    }


def registry_status_table(root: Path | None = None) -> pd.DataFrame:
    root = root or REPO_ROOT
    rows = []
    for spec in all_strategies(root):
        avail = strategy_availability(spec, root)
        curve = spec.resolve_curve(root)
        signal = spec.resolve_signal(root)
        rows.append(
            {
                "id": spec.id,
                "name": spec.name,
                "tags": ", ".join(spec.tags),
                "status": avail,
                "curve_file": str(curve.relative_to(root)) if curve and curve.is_file() else (str(spec.curve_path) if spec.curve_path else "—"),
                "curve_exists": bool(curve and curve.is_file()),
                "signal_file": str(signal.relative_to(root)) if signal and signal.is_file() else (str(spec.signal_path) if spec.signal_path else "—"),
                "description": spec.description,
            }
        )
    return pd.DataFrame(rows)


def align_curves(
    curves: dict[str, pd.DataFrame],
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    normalize: bool = False,
    equity_col: str = "equity",
) -> pd.DataFrame:
    """Outer-join equity series by date; optional normalize first point to 100."""
    pieces: list[pd.DataFrame] = []
    for sid, df in curves.items():
        if df is None or df.empty or equity_col not in df.columns:
            continue
        sub = df[["date", equity_col]].copy()
        sub["date"] = pd.to_datetime(sub["date"], errors="coerce")
        sub[equity_col] = pd.to_numeric(sub[equity_col], errors="coerce")
        sub = sub.dropna(subset=["date", equity_col])
        if start is not None:
            sub = sub[sub["date"] >= pd.Timestamp(start)]
        if end is not None:
            sub = sub[sub["date"] <= pd.Timestamp(end)]
        if sub.empty:
            continue
        sub = sub.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        piece = sub.rename(columns={equity_col: str(sid)}).set_index("date")
        # Belt-and-suspenders: index must be unique for outer join.
        piece = piece[~piece.index.duplicated(keep="last")]
        if normalize:
            first = float(piece.iloc[0, 0])
            if first != 0:
                piece = piece / first * 100.0
        pieces.append(piece)
    if not pieces:
        return pd.DataFrame()
    out = pieces[0]
    for piece in pieces[1:]:
        out = out.join(piece, how="outer")
    return out.sort_index()


def drawdown_from_equity(equity: pd.Series) -> pd.Series:
    if equity.empty:
        return equity
    peak = equity.cummax()
    return (peak - equity) / peak.replace(0, pd.NA) * 100.0
