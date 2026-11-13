# -*- coding: utf-8 -*-
"""Quality record schema + config/version stamps for reproducible research."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def git_commit_short(root: Path | None = None) -> str | None:
    root = root or ROOT
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def config_version_stamp(root: Path | None = None) -> dict[str, Any]:
    """Stamp formal config files so reports never say only 'current Path-A params'."""
    root = root or ROOT
    return {
        "schema": "cta-config-version-v1",
        "git_commit": git_commit_short(root),
        "execution_rules_sha256": _file_sha256(root / "execution_rules.json"),
        "universe_sha256": _file_sha256(root / "universe.json"),
        "research_cost_sha256": _file_sha256(root / "research_cost.json"),
    }


def bar_quality_record(
    *,
    code: str,
    bar_date: str | None,
    status: str,
    data_valid: bool,
    tradable: bool,
    reasons: list[str],
    quality_score: float,
    price_basis: str = "contract",
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Unified per-bar quality payload (credibility, not a trade signal)."""
    out: dict[str, Any] = {
        "schema": "cta-bar-quality-v1",
        "code": str(code or "").upper(),
        "bar_date": bar_date,
        "status": status,
        "data_valid": bool(data_valid),
        "tradable": bool(tradable),
        "quality_score": round(float(quality_score), 4),
        "price_basis": price_basis,
        "reasons": list(reasons),
    }
    if extras:
        out["extras"] = extras
    return out


def dump_stamp_json(path: Path, root: Path | None = None) -> dict[str, Any]:
    stamp = config_version_stamp(root)
    path.write_text(json.dumps(stamp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stamp
