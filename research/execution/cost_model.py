# -*- coding: utf-8 -*-
"""Base / Stress / Extreme cost scenarios on top of research_cost.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIOS = {
    "base": {"slippage_ticks_mult": 1.0, "fee_mult": 1.0},
    "stress": {"slippage_ticks_mult": 2.0, "fee_mult": 1.25},
    "extreme": {"slippage_ticks_mult": 4.0, "fee_mult": 1.5},
}


def _load_raw(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    path = root / "research_cost.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_cost_scenarios(root: Path | None = None) -> list[str]:
    raw = _load_raw(root)
    scenarios = raw.get("scenarios") or DEFAULT_SCENARIOS
    return sorted(scenarios.keys())


def load_cost_scenario(name: str = "base", root: Path | None = None) -> dict[str, Any]:
    raw = _load_raw(root)
    name = str(name or "base").strip().lower()
    scenarios = raw.get("scenarios") or DEFAULT_SCENARIOS
    if name not in scenarios:
        raise KeyError(f"unknown cost scenario: {name}; have {sorted(scenarios)}")
    sc = dict(scenarios[name])
    path_a = dict(raw.get("path_a_fill") or {})
    base_ticks = float(path_a.get("slippage_ticks") or 1.0)
    mult = float(sc.get("slippage_ticks_mult") or 1.0)
    fee_mult = float(sc.get("fee_mult") or 1.0)
    return {
        "schema": "cta-cost-scenario-v1",
        "name": name,
        "slippage_ticks": base_ticks * mult,
        "slippage_ticks_mult": mult,
        "fee_mult": fee_mult,
        "fill_price": path_a.get("fill_price") or "next_open",
        "note": sc.get("note") or "",
        "live_trading": bool(raw.get("live_trading")),
        "sleeve_proxy": dict(raw.get("sleeve_proxy") or {}),
        "benchmark_equity": raw.get("benchmark_equity"),
    }


def scenario_slippage_ticks(name: str = "base", root: Path | None = None) -> float:
    return float(load_cost_scenario(name, root=root)["slippage_ticks"])
