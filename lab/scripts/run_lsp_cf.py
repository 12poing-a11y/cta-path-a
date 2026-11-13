# -*- coding: utf-8 -*-
"""CF LSP sweep study on cached 15m/60m bars (Research only).

Usage (repo root):
  python lab/scripts/run_lsp_cf.py
  python lab/scripts/run_lsp_cf.py --period 60
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.lsp.pipeline import load_bars_from_minute_cache, run_lsp, save_lsp_run  # noqa: E402
from lab.lsp.resonance import resonate_with_higher_tf, resonance_stats  # noqa: E402
from research.governance import register_experiment  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="CF")
    ap.add_argument("--contract", default="CF2701")
    ap.add_argument("--period", default="15", choices=("15", "60", "both"))
    args = ap.parse_args(argv)

    periods = ("15", "60") if args.period == "both" else (args.period,)
    payloads = {}
    for per in periods:
        tf = f"{per}m"
        bars, _sym = load_bars_from_minute_cache(ROOT, args.symbol, per, contract=args.contract)
        if len(bars) < 80:
            print(f"[lsp] insufficient bars n={len(bars)} for {args.symbol}/{per}")
            continue
        print(f"[lsp] bars={len(bars)} {bars[0].get('datetime')} → {bars[-1].get('datetime')} ({tf})")
        payload = run_lsp(bars, symbol=args.symbol, contract=args.contract, timeframe=tf)
        payloads[tf] = payload
        paths = save_lsp_run(payload, root=ROOT)
        stats = payload.get("stats") or {}
        print(
            f"[lsp] {tf} events={payload['n_events']} probs={stats.get('outcome_probs')} "
            f"avg_mfe={stats.get('avg_mfe_atr')} avg_mae={stats.get('avg_mae_atr')}"
        )
        print(f"[lsp] wrote {paths['latest']}")
        register_experiment(
            name=f"lsp_{args.symbol}_{tf}",
            kind="lsp_sweep",
            params={"symbol": args.symbol, "contract": args.contract, "period": per},
            metrics={
                "n_events": payload["n_events"],
                "outcome_probs": stats.get("outcome_probs"),
                "avg_mfe_atr": stats.get("avg_mfe_atr"),
                "avg_mae_atr": stats.get("avg_mae_atr"),
            },
            validation={"stats": stats},
            artifact=paths["latest"],
            status="Research",
            notes="LSP CF sweep study; does not change Path-A entries.",
            root=ROOT,
        )

    if "15m" in payloads and "60m" in payloads:
        res_events = resonate_with_higher_tf(payloads["15m"]["events"], payloads["60m"]["events"])
        rstats = resonance_stats(res_events)
        payloads["15m"]["events"] = res_events
        payloads["15m"]["stats"]["resonance"] = rstats
        paths = save_lsp_run(payloads["15m"], root=ROOT)
        print(f"[lsp] resonance {rstats} → {paths['latest']}")
    return 0 if payloads else 1


if __name__ == "__main__":
    raise SystemExit(main())
