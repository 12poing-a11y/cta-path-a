# -*- coding: utf-8 -*-
"""Detect liquidity sweep / pierce events at confirmed swing levels."""
from __future__ import annotations

from typing import Any, Sequence

from lab.lsp.levels import SwingLevel, atr_series, detect_swing_levels
from lab.lsp.schema import empty_event


def _vol(bar: dict) -> float:
    try:
        return float(bar.get("volume") or 0)
    except (TypeError, ValueError):
        return 0.0


def detect_sweep_events(
    bars: Sequence[dict[str, Any]],
    *,
    symbol: str = "CF",
    contract: str | None = None,
    timeframe: str = "15m",
    swing_left: int = 3,
    swing_right: int = 3,
    min_break_atr: float = 0.05,
    approach_atr: float = 0.5,
    vol_lookback: int = 20,
    cooldown_bars: int = 5,
    include_vwap: bool = True,
) -> list[dict[str, Any]]:
    """Emit one event per first pierce of a fresh confirmed swing (Research only)."""
    levels = detect_swing_levels(bars, swing_left=swing_left, swing_right=swing_right)
    if include_vwap:
        try:
            from lab.lsp.vwap_levels import vwap_levels_as_swings

            levels = list(levels) + vwap_levels_as_swings(bars)
        except Exception:
            pass
    atrs = atr_series(bars, 14)
    events: list[dict[str, Any]] = []
    used: set[tuple[str, int]] = set()  # (kind, swing_index) once pierced
    last_event_i = -10_000

    # Map confirmed_index -> levels that become active
    by_conf: dict[int, list[SwingLevel]] = {}
    for lv in levels:
        by_conf.setdefault(lv.confirmed_index, []).append(lv)

    active: list[SwingLevel] = []
    for i, bar in enumerate(bars):
        for lv in by_conf.get(i, []):
            active.append(lv)
        if i - last_event_i < cooldown_bars:
            continue
        atr = atrs[i]
        if atr is None or atr <= 0:
            continue
        hi = float(bar["high"])
        lo = float(bar["low"])
        close = float(bar["close"])
        # Average volume
        j0 = max(0, i - vol_lookback)
        vols = [_vol(bars[j]) for j in range(j0, i)]
        avg_vol = (sum(vols) / len(vols)) if vols else 0.0
        vol_ratio = (_vol(bar) / avg_vol) if avg_vol > 0 else None

        for lv in list(active):
            key = (lv.kind, lv.index)
            if key in used:
                continue
            # Only trade levels that existed before this bar
            if lv.confirmed_index >= i:
                continue
            pierced = False
            direction = None
            break_size = 0.0
            if lv.kind == "high" and hi > lv.price + min_break_atr * atr:
                pierced = True
                direction = "up"
                break_size = (hi - lv.price) / atr
            elif lv.kind == "low" and lo < lv.price - min_break_atr * atr:
                pierced = True
                direction = "down"
                break_size = (lv.price - lo) / atr
            if not pierced:
                continue
            used.add(key)
            last_event_i = i
            ev = empty_event(symbol=symbol, timeframe=timeframe)
            ev.update(
                {
                    "schema": "cta-lsp-event-v1",
                    "contract": contract,
                    "timestamp": str(bar.get("datetime") or bar.get("date") or ""),
                    "bar_index": i,
                    "level_type": f"swing_{lv.kind}",
                    "level_price": round(lv.price, 4),
                    "level_index": lv.index,
                    "level_confirmed_index": lv.confirmed_index,
                    "distance_to_level": round((close - lv.price) / atr, 4),
                    "break_direction": direction,
                    "break_size_atr": round(break_size, 4),
                    "volume_ratio": None if vol_ratio is None else round(vol_ratio, 4),
                    "atr": round(atr, 4),
                    "note": "Detected pierce; outcome filled by label_events().",
                }
            )
            events.append(ev)
            break  # one event per bar
    return events
