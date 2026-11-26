# -*- coding: utf-8 -*-
"""Price matcher for the derived official main (design §6).

Why: `.cache/history/{code}0.json` is only rewritten when the daily job has to fill a gap (its last bar can be a
pre-close snapshot). `.cache/sina/<date>/{code}0.json` is rewritten every day with the final bars.

Rule: matcher = `.cache/history` rows, overridden by the newest `.cache/sina/<date>/` snapshot that contains the product
(snapshot wins on the same date). Checked on 2026-11-26: 101,935 overlapping bars, 22 differ, all on 2026-11-25 (the
history row was a pre-close snapshot). R8's frozen window ends 2025-12-31, so the frozen results do not use these rows.

The matcher is regenerated on every judge run and kept outside git (about 15 MB per rebuild).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C


def _load(p: Path) -> list[dict]:
    if not p.exists():
        return []
    rows = json.loads(p.read_text(encoding="utf-8"))
    return rows if isinstance(rows, list) else []


def latest_snapshot_dir(code: str, snapshots: Path | None = None) -> Path | None:
    root = Path(snapshots or C.SINA_SNAPSHOTS)
    if not root.exists():
        return None
    for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):  # ISO dates sort lexically
        if (d / f"{code}0.json").exists():
            return d
    return None


def merged_series(code: str, history: Path | None = None, snapshots: Path | None = None) -> tuple[list[dict], str | None]:
    hist_dir = Path(history or (C.ROOT / ".cache" / "history"))
    by: dict[str, dict] = {}
    for row in _load(hist_dir / f"{code}0.json"):
        by[str(row.get("date"))[:10]] = row
    snap = latest_snapshot_dir(code, snapshots)
    if snap is not None:
        for row in _load(snap / f"{code}0.json"):
            by[str(row.get("date"))[:10]] = row  # the snapshot is the final/newer version of the same date
    return [by[k] for k in sorted(by)], (snap.name if snap is not None else None)


def build_matcher(codes=None, history=None, snapshots=None, out_dir: Path | None = None) -> dict[str, str | None]:
    """Write one merged series per product. Returns {code: snapshot date used (None = history only)}."""
    out = Path(out_dir or C.MATCHER)
    out.mkdir(parents=True, exist_ok=True)
    used: dict[str, str | None] = {}
    for code in (codes or C.PRODUCTS):
        rows, snap = merged_series(code, history=history, snapshots=snapshots)
        (out / f"{code}0.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        used[code] = snap
    return used
