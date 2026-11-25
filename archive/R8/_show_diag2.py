import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import load_all  # noqa: E402

d = json.loads((ROOT / "archive/R8/feasibility_diag.json").read_text(encoding="utf-8"))
for k, v in d["vol_oi_mismatch"].items():
    print(k, {kk: vv for kk, vv in v.items()})
by = load_all()
rows = []
bycont = Counter()
for p in sorted((ROOT / ".cache" / "contracts").glob("*.json")):
    cid = p.stem
    if cid not in by or not re.match(r"(EB|EG|I|JD|JM|L|M|P|PP|V)\d{4}$", cid):
        continue
    for lb in json.loads(p.read_text(encoding="utf-8")).get("bars", []):
        dd = str(lb["date"])[:10]
        ob = by[cid].get(dd)
        if dd < "2024-09-01" or ob is None:
            continue
        if any(abs(float(lb[k]) - float(ob[k])) > 1e-9 for k in ("open", "high", "low", "close")):
            rows.append((cid, dd, ob, lb))
            bycont[cid] += 1
print("DCE price mismatch rows:", len(rows), "by contract (top):", bycont.most_common(8))
for cid, dd, ob, lb in rows[:4]:
    print(cid, dd, "official", {k: ob[k] for k in ("open", "high", "low", "close", "settle", "volume", "oi")}, "local", {k: lb[k] for k in ("open", "high", "low", "close", "settle", "volume", "open_interest")})
# how many of those are on days where official OHLC has zeros
z = sum(1 for _, _, ob, _ in rows if (ob["open"] or 0) == 0)
print("official open==0 in mismatching rows:", z, "official volume stats:", sorted({ob["volume"] for _, _, ob, _ in rows})[:10])
# last trade date? contract last official date vs local last date
for cid in list(bycont)[:6]:
    last_off = max(by[cid])
    loc = json.loads((ROOT / ".cache" / "contracts" / f"{cid}.json").read_text(encoding="utf-8"))["bars"]
    print(cid, "official last", last_off, "local last", str(loc[-1]["date"])[:10], "mismatch days", sorted({dd for c, dd, _, _ in rows if c == cid})[:6])
