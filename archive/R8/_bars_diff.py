# -*- coding: utf-8 -*-
"""Show exactly which fields differ between the bars of two frozen input snapshots (PREREG sec. 7: only `oi` may differ)."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def bars(path):
    s = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in ("series", "bars", "pack"):
        if k in s:
            return s[k], s
    raise SystemExit(f"unknown snapshot layout: {list(s)[:10]}")


def main(a_path, b_path):
    a, _ = bars(a_path)
    b, sb = bars(b_path)
    fields, ncode = Counter(), Counter()
    only = {"len": 0}
    for code in sorted(set(a) | set(b)):
        ha = (a.get(code) or {}).get("hist") if isinstance(a.get(code), dict) else a.get(code)
        hb_ = (b.get(code) or {}).get("hist") if isinstance(b.get(code), dict) else b.get(code)
        if ha is None or hb_ is None or len(ha) != len(hb_):
            only["len"] += 1
            print("length/presence mismatch", code, None if ha is None else len(ha), None if hb_ is None else len(hb_))
            continue
        for x, y in zip(ha, hb_):
            for f in sorted(set(x) | set(y)):
                if x.get(f) != y.get(f):
                    fields[f] += 1
                    ncode[(code, f)] += 1
    print("differing fields (count of bar-days):", dict(fields))
    print("codes affected:", sorted({c for (c, f) in ncode}))
    print("length mismatches:", only["len"])
    return 0 if set(fields) <= {"oi"} and only["len"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
