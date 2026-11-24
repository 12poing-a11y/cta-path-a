# -*- coding: utf-8 -*-
"""R7a-D1: day-by-day main_map comparison, pre-D (git ref) vs working tree, on one snapshot.

usage: python archive/R7/_main_map_compare.py [--ref a238a3d] [--snap PATH] [--root DIR] [--out JSON]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _old_module(ref: str):
    src = subprocess.check_output(["git", "show", f"{ref}:research/data_quality/main_map.py"], cwd=ROOT)
    tmp = Path(tempfile.mkdtemp()) / "main_map_old.py"
    tmp.write_bytes(src)
    spec = importlib.util.spec_from_file_location("main_map_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["main_map_old"] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="a238a3d")
    ap.add_argument("--snap", default="archive/snapshots/bt_input_20261123_da9c8de64ab4.json")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    from research.data_quality import main_map as new

    old = _old_module(a.ref)
    snap = json.loads((ROOT / a.snap).read_text(encoding="utf-8"))
    uni = {u["code"]: u for u in json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))["symbols"]}
    series = {c: {"meta": dict(uni[c]), "hist": h} for c, h in snap["bars"].items() if c in uni}
    m0 = old.build_main_map(series, root=Path(a.root))
    m1 = new.build_main_map(series, root=Path(a.root))
    diffs = []
    for c in series:
        for d in sorted(set(m0.maps[c]) | set(m1.maps[c])):
            if m0.maps[c].get(d) != m1.maps[c].get(d):
                diffs.append({"code": c, "date": d, "old": m0.maps[c].get(d), "new": m1.maps[c].get(d)})
    rep = {
        "ref": a.ref,
        "snapshot": a.snap,
        "days": sum(len(v) for v in m1.maps.values()),
        "diff_days": len(diffs),
        "old_none_days": sum(s["none_days"] for s in m0.stats.values()),
        "new_none_days": sum(s["none_days"] for s in m1.stats.values()),
        "diffs": diffs,
    }
    print({k: v for k, v in rep.items() if k != "diffs"})
    for x in diffs[:40]:
        print(x)
    if a.out:
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
