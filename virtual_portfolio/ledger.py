# -*- coding: utf-8 -*-
"""Append-only VP ledger. Never rewrites history rows."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from virtual_portfolio.guard import assert_vp_write_path
from virtual_portfolio.paths import account_dir, ledger_path

SCHEMA = "cta-vp-ledger-v1"


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def event_id(payload: dict[str, Any]) -> str:
    """Stable idempotency key from business fields (not recorded_at)."""
    parts = [
        str(payload.get("account_id") or ""),
        str(payload.get("kind") or ""),
        str(payload.get("client_event_id") or ""),
        str(payload.get("symbol") or ""),
        str(payload.get("side") or ""),
        str(payload.get("asof") or ""),
        str(payload.get("qty") or ""),
        str(payload.get("price") or ""),
        str(payload.get("source") or ""),
        str(payload.get("note") or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]


def load_events(root: Path, account_id: str) -> list[dict[str, Any]]:
    path = ledger_path(root, account_id)
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


def append_event(
    root: Path,
    account_id: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Append event if event_id unseen; otherwise return existing with deduped=True."""
    account_dir(root, account_id, create=True)
    path = ledger_path(root, account_id)
    assert_vp_write_path(path, root)

    row = dict(event)
    row["schema"] = SCHEMA
    row["account_id"] = account_id
    row.setdefault("recorded_at", _iso_now())
    if not row.get("event_id"):
        row["event_id"] = event_id(row)

    existing = load_events(root, account_id)
    for prev in existing:
        if prev.get("event_id") == row["event_id"]:
            out = dict(prev)
            out["deduped"] = True
            return out

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    row["deduped"] = False
    return row
