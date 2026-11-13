# -*- coding: utf-8 -*-
"""Experiment registry on top of research_experiment (append-only, paper only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_experiment import record_experiment

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "data" / "experiments" / "ledger.jsonl"


def register_experiment(
    *,
    name: str,
    kind: str,
    params: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    artifact: str | None = None,
    status: str = "Research",
    notes: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """status ∈ Research | Shadow | Approved — never auto-writes execution_rules."""
    root = root or ROOT
    status = str(status or "Research")
    if status not in ("Research", "Shadow", "Approved"):
        status = "Research"
    merged_metrics = dict(metrics or {})
    if validation:
        merged_metrics["validation"] = validation
    row = record_experiment(
        name=name,
        kind=kind,
        params={**(params or {}), "status": status},
        metrics=merged_metrics,
        artifact=artifact,
        notes=notes,
        root=root,
    )
    row["status"] = status
    return row


def load_ledger(root: Path | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    root = root or ROOT
    path = root / "data" / "experiments" / "ledger.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]
