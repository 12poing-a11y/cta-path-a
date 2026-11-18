# -*- coding: utf-8 -*-
"""LSP sweep study on cached 15m/60m bars (Research only).

Usage (repo root):
  python lab/scripts/run_lsp_cf.py
  python lab/scripts/run_lsp_cf.py --period both
  python lab/scripts/run_lsp_cf.py --symbol P --contract P2701 --period both
  python lab/scripts/run_lsp_cf.py --symbols CF,P,RB,MA,TA --period both
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.lsp.pipeline import (  # noqa: E402
    DEFAULT_LSP_SYMBOLS,
    load_bars_from_minute_cache,
    refresh_lsp_universe,
    resolve_lsp_contract,
    run_lsp,
    save_lsp_run,
)
from lab.lsp.resonance import resonate_with_higher_tf, resonance_stats  # noqa: E402
from research.governance import register_experiment  # noqa: E402


def _run_one(symbol: str, contract: str | None, period: str) -> dict:
    periods = ("15", "60") if period == "both" else (period,)
    payloads: dict = {}
    for per in periods:
        tf = f"{per}m"
        bars, _sym = load_bars_from_minute_cache(ROOT, symbol, per, contract=contract)
        if len(bars) < 80:
            print(f"[lsp] insufficient bars n={len(bars)} for {symbol}/{per}")
            continue
        print(
            f"[lsp] {symbol} bars={len(bars)} "
            f"{bars[0].get('datetime')} → {bars[-1].get('datetime')} ({tf})"
        )
        payload = run_lsp(bars, symbol=symbol, contract=contract, timeframe=tf)
        payloads[tf] = payload
        paths = save_lsp_run(payload, root=ROOT)
        stats = payload.get("stats") or {}
        print(
            f"[lsp] {symbol} {tf} events={payload['n_events']} "
            f"probs={stats.get('outcome_probs')} "
            f"by_dir={list((stats.get('by_direction_detail') or {}).keys())}"
        )
        print(f"[lsp] wrote {paths['latest']}")
        register_experiment(
            name=f"lsp_{symbol}_{tf}",
            kind="lsp_sweep",
            params={"symbol": symbol, "contract": contract, "period": per},
            metrics={
                "n_events": payload["n_events"],
                "outcome_probs": stats.get("outcome_probs"),
                "avg_mfe_atr": stats.get("avg_mfe_atr"),
                "avg_mae_atr": stats.get("avg_mae_atr"),
            },
            validation={"stats": stats},
            artifact=paths["latest"],
            status="Research",
            notes="LSP sweep study; does not change Path-A entries.",
            root=ROOT,
        )

    if "15m" in payloads and "60m" in payloads:
        res_events = resonate_with_higher_tf(
            payloads["15m"]["events"], payloads["60m"]["events"]
        )
        rstats = resonance_stats(res_events)
        payloads["15m"]["events"] = res_events
        payloads["15m"]["stats"]["resonance"] = rstats
        paths = save_lsp_run(payloads["15m"], root=ROOT)
        print(f"[lsp] {symbol} resonance {rstats} → {paths['latest']}")
    return payloads


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="CF")
    ap.add_argument("--contract", default=None)
    ap.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated product codes; overrides --symbol. "
        f"Default desk set: {','.join(DEFAULT_LSP_SYMBOLS)}",
    )
    ap.add_argument("--period", default="15", choices=("15", "60", "both"))
    ap.add_argument(
        "--daily",
        action="store_true",
        help="Bulk soft refresh (no experiment registry); same path as daily_update",
    )
    args = ap.parse_args(argv)

    if args.daily:
        codes = (
            [c.strip().upper() for c in str(args.symbols).split(",") if c.strip()]
            if args.symbols
            else list(DEFAULT_LSP_SYMBOLS)
        )
        summary = refresh_lsp_universe(ROOT, symbols=codes, period=args.period)
        print(
            f"[lsp] daily refresh ok={summary.get('ok')} "
            f"n_ok={summary.get('n_ok')} n_skip={summary.get('n_skip')}"
        )
        return 0 if summary.get("ok") else 1

    codes = (
        [c.strip().upper() for c in str(args.symbols).split(",") if c.strip()]
        if args.symbols
        else [str(args.symbol).upper()]
    )
    ok_any = False
    for code in codes:
        contract = resolve_lsp_contract(
            ROOT, code, args.contract if len(codes) == 1 else None
        )
        print(f"[lsp] === {code} contract={contract or 'auto/none'} ===")
        payloads = _run_one(code, contract, args.period)
        ok_any = ok_any or bool(payloads)
    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
