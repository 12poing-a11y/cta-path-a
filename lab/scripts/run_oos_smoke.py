# -*- coding: utf-8 -*-
"""OOS smoke: equal-weight mom20/60 score vs Path-A window; no retuning.

Reads lab factor panel, freezes IS, reports OOS hit-rate style stats only
(direction of mom_20 vs next-day return sign). Not a full backtest KPI claim.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]


def _load_split() -> dict:
    return json.loads((LAB / "config" / "oos_split.json").read_text(encoding="utf-8"))


def _sign(x: float | None) -> int:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def main() -> int:
    split = _load_split()
    is_end = str(split["in_sample"]["end"])
    oos_start = str(split["out_of_sample"]["start"])
    panel_path = LAB / "data" / "factors" / "panel_daily.jsonl"
    if not panel_path.is_file():
        print("[oos] missing panel; run build_factor_panel.py first")
        return 1
    by_code: dict[str, list[dict]] = defaultdict(list)
    with panel_path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            by_code[row["code"]].append(row)
    hits = miss = flat = 0
    n_oos = 0
    bar_dir = LAB / "data" / "bars" / "continuous"
    for path in bar_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars = payload.get("bars") or []
        fmap = {r["date"]: r for r in by_code.get(payload["code"], [])}
        for i in range(len(bars) - 1):
            day = bars[i]["date"]
            if day < oos_start:
                continue
            fac = fmap.get(day) or {}
            mom = fac.get("mom_20")
            c0, c1 = float(bars[i]["close"]), float(bars[i + 1]["close"])
            if not c0 or mom is None:
                flat += 1
                n_oos += 1
                continue
            n_oos += 1
            pred = _sign(float(mom))
            realized = _sign(c1 / c0 - 1.0)
            if pred == 0 or realized == 0:
                flat += 1
            elif pred == realized:
                hits += 1
            else:
                miss += 1
    decided = hits + miss
    hit_rate = (hits / decided * 100.0) if decided else None
    report = {
        "ok": True,
        "plan": "A",
        "is_end": is_end,
        "oos_start": oos_start,
        "oos_rows": n_oos,
        "hits": hits,
        "miss": miss,
        "flat": flat,
        "hit_rate_pct": None if hit_rate is None else round(hit_rate, 2),
        "metric": "sign(mom_20) vs next-day close return (smoke only)",
        "disclaimer": "冒烟指标，非策略夏普/净收益承诺；正式 OOS 净值另开 runs。",
    }
    out = LAB / "research" / "oos" / "smoke_mom20.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
