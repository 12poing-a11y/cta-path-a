# -*- coding: utf-8 -*-
"""Write-path fence: VP may only touch data/virtual_portfolio/**."""
from __future__ import annotations

from pathlib import Path

VP_DATA_REL = Path("data") / "virtual_portfolio"


class VpGuardError(RuntimeError):
    """Raised when a write escapes the VP namespace."""


def vp_data_root(root: Path) -> Path:
    return Path(root).resolve() / VP_DATA_REL


def assert_vp_write_path(path: Path, root: Path) -> Path:
    """Ensure ``path`` resolves under ``data/virtual_portfolio`` for ``root``."""
    root_r = Path(root).resolve()
    path_r = Path(path).resolve()
    allowed = (root_r / VP_DATA_REL).resolve()
    try:
        path_r.relative_to(allowed)
    except ValueError as exc:
        raise VpGuardError(
            f"VP write rejected outside {allowed}: {path_r}"
        ) from exc
    # Soft check: never allow classic formal artifacts even if somehow nested.
    name = path_r.name.lower()
    banned = (
        "paper_book_latest.json",
        "l1_report.json",
        "l1_report_fingerprint.json",
        "universe.json",
    )
    if name in banned:
        raise VpGuardError(f"VP write banned formal artifact name: {name}")
    return path_r
