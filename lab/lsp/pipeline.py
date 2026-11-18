# -*- coding: utf-8 -*-
"""End-to-end LSP research run for one symbol/timeframe."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab.lsp.detect import detect_sweep_events
from lab.lsp.label import label_events
from lab.lsp.stats import summarize_events

ROOT = Path(__file__).resolve().parents[2]


def load_bars_from_minute_cache(
    root: Path,
    code: str,
    period: str = "15",
    *,
    contract: str | None = None,
) -> tuple[list[dict], str]:
    """Load merged minute bars; prefer explicit contract file when given."""
    from minute_data import load_minute_bars_series

    symbol = str(contract or code).upper()
    # Prefer contract-specific series when present
    bars = load_minute_bars_series(root, code.upper(), period)
    if contract:
        # Filter is already by code variety; contract files merge in load_minute_bars_series
        pass
    return bars, symbol


def run_lsp(
    bars: list[dict[str, Any]],
    *,
    symbol: str = "CF",
    contract: str | None = "CF2701",
    timeframe: str = "15m",
    reclaim_bars: int = 5,
) -> dict[str, Any]:
    events = detect_sweep_events(
        bars,
        symbol=symbol,
        contract=contract,
        timeframe=timeframe,
    )
    labeled = label_events(bars, events, reclaim_bars=reclaim_bars)
    stats = summarize_events(labeled)
    return {
        "ok": True,
        "schema": "cta-lsp-run-v1",
        "symbol": symbol,
        "contract": contract,
        "timeframe": timeframe,
        "n_bars": len(bars),
        "n_events": len(labeled),
        "stats": stats,
        "events": labeled,
        "live_trading": False,
        "status": "Research",
    }


def save_lsp_run(payload: dict[str, Any], root: Path | None = None) -> dict[str, str]:
    root = root or ROOT
    out_dir = root / "lab" / "research" / "lsp"
    out_dir.mkdir(parents=True, exist_ok=True)
    full = out_dir / f"lsp_{payload.get('symbol')}_{payload.get('timeframe')}_latest.json"
    # Compact latest without dumping every bar
    slim_events = payload.get("events") or []
    latest = {
        **{k: v for k, v in payload.items() if k != "events"},
        "events_tail": slim_events[-50:],
        "events_n": len(slim_events),
    }
    full.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Full event list separate (still small vs minute cache)
    ev_path = out_dir / f"lsp_{payload.get('symbol')}_{payload.get('timeframe')}_events.json"
    ev_path.write_text(
        json.dumps(slim_events, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "latest": str(full.relative_to(root)),
        "events": str(ev_path.relative_to(root)),
    }


# Desk / daily soft refresh universe (matches existing lab/research/lsp coverage).
DEFAULT_LSP_SYMBOLS: tuple[str, ...] = (
    "CF",
    "P",
    "RB",
    "MA",
    "TA",
    "RU",
    "CU",
    "AU",
    "AG",
    "I",
    "FG",
    "SA",
)


def resolve_lsp_contract(root: Path, code: str, explicit: str | None = None) -> str | None:
    """Dominant or latest month file for LSP bar load."""
    if explicit:
        return str(explicit).upper()
    try:
        from minute_data import resolve_dominant_contract

        dom = resolve_dominant_contract(root, code)
        if isinstance(dom, dict) and dom.get("symbol"):
            return str(dom["symbol"]).upper()
    except Exception:
        pass
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


def refresh_lsp_universe(
    root: Path | None = None,
    *,
    symbols: list[str] | tuple[str, ...] | None = None,
    period: str = "both",
) -> dict[str, Any]:
    """Recompute LSP latest/events from minute cache. Research-only; no paper_book.

    Soft-safe for daily_update: skips symbols with insufficient bars.
    """
    from lab.lsp.resonance import resonate_with_higher_tf, resonance_stats

    root = root or ROOT
    codes = [str(c).strip().upper() for c in (symbols or DEFAULT_LSP_SYMBOLS) if str(c).strip()]
    periods = ("15", "60") if period == "both" else (period,)
    rows: list[dict[str, Any]] = []
    ok_n = 0
    skip_n = 0
    for code in codes:
        contract = resolve_lsp_contract(root, code)
        payloads: dict[str, Any] = {}
        for per in periods:
            tf = f"{per}m"
            bars, _sym = load_bars_from_minute_cache(root, code, per, contract=contract)
            if len(bars) < 80:
                skip_n += 1
                rows.append(
                    {
                        "symbol": code,
                        "timeframe": tf,
                        "ok": False,
                        "reason": "insufficient_bars",
                        "n_bars": len(bars),
                    }
                )
                continue
            payload = run_lsp(bars, symbol=code, contract=contract, timeframe=tf)
            payloads[tf] = payload
            paths = save_lsp_run(payload, root=root)
            ok_n += 1
            rows.append(
                {
                    "symbol": code,
                    "timeframe": tf,
                    "ok": True,
                    "n_bars": payload["n_bars"],
                    "n_events": payload["n_events"],
                    "bar_end": (bars[-1] or {}).get("datetime"),
                    "path": paths.get("latest"),
                }
            )
        if "15m" in payloads and "60m" in payloads:
            res_events = resonate_with_higher_tf(
                payloads["15m"]["events"], payloads["60m"]["events"]
            )
            rstats = resonance_stats(res_events)
            payloads["15m"]["events"] = res_events
            payloads["15m"]["stats"]["resonance"] = rstats
            save_lsp_run(payloads["15m"], root=root)
    return {
        "ok": ok_n > 0,
        "schema": "cta-lsp-refresh-v1",
        "n_ok": ok_n,
        "n_skip": skip_n,
        "symbols": codes,
        "period": period,
        "rows": rows,
    }
