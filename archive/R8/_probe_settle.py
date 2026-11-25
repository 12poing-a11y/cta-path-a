import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
for u in uni["symbols"]:
    c = u["code"]
    bs = [b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8")) if "2016-01-01" <= str(b["date"])[:10] <= "2025-12-31"]
    miss = [str(b["date"])[:10] for b in bs if b.get("settle") in (None, 0)]
    if not miss:
        continue
    # contiguous runs by index
    runs, start, prev = [], None, None
    idx = {str(b["date"])[:10]: i for i, b in enumerate(bs)}
    for d in miss:
        i = idx[d]
        if start is None:
            start = prev = (d, i)
        elif i == prev[1] + 1:
            prev = (d, i)
        else:
            runs.append((start[0], prev[0], prev[1] - start[1] + 1))
            start = prev = (d, i)
    runs.append((start[0], prev[0], prev[1] - start[1] + 1))
    print(c, len(miss), runs[:6])
# FU zero-volume stretch
bs = [b for b in json.loads((ROOT / ".cache" / "history" / "FU0.json").read_text(encoding="utf-8")) if "2016-01-01" <= str(b["date"])[:10] <= "2025-12-31"]
z = [str(b["date"])[:10] for b in bs if not b.get("volume")]
print("FU zero-volume bars:", len(z), z[0], z[-1], "by year:", {y: sum(1 for d in z if d[:4] == y) for y in sorted({d[:4] for d in z})})
