# -*- coding: utf-8 -*-
"""R5a step 1 check: the signal_core refactor of simulate must be bit-identical to 1cfe6fc.

Loads the committed (HEAD) historical_backtest.py as a separate module and compares full
simulate results (default + adjusted_signals=False + caps_include_book=False) with the working tree.
"""
import copy
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab/shadow"))
import historical_backtest as new  # noqa: E402

ref = sys.argv[1] if len(sys.argv) > 1 else "1cfe6fc"
src = subprocess.run(["git", "show", f"{ref}:historical_backtest.py"], capture_output=True, cwd=ROOT).stdout.decode("utf-8")
old = types.ModuleType("hb_old")
old.__file__ = str(ROOT / "historical_backtest.py")
exec(compile(src, "hb_old", "exec"), old.__dict__)

snap = json.loads((ROOT / "archive/snapshots/bt_input_20261123_da9c8de64ab4.json").read_text(encoding="utf-8"))
bt = json.loads((ROOT / "archive/R0/fresh_bt.json").read_text(encoding="utf-8"))


def patch(m):
    m.prepare_pack_for_execution = lambda pack, root=None: bt.get("contract_pack") or {}
    m.load_member_seats = lambda dates, codes: snap["member"]
    m.load_member_changes = lambda dates, codes: snap["member"]
    m.lag_member = lambda mm, dates, lag: mm
    m.load_curves = lambda codes: {
        c: ({"carry": v} if not (isinstance(v, dict) and "carry" in v) else v)
        for c, v in (snap.get("carry") or {}).items()
    }
    m.lag_curves_carry = lambda curves, dates, lag: curves


def pack(m):
    p = m._load_cfg()
    series = {}
    for u in p["cfg"]["symbols"]:
        c = u["code"]
        if c in snap["bars"]:
            series[c] = {"meta": dict(u), "hist": copy.deepcopy(snap["bars"][c])}
    return p, (series, dict(snap.get("errors") or {}), dict(snap.get("sources") or {}))


def run(m, **kw):
    patch(m)
    p, pk = pack(m)
    return m._simulate_cfg(p, p["entry_filter"], pack=pk, **kw)


def strip(o):
    o = dict(o)
    for k in ("git_sha", "config_version"):
        o.pop(k, None)
    return o


ok = True
for name, kw in (
    ("default", {}),
    ("adjusted_signals=False", {"adjusted_signals": False}),
    ("caps_include_book=False", {"caps_include_book": False}),
    ("freeze_fix=False", {"freeze_fix": False, "min_seat_days": 0}),
):
    a, b = strip(run(old, **kw)), strip(run(new, **kw))
    same = json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    ok &= same
    print(name, "IDENTICAL" if same else "DIFFERENT", a.get("ret_pct"), b.get("ret_pct"), a.get("max_dd_pct"), b.get("max_dd_pct"), a.get("closed_trades"), b.get("closed_trades"))
    if not same:
        for k in a:
            if a[k] != b.get(k):
                print("   diff key", k)
print("ALL_IDENTICAL" if ok else "MISMATCH")
