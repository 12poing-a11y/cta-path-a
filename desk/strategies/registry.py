# -*- coding: utf-8 -*-
"""Built-in + extra JSON strategy registry for the research desk."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from desk.strategies.base import StrategySpec

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRA_DIR = Path(__file__).resolve().parent / "extra"


def _builtin() -> list[StrategySpec]:
    return [
        StrategySpec(
            id="path_a",
            name="路径A seats",
            description="L1 seats 路径A 历史纸面回测（historical_backtest_latest.json）",
            curve_path=Path("historical_backtest_latest.json"),
            signal_path=Path("l1_report.json"),
            tags=["path_a", "seats", "l1"],
        ),
        StrategySpec(
            id="benchmark",
            name="对照 slow/fast/carry",
            description="对照组合；曲线由 benchmark_stack 落盘后可用，缺曲线时仅 KPI",
            curve_path=Path("benchmark_latest.json"),
            signal_path=Path("benchmark_latest.json"),
            tags=["benchmark", "slow", "fast", "carry"],
        ),
        StrategySpec(
            id="path_a_opt_hedge",
            name="路径A+保护期权",
            description="优先 _art_opt 产物；否则回退主回测且 option_hedge=true 的 JSON",
            curve_path=Path("_art_opt/historical_backtest_latest.json"),
            tags=["path_a", "option_hedge", "observe"],
            loader=_load_opt_hedge,
        ),
    ]


def _load_opt_hedge(root: Path, spec: StrategySpec) -> dict[str, Any]:
    """Prefer _art_opt artifact; fall back to any option_hedge=true curve JSON."""
    candidates = [
        root / "_art_opt" / "historical_backtest_latest.json",
        root / "_bt_opt.json",
        root / "historical_backtest_latest.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if path.name == "historical_backtest_latest.json" and path.parent == root:
            if not data.get("option_hedge"):
                continue
        data = dict(data)
        data["_desk_source"] = str(path.relative_to(root))
        return data
    return {"_desk_missing": True, "_desk_tried": [str(p) for p in candidates]}


def _load_extra_json(path: Path) -> StrategySpec | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sid = str(raw.get("id") or path.stem).strip()
    if not sid:
        return None
    name = str(raw.get("name") or sid)
    desc = str(raw.get("description") or f"extra strategy from {path.name}")
    curve = raw.get("curve_file") or raw.get("curve_path")
    signal = raw.get("signal_file") or raw.get("signal_path")
    if raw.get("placeholder"):
        return None
    tags = list(raw.get("tags") or ["extra"])
    return StrategySpec(
        id=sid,
        name=name,
        description=desc,
        curve_path=Path(curve) if curve else None,
        signal_path=Path(signal) if signal else None,
        tags=tags,
        placeholder=bool(raw.get("placeholder")),
    )


def scan_extra(extra_dir: Path | None = None) -> list[StrategySpec]:
    d = extra_dir or EXTRA_DIR
    if not d.is_dir():
        return []
    out: list[StrategySpec] = []
    for path in sorted(d.glob("*.json")):
        spec = _load_extra_json(path)
        if spec is not None:
            out.append(spec)
    return out


def all_strategies(root: Path | None = None, extra_dir: Path | None = None) -> list[StrategySpec]:
    _ = root  # reserved for future path rewrites
    by_id: dict[str, StrategySpec] = {}
    for spec in _builtin():
        by_id[spec.id] = spec
    for spec in scan_extra(extra_dir):
        by_id[spec.id] = spec  # extra overrides same id
    return list(by_id.values())


def get_strategy(strategy_id: str, root: Path | None = None) -> StrategySpec | None:
    for spec in all_strategies(root):
        if spec.id == strategy_id:
            return spec
    return None
