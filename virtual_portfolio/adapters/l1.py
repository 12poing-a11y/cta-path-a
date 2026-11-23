# -*- coding: utf-8 -*-
"""Read-only L1 signal adapter.

True source: ``<root>/l1_report.json`` (not ``data/l1_report.json``).
Forbidden: import daily_update; call paper_book.refresh_paper_book; write l1/paper.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

L1_REL = Path("l1_report.json")
SOURCE_PATH = "l1_report.json"


def l1_report_path(root: Path) -> Path:
    return Path(root) / L1_REL


def content_hash(payload: dict[str, Any] | bytes | str) -> str:
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    return hashlib.sha256(raw).hexdigest()


def load_l1_snapshot(root: Path) -> dict[str, Any] | None:
    """Load root ``l1_report.json``. Missing / skipped → None. Read-only."""
    path = l1_report_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("skipped"):
        return None
    return data


def iter_signal_rows(snapshot: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield normalized rows from ``snapshot['signals']`` (display/archive only)."""
    asof = str(snapshot.get("asof") or "").strip()
    signals = snapshot.get("signals")
    if not isinstance(signals, list):
        return
    src_hash = content_hash(snapshot)
    for raw in signals:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip().upper()
        bar_date = raw.get("bar_date") or raw.get("date")
        yield {
            "signal_asof": asof,
            "symbol": code,
            "code": code,
            "ticker": raw.get("ticker"),
            "direction_raw": raw.get("direction"),
            "selected": bool(raw.get("selected")),
            "lots_l1": raw.get("lots_l1"),
            "sleeve": raw.get("sleeve"),
            "bucket": raw.get("bucket"),
            "bar_date": bar_date,
            "close": raw.get("close"),
            "atr": raw.get("atr"),
            "action": raw.get("action"),
            "align": raw.get("align"),
            "source_path": SOURCE_PATH,
            "source_hash": src_hash,
        }
