# -*- coding: utf-8 -*-
"""Next-open shadow fills for LSP pierce-and-reclaim signals."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from signals.lsp_profile import LspSignal


@dataclass
class LspTrade:
    signal_id: str
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
    timeframe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LspSkipped:
    signal_id: str
    signal_index: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slip(price: float, direction: str, slippage_bps: float) -> float:
    bump = slippage_bps / 10_000.0
    if direction == "long":
        return price * (1.0 + bump)
    return price * (1.0 - bump)


def simulate_lsp_trades(
    bars: list[dict[str, Any]],
    signals: list[LspSignal],
    *,
    reward_rr: float = 1.5,
    slippage_bps: float = 0.0,
    commission_bps_per_side: float = 0.0,
    one_position_at_a_time: bool = True,
) -> tuple[list[LspTrade], list[LspSkipped]]:
    if reward_rr <= 0:
        raise ValueError("reward_rr must be positive")
    trades: list[LspTrade] = []
    skipped: list[LspSkipped] = []
    busy_until = -1
    for sig in signals:
        entry_i = sig.signal_index + 1
        if entry_i >= len(bars):
            skipped.append(LspSkipped(sig.signal_id, sig.signal_index, "no_next_bar"))
            continue
        if one_position_at_a_time and entry_i <= busy_until:
            skipped.append(LspSkipped(sig.signal_id, sig.signal_index, "position_open"))
            continue
        raw_open = float(bars[entry_i]["open"])
        entry = _slip(raw_open, sig.direction, slippage_bps)
        stop = float(sig.stop_price)
        if sig.direction == "long" and entry <= stop:
            skipped.append(LspSkipped(sig.signal_id, sig.signal_index, "gap_through_stop"))
            continue
        if sig.direction == "short" and entry >= stop:
            skipped.append(LspSkipped(sig.signal_id, sig.signal_index, "gap_through_stop"))
            continue
        risk = abs(entry - stop)
        if risk <= 0:
            skipped.append(LspSkipped(sig.signal_id, sig.signal_index, "zero_risk"))
            continue
        if sig.direction == "long":
            target = entry + reward_rr * risk
        else:
            target = entry - reward_rr * risk
        cost = abs(entry) * (2.0 * commission_bps_per_side / 10_000.0)
        exit_i = entry_i
        exit_px = entry
        reason = "timeout"
        for j in range(entry_i, len(bars)):
            hj = float(bars[j]["high"])
            lj = float(bars[j]["low"])
            hit_stop = (sig.direction == "long" and lj <= stop) or (
                sig.direction == "short" and hj >= stop
            )
            hit_tgt = (sig.direction == "long" and hj >= target) or (
                sig.direction == "short" and lj <= target
            )
            if hit_stop and hit_tgt:
                exit_i, exit_px, reason = j, stop, "stop"
                break
            if hit_stop:
                exit_i, exit_px, reason = j, stop, "stop"
                break
            if hit_tgt:
                exit_i, exit_px, reason = j, target, "target"
                break
            exit_i = j
            exit_px = float(bars[j]["close"])
            reason = "eod_close" if j == len(bars) - 1 else "timeout"
        if sig.direction == "long":
            pnl = exit_px - entry - cost
        else:
            pnl = entry - exit_px - cost
        r_mult = pnl / risk if risk else 0.0
        busy_until = exit_i
        trades.append(
            LspTrade(
                signal_id=sig.signal_id,
                direction=sig.direction,
                signal_index=sig.signal_index,
                signal_date=sig.signal_date,
                entry_index=entry_i,
                entry_date=str(bars[entry_i].get("date") or bars[entry_i].get("datetime") or entry_i),
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                exit_index=exit_i,
                exit_date=str(bars[exit_i].get("date") or bars[exit_i].get("datetime") or exit_i),
                exit_price=exit_px,
                exit_reason=reason,
                initial_risk=risk,
                pnl_price=pnl,
                r_multiple=round(r_mult, 4),
                cost_price=cost,
                timeframe=sig.timeframe,
            )
        )
    return trades, skipped


def summarize_trades(trades: list[LspTrade]) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "win_rate": None,
            "avg_r": None,
            "sum_r": None,
            "stops": 0,
            "targets": 0,
        }
    rs = [t.r_multiple for t in trades]
    wins = sum(1 for r in rs if r > 0)
    return {
        "n": len(trades),
        "win_rate": round(wins / len(trades), 4),
        "avg_r": round(sum(rs) / len(rs), 4),
        "sum_r": round(sum(rs), 4),
        "stops": sum(1 for t in trades if t.exit_reason == "stop"),
        "targets": sum(1 for t in trades if t.exit_reason == "target"),
    }
