# -*- coding: utf-8 -*-
"""Causal swing levels for LSP (confirmed only after right bars)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence


@dataclass(frozen=True)
class SwingLevel:
    kind: Literal["high", "low"]
    index: int
    price: float
    confirmed_index: int
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "index": self.index,
            "price": self.price,
            "confirmed_index": self.confirmed_index,
            "timestamp": self.timestamp,
        }


def _f(bar: dict, key: str) -> float | None:
    try:
        v = float(bar[key])
    except (KeyError, TypeError, ValueError):
        return None
    return v


def detect_swing_levels(
    bars: Sequence[dict[str, Any]],
    *,
    swing_left: int = 3,
    swing_right: int = 3,
) -> list[SwingLevel]:
    """Fractal swings: pivot extreme vs left/right neighbors; knowable at confirmed_index."""
    if swing_left < 1 or swing_right < 1:
        raise ValueError("swing_left/right must be >= 1")
    n = len(bars)
    out: list[SwingLevel] = []
    for i in range(swing_left, n - swing_right):
        hi = _f(bars[i], "high")
        lo = _f(bars[i], "low")
        if hi is None or lo is None:
            continue
        left = bars[i - swing_left : i]
        right = bars[i + 1 : i + 1 + swing_right]
        if len(left) < swing_left or len(right) < swing_right:
            continue
        left_h = [_f(b, "high") for b in left]
        right_h = [_f(b, "high") for b in right]
        left_l = [_f(b, "low") for b in left]
        right_l = [_f(b, "low") for b in right]
        if None in left_h + right_h + left_l + right_l:
            continue
        conf = i + swing_right
        ts = str(bars[i].get("datetime") or bars[i].get("date") or "")
        if hi > max(left_h) and hi > max(right_h):  # type: ignore[type-var]
            out.append(SwingLevel("high", i, hi, conf, ts or None))
        if lo < min(left_l) and lo < min(right_l):  # type: ignore[type-var]
            out.append(SwingLevel("low", i, lo, conf, ts or None))
    return out


def atr_series(bars: Sequence[dict[str, Any]], n: int = 14) -> list[float | None]:
    """Wilder-like simple ATR from minute OHLC (None until warm)."""
    out: list[float | None] = [None] * len(bars)
    trs: list[float] = []
    prev_c = None
    for i, b in enumerate(bars):
        h, l, c = _f(b, "high"), _f(b, "low"), _f(b, "close")
        if None in (h, l, c):
            trs.append(float("nan"))
            prev_c = c
            continue
        if prev_c is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
        prev_c = c
        if i + 1 >= n and all(x == x for x in trs[i + 1 - n : i + 1]):  # not NaN
            out[i] = sum(trs[i + 1 - n : i + 1]) / n
    return out
