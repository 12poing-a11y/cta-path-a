import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for c in ("V", "EG", "RB", "FG"):
    bs = [b for b in json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8")) if "2016-01-01" <= str(b["date"])[:10] <= "2025-12-31"]
    miss = [str(b["date"])[:10] for b in bs if b.get("settle") in (None, 0)]
    after = [d for d in miss if d > "2018-03-09"]
    print(c, "total", len(miss), "after 2018-03-09:", len(after), (min(after), max(after)) if after else None)
    print("  by month (after 2018-03-09):", dict(Counter(d[:7] for d in after)))
    print("  non-DCE-style isolated days:", [d for d in miss if not ("2017-11-01" <= d <= "2018-03-09") and not ("2019-12-01" <= d <= "2020-07-31")])
