# -*- coding: utf-8 -*-
"""R7a-D4: freeze the minute bars read by tests/test_freeze_fix_gates.py's two 11-13 replays.

The KPI lock (R3: 4.189 / 4.294 / 42) was measured on the local minute cache, which holds bars the
committed ``.cache/akshare/minute`` files lack; a clean checkout then gives 4.619 / 4.617 / 42.
This records every ``load_minute_bars_on_trading_day`` call of the legacy and the fixed replay
(local cache) into tests/fixtures/freeze_fix_1113_minute.json; the test serves minutes from it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "lab" / "shadow", ROOT / "lab" / "shadow" / "fix3"):
    sys.path.insert(0, str(p))

OUT = ROOT / "tests" / "fixtures" / "freeze_fix_1113_minute.json"


def main() -> int:
    import minute_data

    import replay as R

    real = minute_data.load_minute_bars_on_trading_day
    rec: dict[str, list] = {}

    def recorder(root, code, day, period="15", *, sessions):
        bars = real(root, code, day, period, sessions=sessions)
        rec[f"{code}|{day}|{period}"] = bars
        return bars

    minute_data.load_minute_bars_on_trading_day = recorder
    try:
        p, pack = R.make_pack()
        legacy = R.run(p, pack, freeze_fix=False, min_seat_days=0)
        p, pack = R.make_pack()
        fixed = R.run(p, pack)
    finally:
        minute_data.load_minute_bars_on_trading_day = real
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": "minute bars read by the 11-13 legacy + fixed replays (local cache, captured R7a-D4)",
        "legacy_kpi": [legacy["ret_pct"], legacy["max_dd_pct"], legacy["closed_trades"]],
        "fixed_kpi": [fixed["ret_pct"], fixed["max_dd_pct"], fixed["closed_trades"]],
        "calls": rec,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(payload["legacy_kpi"], payload["fixed_kpi"], len(rec), "calls ->", OUT, OUT.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
