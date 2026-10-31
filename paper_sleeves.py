# -*- coding: utf-8 -*-
"""Complementary paper sleeves (Stage-1): Donchian / chop MR / vol-adj XS mom.

Outputs land in ``external/strategies/`` and register via desk extra specs.
Uses the same Path-A universe fetch as ``proxy_cta.py``. Not live trading.

Usage:
  python paper_sleeves.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def load_cost_bps(root: Path | None = None) -> float:
    p = (root or ROOT) / "research_cost.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return float((raw.get("sleeve_proxy") or {}).get("cost_bps_one_way") or 3.0)
    except Exception:
        return 3.0


def path_a_momentum_signal_series(
    bars: pd.DataFrame,
    *,
    min_r20: float = 3.0,
    min_r60: float = 5.0,
) -> pd.Series:
    """Path-A style same-sign momentum; uses only past closes (shift)."""
    close = bars["close"].astype(float)
    r20 = (close / close.shift(20) - 1.0) * 100.0
    r60 = (close / close.shift(60) - 1.0) * 100.0
    same = np.sign(r20) == np.sign(r60)
    strong = (r20.abs() >= min_r20) & (r60.abs() >= min_r60)
    raw = np.where(same & strong, np.sign(r20).fillna(0.0), 0.0)
    return pd.Series(raw, index=bars.index).fillna(0).astype(int)


def donchian_signal_series(bars: pd.DataFrame, window: int = 20) -> pd.Series:
    """Breakout vs prior window high/low (excludes same-day bar via shift(1))."""
    prior_high = bars["high"].astype(float).rolling(window).max().shift(1)
    prior_low = bars["low"].astype(float).rolling(window).min().shift(1)
    close = bars["close"].astype(float)
    sig = pd.Series(0, index=bars.index, dtype=int)
    sig = sig.mask(close > prior_high, 1)
    sig = sig.mask(close < prior_low, -1)
    return sig.fillna(0).astype(int)


def mr_signal_series(
    bars: pd.DataFrame,
    *,
    sma: int = 20,
    z_entry: float = 1.5,
    r20_max: float = 5.0,
    r60_max: float = 8.0,
) -> pd.Series:
    """Fade z-score extremes only when short/medium momentum looks choppy."""
    close = bars["close"].astype(float)
    ma = close.rolling(sma).mean()
    sd = close.rolling(sma).std()
    z = (close - ma) / sd.replace(0.0, np.nan)
    r20 = (close / close.shift(20) - 1.0) * 100.0
    r60 = (close / close.shift(60) - 1.0) * 100.0
    chop = (r20.abs() < r20_max) & (r60.abs() < r60_max)
    sig = pd.Series(0, index=bars.index, dtype=int)
    sig = sig.mask(chop & (z > z_entry), -1)
    sig = sig.mask(chop & (z < -z_entry), 1)
    return sig.fillna(0).astype(int)


def xs_mom_score_series(bars: pd.DataFrame) -> pd.Series:
    """Vol-adjusted momentum: 0.5*r20 + 0.5*r60 scaled by 20d close vol."""
    close = bars["close"].astype(float)
    r20 = (close / close.shift(20) - 1.0) * 100.0
    r60 = (close / close.shift(60) - 1.0) * 100.0
    vol = close.pct_change().rolling(20).std().replace(0.0, np.nan) * 100.0
    raw = 0.5 * r20 + 0.5 * r60
    return (raw / vol).replace([np.inf, -np.inf], np.nan)


def xs_mom_weights_on_day(
    panel: dict[str, pd.Series],
    day: pd.Timestamp,
    *,
    top_n: int = 3,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for code, s in panel.items():
        if day not in s.index:
            continue
        v = s.loc[day]
        if isinstance(v, pd.Series):
            v = v.iloc[-1]
        if pd.isna(v):
            continue
        scores[str(code)] = float(v)
    if len(scores) < top_n * 2:
        return {}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    longs = [c for c, _ in ranked[:top_n]]
    shorts = [c for c, _ in ranked[-top_n:]]
    w: dict[str, float] = {}
    leg = 0.5 / float(top_n)
    for c in longs:
        w[c] = leg
    for c in shorts:
        w[c] = -leg
    return w


def _hist_to_df(hist: list[dict]) -> pd.DataFrame:
    rows = []
    for bar in hist:
        rows.append(
            {
                "date": bar["date"],
                "open": float(bar.get("open") or bar.get("close") or 0),
                "high": float(bar.get("high") or bar.get("close") or 0),
                "low": float(bar.get("low") or bar.get("close") or 0),
                "close": float(bar.get("close") or 0),
                "volume": float(bar.get("volume") or 0),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _max_dd(equity: list[float]) -> float:
    peak = equity[0]
    dd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak)
    return dd * 100.0


def _pack_metrics(
    *,
    name: str,
    family: str,
    curve: list[dict],
    rets_day: list[float],
    equity0: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(curve) < 2:
        return {"ok": False, "error": "curve too short", "strategy": name}
    eq = [c["equity"] for c in curve]
    ret_pct = (eq[-1] / eq[0] - 1.0) * 100.0
    dd = _max_dd(eq)
    if rets_day:
        mu = sum(rets_day) / len(rets_day)
        var = sum((r - mu) ** 2 for r in rets_day) / max(1, len(rets_day) - 1)
        vol = math.sqrt(var) * math.sqrt(252) if var > 0 else 0.0
        ann = mu * 252 * 100.0
        sharpe = (mu * 252 / vol) if vol > 0 else None
    else:
        ann = ret_pct
        sharpe = None
    calmar = (ann / dd) if dd > 0 else None
    out: dict[str, Any] = {
        "ok": True,
        "strategy": name,
        "family": family,
        "track_source": "local paper_sleeves.py (Path-A universe)",
        "live_trading": False,
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "equity_start": equity0,
        "equity_end": round(eq[-1], 2),
        "ret_pct": round(ret_pct, 3),
        "ret_ann_pct": round(ann, 3) if ann is not None else None,
        "max_dd_pct": round(dd, 3),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "calmar": round(calmar, 3) if calmar is not None else None,
        "equity_curve": curve,
        "summary": (
            f"sleeve {name} ret={ret_pct:.2f}% ann≈{ann:.2f}% "
            f"dd={dd:.2f}% sharpe={sharpe}"
        ),
    }
    if extra:
        out.update(extra)
    return out


def _simulate_ts_signals(
    frames: dict[str, pd.DataFrame],
    signal_fn,
    *,
    name: str,
    family: str,
    equity0: float = 200_000.0,
    cost_bps: float = 3.0,
    start_i: int = 60,
) -> dict[str, Any]:
    """Equal-weight active legs; next-day close-to-close; turnover cost on flip."""
    sigs = {code: signal_fn(df) for code, df in frames.items() if not df.empty}
    if not sigs:
        return {"ok": False, "error": "no frames", "strategy": name}
    dates = sorted({d for df in frames.values() for d in df.index})
    if len(dates) <= start_i + 1:
        return {"ok": False, "error": "too few dates", "strategy": name}

    equity = equity0
    curve: list[dict] = [{"date": dates[start_i].strftime("%Y-%m-%d"), "equity": equity0}]
    rets_day: list[float] = []
    prev_w: dict[str, float] = {}

    for d in dates[start_i:-1]:
        nxt = dates[dates.index(d) + 1]
        active: dict[str, int] = {}
        for code, s in sigs.items():
            if d not in s.index:
                continue
            v = int(s.loc[d])
            if v != 0 and d in frames[code].index and nxt in frames[code].index:
                active[code] = v
        if not active:
            day_ret = 0.0
            turnover = sum(abs(prev_w.get(c, 0.0)) for c in prev_w)
            cost = turnover * (cost_bps / 1e4)
            equity *= 1.0 - cost
            prev_w = {}
            curve.append({"date": nxt.strftime("%Y-%m-%d"), "equity": round(equity, 2)})
            rets_day.append(-cost)
            continue
        w_each = 1.0 / len(active)
        weights = {c: w_each * float(s) for c, s in active.items()}
        day_ret = 0.0
        for code, w in weights.items():
            px0 = float(frames[code].loc[d, "close"])
            px1 = float(frames[code].loc[nxt, "close"])
            if px0 <= 0:
                continue
            day_ret += w * (px1 / px0 - 1.0)
        codes = set(weights) | set(prev_w)
        turnover = sum(abs(weights.get(c, 0.0) - prev_w.get(c, 0.0)) for c in codes)
        cost = turnover * (cost_bps / 1e4)
        net = day_ret - cost
        equity *= 1.0 + net
        rets_day.append(net)
        prev_w = weights
        curve.append({"date": nxt.strftime("%Y-%m-%d"), "equity": round(equity, 2)})

    return _pack_metrics(
        name=name,
        family=family,
        curve=curve,
        rets_day=rets_day,
        equity0=equity0,
        extra={"cost_bps_one_way": cost_bps, "sleeve": name},
    )


def _simulate_xs_mom(
    frames: dict[str, pd.DataFrame],
    *,
    name: str = "sleeve_xs_mom",
    equity0: float = 200_000.0,
    cost_bps: float = 3.0,
    top_n: int = 3,
    start_i: int = 60,
) -> dict[str, Any]:
    scores = {code: xs_mom_score_series(df) for code, df in frames.items() if not df.empty}
    dates = sorted({d for df in frames.values() for d in df.index})
    if len(dates) <= start_i + 1:
        return {"ok": False, "error": "too few dates", "strategy": name}

    equity = equity0
    curve: list[dict] = [{"date": dates[start_i].strftime("%Y-%m-%d"), "equity": equity0}]
    rets_day: list[float] = []
    prev_w: dict[str, float] = {}

    for d in dates[start_i:-1]:
        nxt = dates[dates.index(d) + 1]
        weights = xs_mom_weights_on_day(scores, d, top_n=top_n)
        # Keep only codes with both days
        weights = {
            c: w
            for c, w in weights.items()
            if c in frames and d in frames[c].index and nxt in frames[c].index
        }
        day_ret = 0.0
        for code, w in weights.items():
            px0 = float(frames[code].loc[d, "close"])
            px1 = float(frames[code].loc[nxt, "close"])
            if px0 <= 0:
                continue
            day_ret += w * (px1 / px0 - 1.0)
        codes = set(weights) | set(prev_w)
        turnover = sum(abs(weights.get(c, 0.0) - prev_w.get(c, 0.0)) for c in codes)
        cost = turnover * (cost_bps / 1e4)
        net = day_ret - cost
        equity *= 1.0 + net
        rets_day.append(net)
        prev_w = weights
        curve.append({"date": nxt.strftime("%Y-%m-%d"), "equity": round(equity, 2)})

    return _pack_metrics(
        name=name,
        family="paper_sleeve_xs",
        curve=curve,
        rets_day=rets_day,
        equity0=equity0,
        extra={"cost_bps_one_way": cost_bps, "top_n": top_n, "sleeve": name},
    )


def _write_sleeve(sid: str, label: str, description: str, payload: dict, tags: list[str]) -> None:
    out_dir = ROOT / "external" / "strategies"
    extra_dir = ROOT / "desk" / "strategies" / "extra"
    out_dir.mkdir(parents=True, exist_ok=True)
    extra_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["name"] = label
    payload["description"] = description
    payload["live_trading"] = False
    (out_dir / f"{sid}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    extra = {
        "id": sid,
        "name": label,
        "description": description,
        "curve_file": f"external/strategies/{sid}.json",
        "tags": tags,
    }
    (extra_dir / f"{sid}.json").write_text(
        json.dumps(extra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    from historical_backtest import _fetch_pack, _load_cfg
    from research_experiment import record_experiment

    p = _load_cfg()
    symbols = p["cfg"]["symbols"]
    cost_bps = load_cost_bps()
    equity0 = float(
        (json.loads((ROOT / "research_cost.json").read_text(encoding="utf-8")).get("benchmark_equity"))
        if (ROOT / "research_cost.json").is_file()
        else 200_000.0
    )
    print("[sleeves] fetch bars…")
    series, errors, _sources = _fetch_pack(symbols)
    if errors:
        print("[sleeves] fetch errors", list(errors)[:5])
    frames = {code: _hist_to_df(pack["hist"]) for code, pack in series.items()}
    frames = {c: df for c, df in frames.items() if len(df) >= 80}
    print(f"[sleeves] frames={len(frames)} cost_bps={cost_bps}")

    specs = [
        (
            "sleeve_donchian",
            "纸面·唐奇安突破",
            "纸面互补：20日唐奇安突破（先验高低，防同日偷看）；等权活跃腿；次日收盘收益；单边成本 bp。",
            lambda: _simulate_ts_signals(
                frames,
                lambda df: donchian_signal_series(df, window=20),
                name="sleeve_donchian",
                family="paper_sleeve_trend",
                equity0=equity0,
                cost_bps=cost_bps,
            ),
            ["paper_sleeve", "donchian", "trend", "complementary"],
        ),
        (
            "sleeve_mr",
            "纸面·震荡均值回归",
            "纸面互补：|r20|/|r60| 偏弱时对 z-score 极值反向；等权活跃腿；不下单实盘。",
            lambda: _simulate_ts_signals(
                frames,
                mr_signal_series,
                name="sleeve_mr",
                family="paper_sleeve_mr",
                equity0=equity0,
                cost_bps=cost_bps,
            ),
            ["paper_sleeve", "mean_reversion", "chop", "complementary"],
        ),
        (
            "sleeve_xs_mom",
            "纸面·波动调整截面动量",
            "纸面互补：波动调整动量多空各 top_n；次日收益；与 Path-A 同宇宙。",
            lambda: _simulate_xs_mom(
                frames, name="sleeve_xs_mom", equity0=equity0, cost_bps=cost_bps, top_n=3
            ),
            ["paper_sleeve", "cross_section", "momentum", "complementary"],
        ),
    ]

    for sid, label, desc, runner, tags in specs:
        print(f"[sleeves] simulate {sid}…")
        payload = runner()
        _write_sleeve(sid, label, desc, payload, tags)
        print(" ", payload.get("summary") or payload.get("error"))
        record_experiment(
            name=sid,
            kind="paper_sleeve",
            params={"cost_bps_one_way": cost_bps, "equity0": equity0},
            metrics={
                "ret_pct": payload.get("ret_pct"),
                "sharpe": payload.get("sharpe"),
                "max_dd_pct": payload.get("max_dd_pct"),
                "ok": payload.get("ok"),
            },
            artifact=f"external/strategies/{sid}.json",
            notes=label,
        )


if __name__ == "__main__":
    main()
