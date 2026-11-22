# -*- coding: utf-8 -*-
"""Run V1.3 arb shadow monitor on agri + black supply pairs."""
from __future__ import annotations

import json
from pathlib import Path

from research.arbitrage_backtest import load_pair_inputs_from_root
from research.arbitrage_shadow_monitor import (
    append_decision_ledger,
    monitor_pair,
    summarize_universe,
)

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
    reports = []
    all_decisions = []
    for m in meta:
        if not m.get("ok"):
            continue
        pid = m["pair"]
        sa, sb = specs[pid]
        rep = monitor_pair(
            bars[pid],
            pair_id=pid,
            spec_a=sa,
            spec_b=sb,
            start=START,
            end=END,
            require_cointegration=True,
        )
        reports.append(rep)
        all_decisions.extend(rep.get("decisions") or [])

    summary = summarize_universe(reports)
    summary["window"] = {"start": START, "end": END}
    summary["align_meta"] = meta
    summary["focus"] = "农产品+黑色供需"
    summary["excluded"] = {
        "贵金属": ["AU/AG"],
        "能化": ["MA/TA", "MA/EG", "FG/SA"],
        "有色": ["CU/AL"],
    }

    out_dir = ROOT / "lab" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "arb_v13_shadow_latest.json"
    # Strip decisions from latest for readability; full ledger in jsonl
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger = out_dir / "arb_v13_shadow_ledger.jsonl"
    # Fresh run snapshot file for this window (append-only across runs still preserved
    # by also writing dated copy). Overwrite dated? Use append to ledger always.
    n = append_decision_ledger(ledger, all_decisions)
    dated = out_dir / f"arb_v13_shadow_decisions_{START.replace('-', '')}_{END.replace('-', '')}.json"
    dated.write_text(
        json.dumps(
            {
                "window": {"start": START, "end": END},
                "n_decisions": len(all_decisions),
                "decisions": all_decisions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "wrote_latest": str(latest),
                "wrote_ledger_append_n": n,
                "wrote_decisions": str(dated),
                "dual_path_totals": summary["dual_path_totals"],
                "block_reason_counts": summary["block_reason_counts"],
                "data_quality_counts": summary["data_quality_counts"],
                "pairs": [
                    {
                        "pair": p["pair"],
                        "n_signal": p["n_signal"],
                        "n_pass": p["n_pass"],
                        "n_block": p["n_block"],
                        "dual_path": p["dual_path"],
                    }
                    for p in summary["pairs"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
