# -*- coding: utf-8 -*-
"""Read-only probe #2: contract-bar cache range (.cache/contracts), member-seat cache range (.cache/member),
carry curves source.  Numbers only -> archive/R8/long_coverage_probe2.json"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
out = {}

# ---- contracts: AG2510.json -> code + delivery yymm
byc = defaultdict(list)
for p in (ROOT / ".cache" / "contracts").glob("*.json"):
    m = re.match(r"^([A-Z]+)(\d{4})$", p.stem)
    if m:
        byc[m.group(1)].append(m.group(2))
rng = {}
for c, v in sorted(byc.items()):
    v = sorted(v)
    rng[c] = {"n_contracts": len(v), "first_delivery": v[0], "last_delivery": v[-1]}
out["contracts_by_code"] = rng
# first bar date across contracts (sample a few per code: earliest delivery file)
first_dates = {}
for c, v in sorted(byc.items()):
    p = ROOT / ".cache" / "contracts" / f"{c}{sorted(v)[0]}.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    bars = raw if isinstance(raw, list) else raw.get("bars") or raw.get("hist") or []
    first_dates[c] = {"file": p.name, "first_bar": (str(bars[0].get("date"))[:10] if bars else None), "n": len(bars)}
out["earliest_contract_first_bar"] = first_dates

# ---- member seats
mem = defaultdict(list)
for p in (ROOT / ".cache" / "member").glob("*.txt"):
    m = re.match(r"^([a-z]+)-(\d{8})\.txt$", p.name)
    if m:
        mem[m.group(1)].append(m.group(2))
out["member_txt_by_exchange"] = {k: {"n": len(v), "first": min(v), "last": max(v)} for k, v in sorted(mem.items())}
d = ROOT / ".cache" / "member" / "_dce_dl"
out["member_dce_dl_files"] = len(list(d.glob("*"))) if d.exists() else 0
print(json.dumps(out, ensure_ascii=False, indent=1))
(ROOT / "archive" / "R8" / "long_coverage_probe2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
