# -*- coding: utf-8 -*-
"""Compare two historical_backtest result JSONs key by key (all top-level keys), report every difference."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(p):
    p = Path(p)
    if not p.is_absolute():
        p = ROOT / p
    return json.loads(p.read_text(encoding="utf-8"))


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


def main(argv=None) -> int:
    a, b = load(argv[0]), load(argv[1])
    keys = sorted(set(a) | set(b))
    diffs = [k for k in keys if canon(a.get(k)) != canon(b.get(k))]
    same = [k for k in keys if k not in diffs]
    print(f"top-level keys: {len(keys)}  identical: {len(same)}  different: {len(diffs)}")
    print("identical keys include:", [k for k in ("ret_pct", "gross_ret_pct", "max_dd_pct", "cost_yuan", "closed_trades",
                                                  "closed_pnls", "equity_curve", "exits", "equity_end", "start", "end",
                                                  "cost_scenario_contrast", "caps_entry_gross_max", "contract_pack",
                                                  "day_pnls", "trade_exits") if k in same])
    for k in diffs:
        va, vb = a.get(k), b.get(k)
        sa, sb = canon(va), canon(vb)
        print(f"DIFF {k}: {sa[:160]!r} vs {sb[:160]!r}")
        if isinstance(va, dict) and isinstance(vb, dict):
            sub = [s for s in sorted(set(va) | set(vb)) if canon(va.get(s)) != canon(vb.get(s))]
            print(f"     differing sub-keys: {sub}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
