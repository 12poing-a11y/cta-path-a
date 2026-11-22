# -*- coding: utf-8 -*-
"""Compare fade (mean-reversion) vs follow (momentum/reverse) on agri+black."""
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


def slim(report: dict) -> dict:
    return {
        "signal_mode": report.get("signal_mode"),
        "controls": {
            m: block["portfolio"]
            for m, block in (report.get("controls") or {}).items()
        },
        "pair_nets": {
            m: {
                pid: {
                    "net_pnl_yuan": r.get("net_pnl_yuan"),
                    "trades": r.get("trades"),
                    "blocked_entries": r.get("blocked_entries"),
                }
                for pid, r in block["pairs"].items()
            }
            for m, block in (report.get("controls") or {}).items()
        },
    }


def main() -> None:
    bars, specs, meta = load_pair_inputs_from_root(ROOT, FOCUS)
    ids = [m["pair"] for m in meta if m.get("ok")]
    out = {
        "mode": "arb_fade_vs_follow_shadow",
        "disclaimer": (
            "同一套 V1.2 口径；follow=价差动量（反向于均值回归）；"
            "非正式晋级/不下单。"
        ),
        "window": {"start": START, "end": END},
        "align_meta": meta,
        "fade": None,
        "follow": None,
        "delta_follow_minus_fade": {},
    }
    for mode in ("fade", "follow"):
        rep = backtest_universe(
            bars,
            specs,
            start=START,
            end=END,
            capital=1_000_000.0,
            total_risk_budget=80_000.0,
            focus_pairs=ids,
            require_cointegration=True,
            signal_mode=mode,
        )
        out[mode] = slim(rep)
    for ctrl in (out["fade"]["controls"] or {}):
        f = out["fade"]["controls"][ctrl]
        g = out["follow"]["controls"][ctrl]
        out["delta_follow_minus_fade"][ctrl] = {
            "ret_pct_pts": round(float(g["ret_pct"]) - float(f["ret_pct"]), 3),
            "net_pnl_yuan": round(float(g["net_pnl_yuan"]) - float(f["net_pnl_yuan"]), 2),
            "dd_pct_pts": round(float(g["max_dd_pct"]) - float(f["max_dd_pct"]), 3),
        }
    path = ROOT / "lab" / "research" / "arb_fade_vs_follow_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(path),
                "fade": out["fade"]["controls"],
                "follow": out["follow"]["controls"],
                "delta_follow_minus_fade": out["delta_follow_minus_fade"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
