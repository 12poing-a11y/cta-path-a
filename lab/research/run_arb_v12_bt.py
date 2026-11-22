# -*- coding: utf-8 -*-
"""Run V1.2 research BT on agri + black supply pairs (shadow only)."""
from __future__ import annotations

import json
from pathlib import Path

from research.arbitrage_backtest import backtest_universe, load_pair_inputs_from_root

ROOT = Path(__file__).resolve().parents[2]
FOCUS = (
    ("M", "P", "农产品"),
    ("RB", "I", "黑色"),
    ("RB", "JM", "黑色"),
    ("I", "JM", "黑色"),
)
START, END = "2025-11-20", "2026-11-20"


def main() -> None:
    bars, specs, meta = load_pair_inputs_from_root(ROOT, FOCUS)
    report = backtest_universe(
        bars,
        specs,
        start=START,
        end=END,
        capital=1_000_000.0,
        total_risk_budget=80_000.0,
        focus_pairs=[m["pair"] for m in meta if m.get("ok")],
        require_cointegration=True,
    )
    report["align_meta"] = meta
    report["excluded"] = {
        "贵金属": ["AU/AG"],
        "能化": ["MA/TA", "MA/EG", "FG/SA"],
        "有色": ["CU/AL"],
    }
    out = ROOT / "lab" / "research" / "arb_v12_bt_agri_black_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "wrote": str(out),
        "align_meta": meta,
        "controls": {
            m: report["controls"][m]["portfolio"] for m in report["controls"]
        },
    }
    # per-pair net for best control
    for m, block in report["controls"].items():
        summary.setdefault("pair_nets", {})[m] = {
            pid: {
                "net_pnl_yuan": r.get("net_pnl_yuan"),
                "trades": r.get("trades"),
                "blocked_entries": r.get("blocked_entries"),
            }
            for pid, r in block["pairs"].items()
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
