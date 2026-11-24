# -*- coding: utf-8 -*-
"""R5a: per-code difference between the legacy (pre-R5a) and the shared-core daily signal path."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
L = json.loads((ROOT / "archive/R5/l1_report_dryrun_legacy.json").read_text(encoding="utf-8"))
N = json.loads((ROOT / "archive/R5/l1_report_dryrun.json").read_text(encoding="utf-8"))
lo = {s["code"]: s for s in L["signals"]}
ne = {s["code"]: s for s in N["signals"]}
rows, changed = [], 0
for code in ne:
    a, b = lo.get(code, {}), ne[code]
    row = {
        "code": code,
        "bar_date": [a.get("bar_date"), b.get("bar_date")],
        "direction": [a.get("direction"), b.get("direction")],
        "r20": [a.get("r20"), b.get("r20")],
        "r60": [a.get("r60"), b.get("r60")],
        "atr": [a.get("atr"), b.get("atr")],
        "lots_raw": [a.get("lots_raw"), b.get("lots_raw")],
        "selected": [a.get("selected"), b.get("selected")],
        "block": [a.get("block"), b.get("block")],
        "adj_fallback": b.get("adj_fallback"),
    }
    d = {}
    for k in ("direction", "lots_raw", "selected", "block"):
        if row[k][0] != row[k][1]:
            d[k] = row[k]
    for k, tol in (("r20", 0.0005), ("r60", 0.0005), ("atr", 0.005)):
        x, y = row[k]
        if (x is None) != (y is None) or (x is not None and abs(x - y) > tol):
            d[k] = row[k]
    row["diff"] = d
    changed += bool(d)
    rows.append(row)
out = {
    "legacy": "l1_report_dryrun_legacy.json (n=120 raw bars, unlagged seats/carry, no vol_bypass)",
    "core": "l1_report_dryrun.json (signal_core, roll-free, lagged books)",
    "n_codes": len(rows),
    "n_changed": changed,
    "direction_changes": [r["code"] for r in rows if "direction" in r["diff"]],
    "lots_changes": [r["code"] for r in rows if "lots_raw" in r["diff"]],
    "selected_changes": [r["code"] for r in rows if "selected" in r["diff"]],
    "block_changes": [r["code"] for r in rows if "block" in r["diff"]],
    "selected_legacy": [s["code"] for s in L["signals"] if s.get("selected")],
    "selected_core": [s["code"] for s in N["signals"] if s.get("selected")],
    "adj_fallback_codes": N.get("adj_fallback_codes"),
    "contract_cache": N.get("contract_cache"),
    "rows": rows,
}
(ROOT / "archive/R5/dryrun_old_vs_new.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print({k: v for k, v in out.items() if k != "rows"})
for r in rows:
    if r["diff"]:
        print(r["code"], {k: v for k, v in r["diff"].items()})
