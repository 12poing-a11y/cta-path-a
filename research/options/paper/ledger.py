# -*- coding: utf-8 -*-
"""Options research paper trades — physically separate from paper_book."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "cta-options-paper-v1"
OUT_REL = Path("data") / "options" / "paper_trades"
LEDGER_NAME = "ledger.jsonl"
STATUS_ORDER = ("RESEARCH", "WARN", "PAPER_CANDIDATE")


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def out_dir(root: Path) -> Path:
    d = Path(root) / OUT_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path(root: Path) -> Path:
    return out_dir(root) / LEDGER_NAME


def trade_fingerprint(row: dict[str, Any]) -> str:
    key = "|".join(
        [
            str(row.get("strategy_id") or ""),
            str(row.get("code") or ""),
            str(row.get("asof") or ""),
            str(row.get("kind") or ""),
            str((row.get("short") or {}).get("strike") or ""),
            str((row.get("long") or {}).get("strike") or ""),
            str(row.get("credit_points") or ""),
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_ledger(root: Path) -> list[dict[str, Any]]:
    path = ledger_path(root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def append_trade(root: Path, trade: dict[str, Any], *, status: str = "RESEARCH") -> dict[str, Any]:
    """Idempotent append by fingerprint. Never touches Path-A paper_book."""
    if status not in STATUS_ORDER:
        raise ValueError(f"status 须为 {STATUS_ORDER}")
    row = {
        "schema": SCHEMA,
        "fp": trade_fingerprint(trade),
        "recorded_at": _iso_now(),
        "strategy_id": trade.get("strategy_id") or "credit_vertical",
        "code": trade.get("code"),
        "asof": trade.get("asof") or trade.get("entry_asof"),
        "kind": trade.get("kind"),
        "legs": [
            trade.get("short"),
            trade.get("long"),
        ],
        "credit": trade.get("credit_points"),
        "margin_est": trade.get("margin_est_cny"),
        "pricing_mode": trade.get("pricing_mode"),
        "quality": trade.get("quality_status") or trade.get("quality"),
        "status": status,
        "pnl_points": trade.get("pnl_points"),
        "pnl_cny": trade.get("pnl_cny"),
        "exit_asof": trade.get("exit_asof"),
        "exit_reason": trade.get("exit_reason"),
    }
    existing = {r.get("fp") for r in load_ledger(root)}
    if row["fp"] in existing:
        row["deduped"] = True
        return row
    path = ledger_path(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    row["deduped"] = False
    return row


def ingest_bt_closed(root: Path, bt: dict[str, Any], *, status: str | None = None) -> dict[str, Any]:
    """Append closed BT trades into research paper ledger."""
    st = status or (bt.get("strategy_state") if bt.get("strategy_state") in STATUS_ORDER else "WARN")
    n_new = 0
    n_dup = 0
    for t in bt.get("trades") or []:
        if t.get("status") != "closed":
            continue
        row = append_trade(root, t, status=str(st))
        if row.get("deduped"):
            n_dup += 1
        else:
            n_new += 1
    return {"n_new": n_new, "n_dup": n_dup, "status": st, "path": str(ledger_path(root))}
