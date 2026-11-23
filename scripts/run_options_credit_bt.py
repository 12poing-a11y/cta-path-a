# -*- coding: utf-8 -*-
"""Run credit-vertical research BT + optional paper ingest + risk report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.options.backtest.engine import run_credit_vertical_bt  # noqa: E402
from research.options.paper.ledger import ingest_bt_closed  # noqa: E402
from research.options.risk_report import build_risk_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--codes", default="CF,SR,MA")
    ap.add_argument("--kind", default="put_credit", choices=["put_credit", "call_credit"])
    ap.add_argument("--width", type=float, default=200.0)
    ap.add_argument("--slip-ticks", type=float, default=2.0)
    ap.add_argument("--exit", default="next_snap", choices=["next_snap", "expiry"])
    ap.add_argument(
        "--settle-only",
        action="store_true",
        help="Force settle_discount pricing (no Bid/Ask preference)",
    )
    ap.add_argument("--ingest-paper", action="store_true")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    codes = [c.strip().upper() for c in str(args.codes).split(",") if c.strip()]
    bt = run_credit_vertical_bt(
        args.root,
        codes=codes,
        kind=args.kind,
        width_points=args.width,
        slip_ticks=args.slip_ticks,
        exit_mode=args.exit,
        prefer_bid_ask=not args.settle_only,
        write=True,
    )
    m = bt.get("metrics") or {}
    print(
        f"[options-bt] state={bt.get('strategy_state')} "
        f"n_closed={m.get('n_closed')} win={m.get('win_rate')} "
        f"avg_pnl_cny={m.get('avg_pnl_cny')} path={bt.get('path')}"
    )
    if args.ingest_paper:
        ing = ingest_bt_closed(args.root, bt)
        print(f"[options-paper] new={ing['n_new']} dup={ing['n_dup']} → {ing['path']}")
    risk = build_risk_report(args.root, write=True)
    print(f"[options-risk] → {risk.get('path')}")
    # compact stdout for CI logs
    print(json.dumps({"metrics": m, "strategy_state": bt.get("strategy_state")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
