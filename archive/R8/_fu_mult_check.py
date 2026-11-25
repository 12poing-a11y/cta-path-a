import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import RAW, load_all  # noqa: E402

by = load_all()
fu = [c for c in by if re.match(r"FU\d{4}$", c)]
mani = json.loads((RAW / "MANIFEST_shfe.json").read_text(encoding="utf-8"))
rows = []
for d, rec in sorted(mani.items()):
    if rec.get("status") != "ok" or not ("2016-01-01" <= d <= "2019-06-30"):
        continue
    j = json.loads(gzip.decompress((RAW / "shfe" / f"{d.replace('-', '')}.gz").read_bytes()))
    for r in j.get("o_curproduct") or []:
        if str(r.get("PRODUCTID", "")).strip() == "fu_f" and r.get("TURNOVER") and r.get("VOLUME"):
            denom = sum((by[c][d]["volume"] or 0) * (by[c][d]["settle"] or 0) for c in fu if d in by[c])
            if denom > 0:
                rows.append((d, float(r["VOLUME"]), float(r["TURNOVER"]) * 1e8 / denom))
print("n days with FU product turnover:", len(rows))
by_period = defaultdict(list)
for d, v, ratio in rows:
    k = "2016-01..2018-06" if d < "2018-06-27" else "2018-06-27..2018-07-13" if d < "2018-07-16" else "2018-07-16..2019-06"
    by_period[k].append((d, v, ratio))
for k, v in by_period.items():
    rs = sorted(r for _, _, r in v)
    print(k, "days", len(v), "implied multiplier min/median/max", round(rs[0], 2), round(rs[len(rs) // 2], 2), round(rs[-1], 2), "first", v[0][0], "last", v[-1][0])
# switch around the announced date
for d, v, ratio in rows:
    if "2018-06-20" <= d <= "2018-07-24":
        print(d, "vol", v, "implied mult", round(ratio, 2))
