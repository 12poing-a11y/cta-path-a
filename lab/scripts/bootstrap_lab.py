# -*- coding: utf-8 -*-
"""Create Plan A directory tree under lab/ on D:."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
DIRS = [
    "data/raw",
    "data/bars/continuous",
    "data/bars/delivery",
    "data/factors",
    "research/ic",
    "research/oos",
    "research/runs",
]


def main() -> None:
    for rel in DIRS:
        (LAB / rel).mkdir(parents=True, exist_ok=True)
        keep = LAB / rel / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
    meta = {
        "bootstrapped_at": datetime.now(timezone.utc).isoformat(),
        "plan": "A",
        "root": str(LAB).replace("\\", "/"),
    }
    (LAB / "research" / "runs" / "bootstrap.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[lab] bootstrapped {LAB}")


if __name__ == "__main__":
    main()
