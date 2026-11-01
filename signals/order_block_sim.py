# -*- coding: utf-8 -*-
"""Next-open shadow fills for order-block retest signals.

The signal bar is already closed when a signal exists. The fill is the next
bar's open. This module does not read Path-A execution rules and does not
send orders.

Same-bar stop and target: the stop is taken. A gap through the stop on the
fill bar cancels the entry. Both choices are research assumptions, recorded
on each trade.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from signals.order_block import OrderBlockSignal


@dataclass
class ShadowTrade:
    ob_id: str
    direction: str
    signal_index: int
    signal_date: str
    entry_index: int
    entry_date: str
    entry_price: float
    stop_price: float
    target_price: float
    exit_index: int
    exit_date: str
    exit_price: float
    exit_reason: str
    initial_risk: float
    pnl_price: float
    r_multiple: float
    cost_price: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkippedSignal:
    ob_id: str
    signal_index: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slip(price: float, direction: str, slippage_bps: float) -> float:
    bump = slippage_bps / 10_000.0
    if direction == "long":
        return price * (1.0 + bump)
    return price * (1.0 - bump)


def _round_trip_cost(entry: float, commission_bps_per_side: float) -> float:
    return abs(entry) * (2.0 * commission_bps_per_side / 10_000.0)


def simulate_retest_trades(
    bars: list[dict[str, Any]],
    signals: list[OrderBlockSignal],
    *,
    reward_rr: float = 1.5,
    slippage_bps: float = 0.0,
    commission_bps_per_side: float = 0.0,
    one_position_at_a_time: bool = True,
) -> tuple[list[ShadowTrade], list[SkippedSignal]]:
    """Simulate shadow trades in R units of the zone-boundary stop.

    ``reward_rr`` is local to this experiment. It is not the formal Path-A
    reward:risk setting.
    """
    if reward_rr <= 0:
        raise ValueError("reward_rr must be positive")
    trades: list[ShadowTrade] = []
    skipped: list[SkippedSignal] = []
    busy_until = -1
    for sig in signals:
        entry_i = sig.signal_index + 1
        if entry_i >= len(bars):
            skipped.append(SkippedSignal(sig.ob_id, sig.signal_index, "no_next_bar"))
            continue
        if one_position_at_a_time and entry_i <= busy_until:
            skipped.append(SkippedSignal(sig.ob_id, sig.signal_index, "position_open"))
            continue
        raw_open = float(bars[entry_i]["open"])
        entry = _slip(raw_open, sig.direction, slippage_bps)
        stop = float(sig.stop_price)
        if sig.direction == "long" and entry <= stop:
            skipped.append(SkippedSignal(sig.ob_id, sig.signal_index, "gap_through_stop"))
            continue
        if sig.direction == "short" and entry >= stop:
            skipped.append(SkippedSignal(sig.ob_id, sig.signal_index, "gap_through_stop"))
            continue
        risk = (entry - stop) if sig.direction == "long" else (stop - entry)
        if risk <= 0:
            skipped.append(SkippedSignal(sig.ob_id, sig.signal_index, "non_positive_risk"))
            continue
        if sig.direction == "long":
            target = entry + reward_rr * risk
        else:
            target = entry - reward_rr * risk
        exit_i, exit_price, reason = _walk_exit(
            bars, entry_i, sig.direction, stop, target
        )
        cost = _round_trip_cost(entry, commission_bps_per_side)
        if sig.direction == "long":
            pnl = exit_price - entry - cost
        else:
            pnl = entry - exit_price - cost
        trade = ShadowTrade(
            ob_id=sig.ob_id,
            direction=sig.direction,
            signal_index=sig.signal_index,
            signal_date=sig.signal_date,
            entry_index=entry_i,
            entry_date=str(bars[entry_i].get("date") or entry_i),
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            exit_index=exit_i,
            exit_date=str(bars[exit_i].get("date") or exit_i),
            exit_price=exit_price,
            exit_reason=reason,
            initial_risk=risk,
            pnl_price=pnl,
            r_multiple=pnl / risk,
            cost_price=cost,
        )
        trades.append(trade)
        busy_until = exit_i
    return trades, skipped


def _walk_exit(
    bars: list[dict[str, Any]],
    entry_i: int,
    direction: str,
    stop: float,
    target: float,
) -> tuple[int, float, str]:
    last = len(bars) - 1
    for j in range(entry_i, len(bars)):
        bar = bars[j]
        if direction == "long":
            hit_stop = bar["low"] <= stop
            hit_target = bar["high"] >= target
            if hit_stop and hit_target:
                return j, stop, "stop_and_target_stop_first"
            if hit_stop:
                if bar["open"] <= stop:
                    return j, float(bar["open"]), "gap_stop"
                return j, stop, "stop"
            if hit_target:
                if bar["open"] >= target:
                    return j, float(bar["open"]), "gap_target"
                return j, target, "target"
        else:
            hit_stop = bar["high"] >= stop
            hit_target = bar["low"] <= target
            if hit_stop and hit_target:
                return j, stop, "stop_and_target_stop_first"
            if hit_stop:
                if bar["open"] >= stop:
                    return j, float(bar["open"]), "gap_stop"
                return j, stop, "stop"
            if hit_target:
                if bar["open"] <= target:
                    return j, float(bar["open"]), "gap_target"
                return j, target, "target"
    return last, float(bars[last]["close"]), "open_at_end"
