# -*- coding: utf-8 -*-
"""Causal order-block zones and retest signals (shadow research, v1).

Definition, fixed before any outcome is known:

* A swing high (low) at pivot ``t`` is confirmed only at ``t + swing_right``,
  after ``swing_left`` bars on the left and ``swing_right`` bars on the right
  print strictly lower highs (higher lows). ``swing_right`` must be >= 1.
* Long break of structure: a later bar's close is strictly above the latest
  confirmed swing high. Short is the mirror, through the latest swing low.
* The order block is the nearest opposite candle strictly before that break
  (bearish for a long break, bullish for a short break), inside
  ``ob_search_window``. The zone is that candle's high and low.
* The zone is knowable at the break bar's close and may emit a signal only
  on a later bar that trades back into the zone. Fill policy lives in the
  simulator: next bar's open, never this bar's extreme.
* A long zone stops offering new signals once a bar closes below its low.
  A short zone stops once a bar closes above its high. If the break close
  is already through that boundary, the zone is kept and retired on the
  break bar. Zones that never retest, and zones that fail, stay in the output.

v1 breaks only the latest confirmed swing in each direction. That is a
definition choice. It does not look past the bar being processed.

This module does not size positions, does not read ``execution_rules.json``,
and does not apply the formal Path-A stop of ATR×1.2 or target of 1.5R.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Direction = Literal["long", "short"]
OB_REQUIRED_KEYS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class OrderBlockParams:
    """Research defaults. Not an optimized parameter set."""

    swing_left: int = 2
    swing_right: int = 2
    ob_search_window: int = 10
    max_retests: int = 1
    invalidate_on: str = "close"

    def validated(self) -> OrderBlockParams:
        if self.swing_left < 1:
            raise ValueError("swing_left must be >= 1")
        if self.swing_right < 1:
            raise ValueError(
                "swing_right must be >= 1 so a swing cannot be used on its pivot bar"
            )
        if self.ob_search_window < 1:
            raise ValueError("ob_search_window must be >= 1")
        if self.max_retests < 1:
            raise ValueError("max_retests must be >= 1")
        if self.invalidate_on != "close":
            raise ValueError("v1 only supports invalidate_on='close' (a closing break)")
        return self


@dataclass
class SwingPoint:
    kind: Literal["high", "low"]
    index: int
    price: float
    confirmed_index: int
    broken_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderBlock:
    ob_id: str
    direction: Direction
    source_index: int
    source_date: str
    bos_index: int
    bos_date: str
    swing_index: int
    swing_confirmed_index: int
    swing_price: float
    zone_low: float
    zone_high: float
    known_from_index: int
    active_from_index: int
    invalidation_price: float
    invalidated_index: int | None = None
    invalidated_date: str | None = None
    retest_count: int = 0
    status: Literal["active", "retested", "invalidated"] = "active"
    role: str = "location_stop"
    quality_score: None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderBlockSignal:
    ob_id: str
    direction: Direction
    signal_index: int
    signal_date: str
    bos_index: int
    source_index: int
    active_from_index: int
    zone_low: float
    zone_high: float
    stop_price: float
    entry_reference: float
    fill_rule: str = "next_open"
    role: str = "location_stop"
    quality_score: None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UnzonedBreak:
    """A structure break that had no qualifying opposite candle.

    Kept so a break is not dropped just because it never became a zone.
    """

    direction: Direction
    bos_index: int
    bos_date: str
    swing_index: int
    swing_price: float
    reason: str = "no_opposite_candle"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Detection:
    params: OrderBlockParams
    swings: list[SwingPoint] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    signals: list[OrderBlockSignal] = field(default_factory=list)
    unzoned_breaks: list[UnzonedBreak] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": asdict(self.params),
            "swings": [s.to_dict() for s in self.swings],
            "order_blocks": [o.to_dict() for o in self.order_blocks],
            "signals": [s.to_dict() for s in self.signals],
            "unzoned_breaks": [u.to_dict() for u in self.unzoned_breaks],
        }


def _bar_date(bar: dict[str, Any], index: int) -> str:
    raw = bar.get("date")
    if raw is None or raw == "":
        return str(index)
    return str(raw)


def _validate_bars(bars: list[dict[str, Any]]) -> None:
    if not isinstance(bars, list):
        raise TypeError("bars must be a list of OHLC dicts")
    for i, bar in enumerate(bars):
        if not isinstance(bar, dict):
            raise TypeError(f"bar {i} must be a dict")
        missing = [k for k in OB_REQUIRED_KEYS if k not in bar]
        if missing:
            raise ValueError(f"bar {i} missing {missing}")
        try:
            o = float(bar["open"])
            h = float(bar["high"])
            l = float(bar["low"])
            c = float(bar["close"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bar {i} OHLC must be numeric") from exc
        if h < l or h < max(o, c) or l > min(o, c):
            raise ValueError(f"bar {i} OHLC is inconsistent")
        bar["open"], bar["high"], bar["low"], bar["close"] = o, h, l, c


def _is_swing_high(bars: list[dict[str, Any]], pivot: int, left: int, right: int) -> bool:
    price = bars[pivot]["high"]
    for j in range(pivot - left, pivot):
        if bars[j]["high"] >= price:
            return False
    for j in range(pivot + 1, pivot + right + 1):
        if bars[j]["high"] >= price:
            return False
    return True


def _is_swing_low(bars: list[dict[str, Any]], pivot: int, left: int, right: int) -> bool:
    price = bars[pivot]["low"]
    for j in range(pivot - left, pivot):
        if bars[j]["low"] <= price:
            return False
    for j in range(pivot + 1, pivot + right + 1):
        if bars[j]["low"] <= price:
            return False
    return True


def _find_source(
    bars: list[dict[str, Any]],
    bos_index: int,
    direction: Direction,
    window: int,
) -> int | None:
    start = max(0, bos_index - window)
    for j in range(bos_index - 1, start - 1, -1):
        o = bars[j]["open"]
        c = bars[j]["close"]
        if direction == "long" and c < o:
            return j
        if direction == "short" and c > o:
            return j
    return None


def _overlaps(bar: dict[str, Any], zone_low: float, zone_high: float) -> bool:
    return bar["low"] <= zone_high and bar["high"] >= zone_low


class _Book:
    def __init__(self, bars: list[dict[str, Any]], params: OrderBlockParams) -> None:
        self.bars = bars
        self.params = params
        self.swings: list[SwingPoint] = []
        self.order_blocks: list[OrderBlock] = []
        self.signals: list[OrderBlockSignal] = []
        self.unzoned_breaks: list[UnzonedBreak] = []
        self.ref_high: SwingPoint | None = None
        self.ref_low: SwingPoint | None = None

    def run(self) -> Detection:
        for i in range(len(self.bars)):
            # Retests and invalidations first, using zones already knowable
            # before this close. A zone born on this bar waits until later.
            self._update_zones(i)
            self._break_structure(i)
            self._confirm_swings(i)
        return Detection(
            params=self.params,
            swings=self.swings,
            order_blocks=self.order_blocks,
            signals=self.signals,
            unzoned_breaks=self.unzoned_breaks,
        )

    def _confirm_swings(self, i: int) -> None:
        pivot = i - self.params.swing_right
        if pivot < self.params.swing_left:
            return
        if _is_swing_high(self.bars, pivot, self.params.swing_left, self.params.swing_right):
            swing = SwingPoint(
                kind="high",
                index=pivot,
                price=self.bars[pivot]["high"],
                confirmed_index=i,
            )
            self.swings.append(swing)
            self.ref_high = swing
        if _is_swing_low(self.bars, pivot, self.params.swing_left, self.params.swing_right):
            swing = SwingPoint(
                kind="low",
                index=pivot,
                price=self.bars[pivot]["low"],
                confirmed_index=i,
            )
            self.swings.append(swing)
            self.ref_low = swing

    def _break_structure(self, i: int) -> None:
        close = self.bars[i]["close"]
        high = self.ref_high
        if (
            high is not None
            and high.broken_index is None
            and i > high.confirmed_index
            and close > high.price
        ):
            high.broken_index = i
            self._open_zone("long", i, high)
        low = self.ref_low
        if (
            low is not None
            and low.broken_index is None
            and i > low.confirmed_index
            and close < low.price
        ):
            low.broken_index = i
            self._open_zone("short", i, low)

    def _open_zone(self, direction: Direction, bos_index: int, swing: SwingPoint) -> None:
        source = _find_source(
            self.bars, bos_index, direction, self.params.ob_search_window
        )
        bos_date = _bar_date(self.bars[bos_index], bos_index)
        if source is None:
            self.unzoned_breaks.append(
                UnzonedBreak(
                    direction=direction,
                    bos_index=bos_index,
                    bos_date=bos_date,
                    swing_index=swing.index,
                    swing_price=swing.price,
                )
            )
            return
        candle = self.bars[source]
        zone_low = candle["low"]
        zone_high = candle["high"]
        close = self.bars[bos_index]["close"]
        if direction == "long":
            invalidation = zone_low
            already_through = close < invalidation
            ob_id = f"L{bos_index}-{source}"
        else:
            invalidation = zone_high
            already_through = close > invalidation
            ob_id = f"S{bos_index}-{source}"
        ob = OrderBlock(
            ob_id=ob_id,
            direction=direction,
            source_index=source,
            source_date=_bar_date(candle, source),
            bos_index=bos_index,
            bos_date=bos_date,
            swing_index=swing.index,
            swing_confirmed_index=swing.confirmed_index,
            swing_price=swing.price,
            zone_low=zone_low,
            zone_high=zone_high,
            known_from_index=bos_index,
            active_from_index=bos_index + 1,
            invalidation_price=invalidation,
        )
        # A stale opposite candle can sit entirely beyond the break close.
        # That fact is known at the break close, so the zone is kept and
        # already retired. Later bars must not turn it into a signal.
        if already_through:
            ob.invalidated_index = bos_index
            ob.invalidated_date = bos_date
            ob.status = "invalidated"
        self.order_blocks.append(ob)

    def _update_zones(self, i: int) -> None:
        bar = self.bars[i]
        for ob in self.order_blocks:
            if ob.invalidated_index is not None:
                continue
            if i < ob.active_from_index:
                continue
            closed_through = (
                ob.direction == "long" and bar["close"] < ob.invalidation_price
            ) or (
                ob.direction == "short" and bar["close"] > ob.invalidation_price
            )
            if closed_through:
                ob.invalidated_index = i
                ob.invalidated_date = _bar_date(bar, i)
                ob.status = "invalidated"
                continue
            if ob.retest_count >= self.params.max_retests:
                continue
            if not _overlaps(bar, ob.zone_low, ob.zone_high):
                continue
            self.signals.append(
                OrderBlockSignal(
                    ob_id=ob.ob_id,
                    direction=ob.direction,
                    signal_index=i,
                    signal_date=_bar_date(bar, i),
                    bos_index=ob.bos_index,
                    source_index=ob.source_index,
                    active_from_index=ob.active_from_index,
                    zone_low=ob.zone_low,
                    zone_high=ob.zone_high,
                    stop_price=ob.invalidation_price,
                    entry_reference=bar["close"],
                )
            )
            ob.retest_count += 1
            ob.status = "retested"


def detect_order_blocks(
    bars: list[dict[str, Any]],
    params: OrderBlockParams | None = None,
) -> Detection:
    """Detect zones and retest signals from a causal forward scan.

    The input list is copied. OHLC values are coerced to float on the copy.
    """
    cfg = (params or OrderBlockParams()).validated()
    copied = [dict(bar) for bar in bars]
    _validate_bars(copied)
    return _Book(copied, cfg).run()


def params_from_config(cfg: dict[str, Any]) -> OrderBlockParams:
    """Read structure settings from a shadow config dict.

    Refuses live trading, stub configs, and any switch that would pretend
    a trend, momentum, or ATR module is already applied.
    """
    if cfg.get("live_trading"):
        raise ValueError("order-block shadow refuses live_trading=true")
    if cfg.get("track") != "order_block_shadow":
        raise ValueError("config track must be order_block_shadow")
    if cfg.get("status") != "runnable":
        status = cfg.get("status")
        raise ValueError(
            f"config status is {status!r}; only status='runnable' can execute"
        )
    filters = cfg.get("filters") or {}
    if filters.get("trend") or filters.get("momentum"):
        raise ValueError("trend and momentum filters are separate modules and are not wired")
    risk = cfg.get("risk") or {}
    if float(risk.get("atr_buffer_k") or 0) != 0:
        raise ValueError("ATR stop buffer is not wired; formal ATR×1.2 is unchanged")
    if risk.get("atr_module") not in (None, "not_wired"):
        raise ValueError("ATR module must stay not_wired in this slice")
    execution = cfg.get("execution") or {}
    if execution.get("fill") not in (None, "next_open"):
        raise ValueError("v1 fill is next_open")
    if execution.get("stop_mode") not in (None, "zone_boundary"):
        raise ValueError("v1 stop_mode is zone_boundary, not the formal ATR stop")
    if execution.get("same_bar_conflict") not in (None, "stop_first"):
        raise ValueError("v1 same-bar stop and target resolves to the stop")
    structure = cfg.get("structure") or {}
    return OrderBlockParams(
        swing_left=int(structure.get("swing_left", 2)),
        swing_right=int(structure.get("swing_right", 2)),
        ob_search_window=int(structure.get("ob_search_window", 10)),
        max_retests=int(structure.get("max_retests", 1)),
        invalidate_on=str(structure.get("invalidate_on", "close")),
    ).validated()


def load_run_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("config must be a JSON object")
    params_from_config(cfg)
    return cfg
