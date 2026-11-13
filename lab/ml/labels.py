# -*- coding: utf-8 -*-
"""Causal-safe labels for P4 light tasks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Features known at event/signal time only (no MFE/MAE/post returns).
LSP_FEATURE_KEYS = (
    "break_size_atr",
    "volume_ratio",
    "distance_to_level",
    "atr",
    "htf_resonance",
    "break_up",
    "level_is_high",
    "hour",
)


def load_lsp_events(root: Path | None = None, timeframe: str = "15m") -> list[dict[str, Any]]:
    root = root or ROOT
    path = root / "lab" / "research" / "lsp" / f"lsp_CF_{timeframe}_events.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def lsp_reversal_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """y=1 if outcome is fake_break_reversal."""
    rows = []
    for e in events:
        if not e.get("outcome"):
            continue
        ts = str(e.get("timestamp") or "")
        hour = None
        if len(ts) >= 13 and ts[11:13].isdigit():
            hour = int(ts[11:13])
        feat = {
            "break_size_atr": e.get("break_size_atr"),
            "volume_ratio": e.get("volume_ratio"),
            "distance_to_level": e.get("distance_to_level"),
            "atr": e.get("atr"),
            "htf_resonance": 1.0 if e.get("htf_resonance") else 0.0,
            "break_up": 1.0 if e.get("break_direction") == "up" else 0.0,
            "level_is_high": 1.0 if "high" in str(e.get("level_type") or "") else 0.0,
            "hour": float(hour) if hour is not None else -1.0,
        }
        if any(feat[k] is None for k in ("break_size_atr", "volume_ratio", "atr")):
            continue
        rows.append(
            {
                "task": "lsp_reversal",
                "timestamp": ts,
                "y": 1 if e.get("outcome") == "fake_break_reversal" else 0,
                "features": feat,
                "meta": {"outcome": e.get("outcome"), "symbol": e.get("symbol")},
            }
        )
    return rows


def _ret_n(hist: list[dict], i: int, n: int) -> float | None:
    if i < n:
        return None
    c0 = float(hist[i - n]["close"])
    c1 = float(hist[i]["close"])
    if c0 == 0:
        return None
    return c1 / c0 - 1.0


def _atr14(hist: list[dict], i: int) -> float | None:
    if i < 14:
        return None
    trs = []
    for j in range(i - 13, i + 1):
        h, l = float(hist[j]["high"]), float(hist[j]["low"])
        pc = float(hist[j - 1]["close"]) if j else float(hist[j]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / 14.0


def daily_signal_rows(
    hist: list[dict[str, Any]],
    *,
    min_r20: float = 0.04,
    min_r60: float = 0.06,
    fail_horizon: int = 5,
    continue_horizon: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build trend_fail and breakout_continue samples from daily OHLC."""
    trend_rows: list[dict[str, Any]] = []
    break_rows: list[dict[str, Any]] = []
    for i in range(60, len(hist) - max(fail_horizon, continue_horizon) - 1):
        r20, r60 = _ret_n(hist, i, 20), _ret_n(hist, i, 60)
        atr = _atr14(hist, i)
        if r20 is None or r60 is None or atr is None or atr <= 0:
            continue
        close = float(hist[i]["close"])
        vol = float(hist[i].get("volume") or 0)
        prev_vols = [float(hist[j].get("volume") or 0) for j in range(max(0, i - 20), i)]
        avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0.0
        vol_ratio = (vol / avg_vol) if avg_vol > 0 else 0.0
        aligned = (r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0)
        strong = abs(r20) >= min_r20 and abs(r60) >= min_r60
        direction = 1.0 if r20 > 0 else -1.0
        feat = {
            "r20": r20,
            "r60": r60,
            "atr_pct": atr / close,
            "vol_ratio": vol_ratio,
            "direction": direction,
            "abs_r20": abs(r20),
            "abs_r60": abs(r60),
        }
        d = str(hist[i].get("date") or "")[:10]

        if aligned and strong:
            # trend fail: within horizon, 20/60 no longer same direction
            failed = 0
            for h in range(1, fail_horizon + 1):
                j = i + h
                rr20, rr60 = _ret_n(hist, j, 20), _ret_n(hist, j, 60)
                if rr20 is None or rr60 is None:
                    continue
                still = (rr20 > 0 and rr60 > 0) or (rr20 < 0 and rr60 < 0)
                same_way = (rr20 > 0) == (r20 > 0)
                if not (still and same_way):
                    failed = 1
                    break
            trend_rows.append(
                {
                    "task": "trend_fail",
                    "timestamp": d,
                    "y": failed,
                    "features": feat,
                    "meta": {"date": d},
                }
            )

        # breakout continue: |r20| just crossed min after being below
        prev_r20 = _ret_n(hist, i - 1, 20)
        if prev_r20 is not None and abs(prev_r20) < min_r20 <= abs(r20) and aligned:
            future = _ret_n(hist, i + continue_horizon, continue_horizon)
            # signed continuation from i close over horizon using closes
            c_now = close
            c_fut = float(hist[i + continue_horizon]["close"])
            moved = (c_fut - c_now) / c_now
            cont = 1 if (moved * direction) > 0 else 0
            break_rows.append(
                {
                    "task": "breakout_continue",
                    "timestamp": d,
                    "y": cont,
                    "features": feat,
                    "meta": {"date": d, "moved": moved},
                }
            )
    return trend_rows, break_rows


def load_daily_bars(code: str = "CF", root: Path | None = None) -> list[dict[str, Any]]:
    root = root or ROOT
    # Prefer lab continuous
    path = root / "lab" / "data" / "bars" / "continuous" / f"{code.upper()}.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        bars = data if isinstance(data, list) else data.get("bars") or data.get("hist") or []
        out = []
        for b in bars:
            if not isinstance(b, dict):
                continue
            try:
                out.append(
                    {
                        "date": str(b.get("date") or "")[:10],
                        "open": float(b["open"]),
                        "high": float(b["high"]),
                        "low": float(b["low"]),
                        "close": float(b["close"]),
                        "volume": float(b.get("volume") or 0),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        if len(out) >= 100:
            return out
    # Fallback: market_data continuous (may hit cache)
    try:
        from market_data import fetch_sina_daily

        bars = fetch_sina_daily(code)
        return [
            {
                "date": b["date"],
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume") or 0),
            }
            for b in bars
        ]
    except Exception:
        return []
