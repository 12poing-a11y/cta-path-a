# -*- coding: utf-8 -*-
"""Append-only research experiment log (Stage-0 infra). Paper only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "data" / "experiments"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LATEST = LOG_DIR / "latest.json"
LEDGER = LOG_DIR / "ledger.jsonl"


def _iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_cost_cfg(root: Path | None = None) -> dict[str, Any]:
    p = (root or ROOT) / "research_cost.json"
    if not p.is_file():
        return {"live_trading": False, "sleeve_proxy": {"cost_bps_one_way": 3.0}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"live_trading": False}


def record_experiment(
    *,
    name: str,
    kind: str,
    params: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    artifact: str | None = None,
    notes: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """Write one experiment row; never mutates live trading paths."""
    root = root or ROOT
    row = {
        "ts": _iso(),
        "name": name,
        "kind": kind,
        "params": params or {},
        "metrics": metrics or {},
        "artifact": artifact,
        "notes": notes,
        "live_trading": False,
        "git_hint": "see repo HEAD; CI pytest gates formal Path-A reports",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (LOG_DIR / "latest.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return row
