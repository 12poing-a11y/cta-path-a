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
