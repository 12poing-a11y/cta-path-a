# -*- coding: utf-8 -*-
"""fix3-opt ⑤: real run of historical_backtest.main() — dirty tree => exit 2, formal file untouched.

Runs in a throwaway `git worktree` of HEAD; the network fetch is replaced by the offline
snapshot replay (same engine), everything after simulate (validation, quality gate,
input snapshot, rule lock, write) is the real main() path.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "archive/snapshots/bt_input_20261113_d246813d911a.json"

DRIVER = r'''
import sys, types
stub = types.ModuleType("ifind_call")
stub.active_slot = lambda *a, **k: None
stub.call = lambda *a, **k: {}
stub.usage_report = lambda: {"count": 0, "calls": []}
sys.modules["ifind_call"] = stub
sys.path.insert(0, "."); sys.path.insert(0, "lab/shadow")
import historical_backtest as hb
orig = hb._simulate_cfg
import replay as R
def fake(p, mode, **kw):
    pp, pack = R.make_pack()
    return orig(pp, pp["entry_filter"], pack=pack)
hb._simulate_cfg = fake
sys.argv = ["historical_backtest.py", "--no-cost-stress"]
sys.exit(hb.main())
'''


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.skipif(not SNAP.exists(), reason="snapshot missing")
def test_formal_write_dirty_tree_exit2_and_clean_writes(tmp_path):
    wt = tmp_path / "wt"
    r = subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"git worktree unavailable: {r.stderr[:200]}")
    try:
        formal = wt / "historical_backtest_latest.json"
        before = _sha(formal)
        (wt / "dirty_probe.py").write_text("x = 1\n", encoding="utf-8")  # uncommitted code change
        d = subprocess.run([sys.executable, "-c", DRIVER], cwd=wt, capture_output=True, text=True, timeout=600)
        assert d.returncode == 2, (d.returncode, d.stderr[-800:])
        assert "RULE LOCK FAILED" in d.stderr and "dirty" in d.stderr
        assert _sha(formal) == before
        # clean tree: same run passes the lock and writes (only inside the throwaway worktree)
        (wt / "dirty_probe.py").unlink()
        c = subprocess.run([sys.executable, "-c", DRIVER], cwd=wt, capture_output=True, text=True, timeout=600)
        assert c.returncode == 0, (c.returncode, c.stderr[-800:], c.stdout[-800:])
        assert _sha(formal) != before
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, capture_output=True)
