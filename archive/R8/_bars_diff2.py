# -*- coding: utf-8 -*-
"""List non-oi bar differences between two snapshots (code, date, field, a, b) and where they sit vs the window."""
import json
import sys
from pathlib import Path

a_path, b_path = sys.argv[1:3]
A = json.loads(Path(a_path).read_text(encoding="utf-8"))
B = json.loads(Path(b_path).read_text(encoding="utf-8"))
key = next(k for k in ("series", "bars", "pack") if k in A)
sa, sb = A[key], B[key]
rows = []
for code in sorted(sa):
    ha = sa[code]["hist"] if isinstance(sa[code], dict) else sa[code]
    hb_ = sb[code]["hist"] if isinstance(sb[code], dict) else sb[code]
    n = len(ha)
    for j, (x, y) in enumerate(zip(ha, hb_)):
        for f in sorted(set(x) | set(y)):
            if f != "oi" and x.get(f) != y.get(f):
                rows.append((code, str(x.get("date"))[:10], j, n, f, x.get(f), y.get(f)))
for r in rows:
    print(r)
print("n non-oi diffs:", len(rows))
