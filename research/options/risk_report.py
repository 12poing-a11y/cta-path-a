# -*- coding: utf-8 -*-
"""Options research risk summary (isolated from Path-A)."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.options.backtest.engine import load_latest_bt
from research.options.paper.ledger import load_ledger

OUT_REL = Path("data") / "options" / "risk_reports"
LATEST_NAME = "latest.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def report_dir(root: Path) -> Path:
    d = Path(root) / OUT_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_risk_report(root: Path, *, write: bool = True) -> dict[str, Any]:
    ledger = load_ledger(root)
    bt = load_latest_bt(root) or {}
    by_code: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0, "margin": 0.0, "pnl": 0.0})
    reject_skips = 0
    for t in bt.get("trades") or []:
        if t.get("reason") == "quality_reject":
            reject_skips += 1
        if t.get("status") != "closed":
            continue
        code = str(t.get("code") or "?")
        by_code[code]["n"] += 1
        by_code[code]["margin"] += float(t.get("margin_est_cny") or 0)
        by_code[code]["pnl"] += float(t.get("pnl_cny") or 0)

    openish = [r for r in ledger if r.get("exit_asof") is None and r.get("pnl_cny") is None]
    same_dir_exposure = defaultdict(int)
    for r in ledger:
        code = str(r.get("code") or "")
        kind = str(r.get("kind") or "")
        same_dir_exposure[f"{code}:{kind}"] += 1

    out = {
        "schema": "cta-options-risk-v1",
        "built_at": _iso_now(),
        "strategy_state": bt.get("strategy_state") or "RESEARCH",
        "bt_metrics": bt.get("metrics"),
        "ledger_n": len(ledger),
        "ledger_open_ish": len(openish),
        "quality_reject_skips": reject_skips,
        "by_code": {k: dict(v) for k, v in sorted(by_code.items())},
        "same_direction_counts": dict(sorted(same_dir_exposure.items())),
        "disclaimer": "Research approximate margin; not exchange SPAN; not Path-A formal risk.",
    }
    if write:
        path = report_dir(root) / LATEST_NAME
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        out["path"] = str(path)
    return out
