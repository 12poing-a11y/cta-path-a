# -*- coding: utf-8 -*-
"""Formal-rule lock for weekly / formal batch runs (fix3).

* execution_rules.json sha256 is computed after normalising line endings
  (CRLF/CR -> LF) so Windows checkouts hash the same as CI.
* Run params loaded from universe.json must equal execution_rules.json.
* Simulated fill_series must equal the locked value ("mixed").
* Formal results are not written from a dirty working tree.
Any mismatch raises RuleLockError; callers must not emit numbers.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

LOCK_FILE = "configs/formal_rule_lock.json"
# Paths a batch run itself is allowed to touch (data caches / outputs).
DIRTY_IGNORE_PREFIXES = (
    ".cache/",
    "archive/",
    "data/",
    "lab/data/",
    "weekly_backtest_latest.json",
    "equity_state.json",
)
PARAM_MAP = {
    # execution_rules key -> _load_cfg() key
    "stop_atr_mult": "stop_atr_mult",
    "reward_rr": "reward_rr",
    "min_r20_pct": "min_r20",
    "min_r60_pct": "min_r60",
    "max_positions": "max_positions",
    "max_per_bucket": "max_per_bucket",
    "risk_pct": "risk_pct",
    "entry_filter": "entry_filter",
    "fill_price": "fill_price",
    "availability_lag_days": "availability_lag",
}


class RuleLockError(RuntimeError):
    pass


def normalized_sha256(path: Path) -> str:
    raw = Path(path).read_bytes()
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(raw).hexdigest()


def load_lock(root: Path) -> dict:
    p = Path(root) / LOCK_FILE
    if not p.exists():
        raise RuleLockError(f"missing {LOCK_FILE}")
    return json.loads(p.read_text(encoding="utf-8"))


def _eq(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a) == str(b)


def check_rules(root: Path, p: dict | None = None) -> dict:
    """Pre-run check: rule file hash + loaded params == formal rules."""
    root = Path(root)
    lock = load_lock(root)
    rules_path = root / "execution_rules.json"
    sha = normalized_sha256(rules_path)
    errs = []
    if sha != lock.get("execution_rules_sha256_lf"):
        errs.append(f"execution_rules sha(LF) {sha[:12]} != lock {str(lock.get('execution_rules_sha256_lf'))[:12]}")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    if p is not None:
        for rk, pk in PARAM_MAP.items():
            if rk in rules and not _eq(rules[rk], p.get(pk)):
                errs.append(f"param {pk}={p.get(pk)!r} != execution_rules.{rk}={rules[rk]!r}")
    if errs:
        raise RuleLockError("; ".join(errs))
    return {"execution_rules_sha256_lf": sha, "fill_series_required": lock.get("fill_series")}


def check_fill_series(root: Path, sim: dict) -> None:
    want = load_lock(root).get("fill_series")
    got = (sim or {}).get("fill_series")
    if want and got != want:
        raise RuleLockError(f"fill_series={got!r} != locked {want!r}")


def dirty_paths(root: Path) -> list[str] | None:
    """Uncommitted changes outside run-output paths. None if not a git repo."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=str(root), capture_output=True, text=True, timeout=30, check=True,
        )
    except Exception:  # noqa: BLE001
        return None
    out = []
    for line in r.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if "__pycache__" in path or path.endswith(".pyc"):
            continue
        if path.startswith(DIRTY_IGNORE_PREFIXES):
            continue
        out.append(path)
    return out


def check_clean(root: Path) -> None:
    d = dirty_paths(root)
    if d is None:
        raise RuleLockError("cannot read git status; refuse to write formal result")
    if d:
        raise RuleLockError(f"working tree dirty ({len(d)}): {', '.join(d[:8])}")
