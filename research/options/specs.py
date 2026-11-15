# -*- coding: utf-8 -*-
"""CZCE option/futures contract specs for options research (CF / SR / MA first).

Values are research approximations aligned with Path-A `universe.json` multipliers
and publicly documented CZCE contract sizes. Margin helpers are coarse — not for
exchange clearing or Path-A formal sizing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OptionProductSpec:
    code: str
    label: str
    exchange: str
    multiplier: float  # tons (or units) per lot
    futures_tick: float  # min price change of underlying futures
    option_tick: float  # min price change of option premium (points)
    # Research-only margin proxies (fraction of notional or explicit notes)
    futures_margin_rate: float
    note: str

    def point_value_cny(self) -> float:
        """CNY per 1.0 price point per lot."""
        return float(self.multiplier)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["point_value_cny"] = self.point_value_cny()
        return d


# Primary stage-1 set (see docs/options/SPECS_CF_SR_MA.md).
SPECS: dict[str, OptionProductSpec] = {
    "CF": OptionProductSpec(
        code="CF",
        label="棉花",
        exchange="CZCE",
        multiplier=5.0,
        futures_tick=5.0,
        option_tick=5.0,
        futures_margin_rate=0.09,
        note="mult/tick align universe.json + gamma_wall; option_tick≈futures tick",
    ),
    "SR": OptionProductSpec(
        code="SR",
        label="白糖",
        exchange="CZCE",
        multiplier=10.0,
        futures_tick=1.0,
        option_tick=0.5,
        futures_margin_rate=0.08,
        note="option min change often 0.5 yuan/ton (research); verify before live",
    ),
    "MA": OptionProductSpec(
        code="MA",
        label="甲醇",
        exchange="CZCE",
        multiplier=10.0,
        futures_tick=1.0,
        option_tick=1.0,
        futures_margin_rate=0.09,
        note="mult/tick align universe.json + gamma_wall",
    ),
}

# Observe-only extras already in gamma_wall (not stage-1 credit BT focus).
OBSERVE_EXTRA: dict[str, OptionProductSpec] = {
    "TA": OptionProductSpec(
        code="TA",
        label="PTA",
        exchange="CZCE",
        multiplier=5.0,
        futures_tick=2.0,
        option_tick=2.0,
        futures_margin_rate=0.09,
        note="observe; stage-1 credit BT deferred",
    ),
    "SA": OptionProductSpec(
        code="SA",
        label="纯碱",
        exchange="CZCE",
        multiplier=20.0,
        futures_tick=1.0,
        option_tick=1.0,
        futures_margin_rate=0.09,
        note="observe; stage-1 credit BT deferred",
    ),
    "RM": OptionProductSpec(
        code="RM",
        label="菜粕",
        exchange="CZCE",
        multiplier=10.0,
        futures_tick=1.0,
        option_tick=1.0,
        futures_margin_rate=0.08,
        note="observe; stage-1 credit BT deferred",
    ),
    "OI": OptionProductSpec(
        code="OI",
        label="菜油",
        exchange="CZCE",
        multiplier=10.0,
        futures_tick=1.0,
        option_tick=1.0,
        futures_margin_rate=0.08,
        note="observe; stage-1 credit BT deferred",
    ),
    "FG": OptionProductSpec(
        code="FG",
        label="玻璃",
        exchange="CZCE",
        multiplier=20.0,
        futures_tick=1.0,
        option_tick=1.0,
        futures_margin_rate=0.09,
        note="observe; stage-1 credit BT deferred",
    ),
}


def get_spec(code: str, *, include_observe: bool = False) -> OptionProductSpec:
    c = str(code or "").strip().upper()
    if c in SPECS:
        return SPECS[c]
    if include_observe and c in OBSERVE_EXTRA:
        return OBSERVE_EXTRA[c]
    raise KeyError(f"未知期权研究品种: {code}")


def list_stage1_codes() -> list[str]:
    return list(SPECS.keys())


def credit_vertical_margin_est(
    *,
    width_points: float,
    credit_points: float,
    multiplier: float,
) -> dict[str, float]:
    """Coarse research margin for a vertical credit spread.

    Uses max-loss approximation: (width − credit) × multiplier CNY/lot.
    This is NOT exchange SPAN / CZCE portfolio margin.
    """
    w = float(width_points)
    cr = float(credit_points)
    m = float(multiplier)
    if w <= 0 or m <= 0:
        raise ValueError("width_points 与 multiplier 必须大于 0")
    max_loss_points = max(0.0, w - cr)
    return {
        "width_points": w,
        "credit_points": cr,
        "max_loss_points": max_loss_points,
        "margin_est_cny": max_loss_points * m,
        "approx": "max_loss",  # research only; not exchange SPAN
    }


def credit_vertical_margin_cny(
    *,
    width_points: float,
    credit_points: float,
    multiplier: float,
) -> float:
    return float(
        credit_vertical_margin_est(
            width_points=width_points,
            credit_points=credit_points,
            multiplier=multiplier,
        )["margin_est_cny"]
    )


def slip_discount_points(*, slip_ticks: float, option_tick: float) -> float:
    """Points shaved from settle credit when Bid/Ask unavailable."""
    return max(0.0, float(slip_ticks)) * float(option_tick)
