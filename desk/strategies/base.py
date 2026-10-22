# -*- coding: utf-8 -*-
"""Strategy registration types for the Streamlit research desk."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

Availability = Literal["ready", "kpi_only", "missing", "placeholder"]


@dataclass
class StrategySpec:
    """Declarative strategy adapter over existing engine JSON artifacts."""

    id: str
    name: str
    description: str
    curve_path: Path | None = None
    signal_path: Path | None = None
    tags: list[str] = field(default_factory=list)
    placeholder: bool = False
    # Optional custom loader: (repo_root, spec) -> dict payload
    loader: Callable[[Path, "StrategySpec"], dict[str, Any]] | None = None

    def resolve_curve(self, root: Path) -> Path | None:
        if self.curve_path is None:
            return None
        p = self.curve_path if self.curve_path.is_absolute() else root / self.curve_path
        return p

    def resolve_signal(self, root: Path) -> Path | None:
        if self.signal_path is None:
            return None
        p = self.signal_path if self.signal_path.is_absolute() else root / self.signal_path
        return p
