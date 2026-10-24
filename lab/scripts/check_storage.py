# -*- coding: utf-8 -*-
"""Report D: free space vs Plan A budget."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parent
BUDGET = LAB / "config" / "storage_budget.json"


def _dir_gb(path: Path) -> float:
    if not path.is_dir():
        return 0.0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total / (1024**3)


def main() -> int:
    cfg = json.loads(BUDGET.read_text(encoding="utf-8"))
    soft = float(cfg["budget_gb"]["soft"])
    hard = float(cfg["budget_gb"]["hard"])
    warn = float(cfg["budget_gb"]["warn_free_gb"])
    usage = shutil.disk_usage("D:/")
    free_gb = usage.free / (1024**3)
    lab_gb = _dir_gb(LAB)
    cache_gb = _dir_gb(ROOT / ".cache")
    print(f"D: free = {free_gb:.2f} GB")
    print(f"lab/   = {lab_gb:.3f} GB (budget soft {soft} / hard {hard})")
    print(f".cache = {cache_gb:.3f} GB (Path-A shared)")
    if free_gb < warn:
        print(f"WARN: D: free < {warn} GB")
        return 2
    if lab_gb > hard:
        print(f"FAIL: lab exceeds hard budget {hard} GB")
        return 1
    if lab_gb > soft:
        print(f"NOTE: lab above soft budget {soft} GB (still OK until {hard})")
    else:
        print("OK: within Plan A soft budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
