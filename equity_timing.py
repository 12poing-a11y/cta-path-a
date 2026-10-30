# -*- coding: utf-8 -*-
"""Equity-index timing: composite signal → suggested weight.

Spec: ``external/equity_timing_spec.json`` (上证50 / 沪深300 / 中证500 / 中证1000).
Factor values in {-1,-0.5,0,0.5,1}; category = mean of members; composite = mean
of all single-factor signals. Weight buckets map composite ∈ (-1,1] to
{-100%,-50%,0%,+50%,+100%}. Paper research only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
SPEC_PATH = ROOT / "external" / "equity_timing_spec.json"
ALLOWED = (-1.0, -0.5, 0.0, 0.5, 1.0)


def load_spec(path: Path | None = None) -> dict[str, Any]:
    p = path or SPEC_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_factor(value: Any) -> float | None:
    x = _num(value)
    if x is None:
        return None
    for a in ALLOWED:
        if abs(x - a) < 1e-9:
            return a
    return None


def mean_signal(values: Iterable[Any]) -> float | None:
    xs = [validate_factor(v) for v in values]
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return sum(xs) / len(xs)


def category_signals(groups: dict[str, list[Any]]) -> dict[str, float | None]:
    """groups: category_name -> list of single-factor levels."""
    return {name: mean_signal(vals) for name, vals in (groups or {}).items()}


def composite_from_factors(factors: list[Any]) -> float | None:
    return mean_signal(factors)


def composite_from_categories(category_avgs: dict[str, float | None]) -> float | None:
    xs = [v for v in (category_avgs or {}).values() if v is not None]
    if not xs:
        return None
    return sum(xs) / len(xs)


def suggested_weight(composite: float | None) -> dict[str, Any]:
    """Map composite signal to suggested weight per published buckets.

    Buckets are left-open, right-closed on (low, high], except the first which
    starts at -1 exclusive of nothing practical: values in (-1, -0.3] → -100%.
    Edge: exactly -1 treated as -100%; exactly 1 treated as +100%.
    """
    empty = {"weight": None, "label": "—", "bucket": "", "composite": composite}
    if composite is None:
        return empty
    x = float(composite)
    if x < -1.0 or x > 1.0:
        return {**empty, "label": "越界", "bucket": "out_of_range"}
    # Spec table (合成信号取值范围 → 建议权重)
    if x == -1.0 or (-1.0 < x <= -0.3):
        return {"weight": -1.0, "label": "-100%", "bucket": "(-1,-0.3]", "composite": x}
    if -0.3 < x <= -0.1:
        return {"weight": -0.5, "label": "-50%", "bucket": "(-0.3,-0.1]", "composite": x}
    if -0.1 < x <= 0.1:
        return {"weight": 0.0, "label": "0%", "bucket": "(-0.1,0.1]", "composite": x}
    if 0.1 < x <= 0.3:
        return {"weight": 0.5, "label": "50%", "bucket": "(0.1,0.3]", "composite": x}
    # (0.3, 1]
    return {"weight": 1.0, "label": "100%", "bucket": "(0.3,1]", "composite": x}


def pack_day(
    *,
    asof: str,
    target: str,
    factors: list[Any] | None = None,
    categories: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    """Build one research row: asof signal → predict t+1 open to t+2 open."""
    cat = category_signals(categories or {})
    if factors is not None:
        comp = composite_from_factors(factors)
    else:
        comp = composite_from_categories(cat)
    w = suggested_weight(comp)
    return {
        "asof": asof,
        "target": target,
        "predict_window": "t+1 open → t+2 open",
        "categories": cat,
        "composite": None if comp is None else round(float(comp), 6),
        "suggested_weight": w.get("weight"),
        "suggested_weight_label": w.get("label"),
        "bucket": w.get("bucket"),
        "style": "低胜率高赔率（胜率约40%-50%，盈亏比>2）",
    }


def demo_table() -> list[dict[str, Any]]:
    """Sanity rows for the five weight buckets."""
    probes = [-1.0, -0.5, -0.2, 0.0, 0.2, 0.5, 1.0]
    return [suggested_weight(x) for x in probes]


if __name__ == "__main__":
    for row in demo_table():
        print(row)
    sample = pack_day(
        asof="2026-10-20",
        target="HS300",
        categories={
            "估值": [1, 0.5, 0],
            "动量": [-0.5, 0, 0.5],
            "情绪": [0, 0, -1],
        },
    )
    print("sample", sample)
