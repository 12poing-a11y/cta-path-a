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

from lab.lsp.pipeline import load_bars_from_minute_cache, run_lsp, save_lsp_run  # noqa: E402
from lab.lsp.resonance import resonate_with_higher_tf, resonance_stats  # noqa: E402
from research.governance import register_experiment  # noqa: E402


def _resolve_contract(root: Path, code: str, explicit: str | None) -> str | None:
    if explicit:
        return str(explicit).upper()
    try:
        from minute_data import resolve_dominant_contract

        dom = resolve_dominant_contract(root, code)
        if isinstance(dom, dict) and dom.get("symbol"):
            return str(dom["symbol"]).upper()
    except Exception:
        pass
    # Fallback: pick a month file from minute cache (prefer 2701/2612-style stems).
    minute = root / ".cache" / "akshare" / "minute"
    if minute.is_dir():
        stems: list[str] = []
        for p in minute.glob(f"{code}*_15_sina.json"):
            stem = p.name.split("_")[0].upper()
            rest = stem[len(code) :]
            if rest[:1].isdigit() and stem != f"{code}0":
                stems.append(stem)
        if stems:
            return sorted(stems)[-1]
    return None


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
        help="Comma-separated product codes; overrides --symbol",
    )
    ap.add_argument("--period", default="15", choices=("15", "60", "both"))
    args = ap.parse_args(argv)

    codes = (
        [c.strip().upper() for c in str(args.symbols).split(",") if c.strip()]
        if args.symbols
        else [str(args.symbol).upper()]
    )
    ok_any = False
    for code in codes:
        contract = _resolve_contract(ROOT, code, args.contract if len(codes) == 1 else None)
        print(f"[lsp] === {code} contract={contract or 'auto/none'} ===")
        payloads = _run_one(code, contract, args.period)
        ok_any = ok_any or bool(payloads)
    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
