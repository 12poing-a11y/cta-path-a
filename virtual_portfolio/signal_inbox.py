# -*- coding: utf-8 -*-
"""VP Phase 1B-0 signal inbox — archive L1 snapshots; never touch account ledger."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from virtual_portfolio.adapters.l1 import (
    SOURCE_PATH,
    content_hash,
    iter_signal_rows,
    l1_report_path,
    load_l1_snapshot,
)
from virtual_portfolio.guard import VpGuardError, assert_vp_write_path
from virtual_portfolio.instruments import get_instrument
from virtual_portfolio.paths import (
    signal_inbox_by_asof_path,
    signal_inbox_dir,
    signal_inbox_events_path,
    signal_inbox_latest_path,
    signal_inbox_rejects_path,
    vp_runtime_path,
)
from virtual_portfolio.permissions import (
    VpPermissionError,
    assert_signal_read_allowed,
    default_runtime_flags,
    resolve_runtime,
)

INBOX_SCHEMA = "cta-vp-signal-inbox-v1"


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _write_json(path: Path, root: Path, doc: dict[str, Any]) -> None:
    assert_vp_write_path(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert_vp_write_path(path.parent, root)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, root: Path, row: dict[str, Any]) -> None:
    assert_vp_write_path(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert_vp_write_path(path.parent, root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_vp_runtime(root: Path) -> dict[str, Any]:
    """Fail-closed VP operational flags from ``data/virtual_portfolio/runtime.json``."""
    doc = _read_json(vp_runtime_path(root)) or {}
    return resolve_runtime({**default_runtime_flags(), **doc})


def set_signal_read_allowed(root: Path, allowed: bool) -> dict[str, Any]:
    """Persist SIGNAL_READ_ALLOWED under VP data namespace (does not touch SIGNAL_INGEST)."""
    path = vp_runtime_path(root)
    cur = _read_json(path) or {}
    cur["SIGNAL_READ_ALLOWED"] = bool(allowed)
    # Keep ingest/auto closed unless already explicitly set (default false via resolve).
    cur.setdefault("SIGNAL_INGEST_ALLOWED", False)
    cur.setdefault("AUTO_OPEN_ALLOWED", False)
    cur.setdefault("AUTO_CLOSE_ALLOWED", False)
    _write_json(path, root, cur)
    return load_vp_runtime(root)


def row_idempotency_key(
    *,
    signal_asof: str,
    code: str,
    direction_raw: Any,
    source_hash: str,
) -> str:
    prefix = (source_hash or "")[:16]
    raw = f"{signal_asof}|{code}|{direction_raw}|{prefix}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_rows(root: Path, snapshot: dict[str, Any], *, received_at: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    src_hash = content_hash(snapshot)
    quality_ok = snapshot.get("quality_ok")
    for row in iter_signal_rows(snapshot):
        code = str(row.get("code") or "").upper()
        flags: list[str] = []
        if not code:
            flags.append("MISSING_CODE")
        else:
            inst = get_instrument(root, code, asof=None)
            if inst is None:
                flags.append("UNMAPPED")
        if quality_ok is False:
            flags.append("QUALITY_WARN")
        direction_raw = row.get("direction_raw")
        key = row_idempotency_key(
            signal_asof=str(row.get("signal_asof") or ""),
            code=code,
            direction_raw=direction_raw,
            source_hash=src_hash,
        )
        out.append(
            {
                **row,
                "received_at": received_at,
                "idempotency_key": key,
                "flags": flags,
            }
        )
    return out


def ingest_l1_to_inbox(
    root: Path,
    *,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read L1 → validate → write signal_inbox. Never mutates account ledgers."""
    rt = runtime if runtime is not None else load_vp_runtime(root)
    assert_signal_read_allowed(rt)

    received_at = _iso_now()
    path = l1_report_path(root)
    events_path = signal_inbox_events_path(root)
    rejects_path = signal_inbox_rejects_path(root)

    if not path.is_file():
        reject = {
            "status": "REJECTED",
            "reason": "MISSING_L1",
            "path": SOURCE_PATH,
            "received_at": received_at,
        }
        signal_inbox_dir(root, create=True)
        _append_jsonl(rejects_path, root, reject)
        _append_jsonl(events_path, root, {**reject, "event": "ingest"})
        return reject

    try:
        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        reject = {
            "status": "REJECTED",
            "reason": "BAD_JSON",
            "error": str(exc),
            "path": SOURCE_PATH,
            "received_at": received_at,
        }
        signal_inbox_dir(root, create=True)
        _append_jsonl(rejects_path, root, reject)
        _append_jsonl(events_path, root, {**reject, "event": "ingest"})
        return reject

    if not isinstance(data, dict):
        reject = {
            "status": "REJECTED",
            "reason": "NOT_OBJECT",
            "path": SOURCE_PATH,
            "received_at": received_at,
        }
        signal_inbox_dir(root, create=True)
        _append_jsonl(rejects_path, root, reject)
        _append_jsonl(events_path, root, {**reject, "event": "ingest"})
        return reject

    if data.get("skipped"):
        reject = {
            "status": "REJECTED",
            "reason": "SKIPPED",
            "path": SOURCE_PATH,
            "received_at": received_at,
        }
        signal_inbox_dir(root, create=True)
        _append_jsonl(rejects_path, root, reject)
        _append_jsonl(events_path, root, {**reject, "event": "ingest"})
        return reject

    asof = str(data.get("asof") or "").strip()
    if not asof:
        reject = {
            "status": "REJECTED",
            "reason": "MISSING_ASOF",
            "path": SOURCE_PATH,
            "received_at": received_at,
        }
        signal_inbox_dir(root, create=True)
        _append_jsonl(rejects_path, root, reject)
        _append_jsonl(events_path, root, {**reject, "event": "ingest"})
        return reject

    if not isinstance(data.get("signals"), list):
        reject = {
            "status": "REJECTED",
            "reason": "SIGNALS_NOT_LIST",
            "signal_asof": asof,
            "path": SOURCE_PATH,
            "received_at": received_at,
        }
        signal_inbox_dir(root, create=True)
        _append_jsonl(rejects_path, root, reject)
        _append_jsonl(events_path, root, {**reject, "event": "ingest"})
        return reject

    src_hash = content_hash(data)
    rows = _normalize_rows(root, data, received_at=received_at)
    by_asof = signal_inbox_by_asof_path(root, asof)
    existing = _read_json(by_asof)

    if existing and existing.get("source_hash") == src_hash:
        signal_inbox_dir(root, create=True)
        dup = {
            "status": "DUPLICATE",
            "signal_asof": asof,
            "source_hash": src_hash,
            "n_rows": len(existing.get("rows") or []),
            "received_at": received_at,
            "path": SOURCE_PATH,
        }
        _append_jsonl(
            events_path,
            root,
            {**dup, "event": "ingest", "note": "same asof+source_hash"},
        )
        return dup

    # Merge by idempotency_key if re-ingest with different hash (replace snapshot).
    doc = {
        "schema": INBOX_SCHEMA,
        "signal_asof": asof,
        "source_path": SOURCE_PATH,
        "source_hash": src_hash,
        "quality_ok": data.get("quality_ok"),
        "received_at": received_at,
        "n_rows": len(rows),
        "n_unmapped": sum(1 for r in rows if "UNMAPPED" in (r.get("flags") or [])),
        "n_quality_warn": sum(1 for r in rows if "QUALITY_WARN" in (r.get("flags") or [])),
        "rows": rows,
        # Keep a compact raw header for audit (not full formal rewrite).
        "l1_header": {
            "asof": asof,
            "session_date": data.get("session_date"),
            "updated_at": data.get("updated_at"),
            "quality_ok": data.get("quality_ok"),
            "n_signals": len(data.get("signals") or []),
        },
    }
    signal_inbox_dir(root, create=True)
    by_asof.parent.mkdir(parents=True, exist_ok=True)
    assert_vp_write_path(by_asof.parent, root)
    _write_json(by_asof, root, doc)

    latest = {
        "schema": INBOX_SCHEMA,
        "signal_asof": asof,
        "source_hash": src_hash,
        "received_at": received_at,
        "n_rows": len(rows),
        "n_unmapped": doc["n_unmapped"],
        "status": "OK",
        "by_asof_rel": f"by_asof/{asof}.json",
    }
    _write_json(signal_inbox_latest_path(root), root, latest)
    _append_jsonl(
        events_path,
        root,
        {
            "event": "ingest",
            "status": "OK",
            "signal_asof": asof,
            "source_hash": src_hash,
            "n_rows": len(rows),
            "received_at": received_at,
        },
    )
    return {**latest, "status": "OK"}


def list_inbox_asofs(root: Path) -> list[str]:
    d = signal_inbox_dir(root) / "by_asof"
    if not d.is_dir():
        return []
    out = [p.stem for p in d.glob("*.json")]
    return sorted(out)


def load_inbox_asof(root: Path, asof: str) -> dict[str, Any] | None:
    return _read_json(signal_inbox_by_asof_path(root, str(asof).strip()))


def load_inbox_latest(root: Path) -> dict[str, Any] | None:
    return _read_json(signal_inbox_latest_path(root))


def load_inbox_events(root: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    path = signal_inbox_events_path(root)
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
    return rows[-limit:]


# Re-export for tests / callers that probe guard behavior.
__all__ = [
    "VpGuardError",
    "VpPermissionError",
    "ingest_l1_to_inbox",
    "list_inbox_asofs",
    "load_inbox_asof",
    "load_inbox_events",
    "load_inbox_latest",
    "load_vp_runtime",
    "set_signal_read_allowed",
    "load_l1_snapshot",
]
