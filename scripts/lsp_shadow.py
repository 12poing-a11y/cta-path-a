# -*- coding: utf-8 -*-
"""Run LSP (liquidity sweep × volume-profile) shadow on daily and/or 60m.

Writes data/lsp/shadow/ only. Does not touch Path-A formal artifacts.

Usage:
  python scripts/lsp_shadow.py --demo
  python scripts/lsp_shadow.py --code CF --tf daily
  python scripts/lsp_shadow.py --code CF --tf 60
  python scripts/lsp_shadow.py --code CF --tf both
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signals.lsp_eval import assert_shadow_destination  # noqa: E402
from signals.lsp_profile import detect_lsp_sweeps, load_run_config, params_from_config  # noqa: E402
from signals.lsp_sim import simulate_lsp_trades, summarize_trades  # noqa: E402

SHADOW_DIR = ROOT / "data" / "lsp" / "shadow"
DEFAULT_CFG = ROOT / "configs" / "lsp" / "baseline.json"


def demo_bars() -> list[dict[str, Any]]:
    """Build a clear sweep-high-reclaim then sweep-low-reclaim sequence."""
    # Flat range with volume → value area ~ mid; then pierce high & reclaim; later pierce low & reclaim.
    rows: list[dict[str, Any]] = []
    px = 100.0
    for i in range(60):
        o = px
        c = px + (0.2 if i % 2 == 0 else -0.2)
        h, l = max(o, c) + 0.3, min(o, c) - 0.3
        rows.append(
            {
                "date": f"2024-01-{(i % 28) + 1:02d}",
                "datetime": f"2024-01-{(i % 28) + 1:02d}T10:00:00",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 100 + (i % 5) * 10,
            }
        )
        px = c
    # bar: sweep high then close back
    last = rows[-1]["close"]
    rows.append(
        {
            "date": "2024-03-01",
            "datetime": "2024-03-01T10:00:00",
            "open": last,
            "high": last + 5.0,
            "low": last - 0.2,
            "close": last - 0.5,
            "volume": 200,
        }
    )
    # quiet bars
    px = rows[-1]["close"]
    for i in range(5):
        rows.append(
            {
                "date": f"2024-03-{i + 2:02d}",
                "datetime": f"2024-03-{i + 2:02d}T10:00:00",
                "open": px,
                "high": px + 0.4,
                "low": px - 0.4,
                "close": px + 0.1,
                "volume": 80,
            }
        )
        px = rows[-1]["close"]
    # sweep low reclaim
    rows.append(
        {
            "date": "2024-03-10",
            "datetime": "2024-03-10T10:00:00",
            "open": px,
            "high": px + 0.2,
            "low": px - 5.0,
            "close": px + 0.3,
            "volume": 220,
        }
    )
    rows.append(
        {
            "date": "2024-03-11",
            "datetime": "2024-03-11T10:00:00",
            "open": px + 0.3,
            "high": px + 1.0,
            "low": px - 0.2,
            "close": px + 0.8,
            "volume": 90,
        }
    )
    return rows


def load_daily_bars(code: str) -> list[dict[str, Any]]:
    from market_data import load_free_bars

    bars, _meta = load_free_bars(code)
    return bars


def load_minute_bars(root: Path, code: str, period: str = "60") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from minute_data import ensure_minute_for_code

    pack = ensure_minute_for_code(root, code, period, force=False, verify_em=False)
    bars = pack.get("bars") or []
    # Normalize date field for simulator display
    out = []
    for b in bars:
        row = dict(b)
        if not row.get("date") and row.get("datetime"):
            row["date"] = str(row["datetime"])[:10]
        out.append(row)
    return out, pack


def run_one(
    bars: list[dict[str, Any]],
    config_path: Path,
    *,
    symbol: str,
    timeframe: str,
    root: Path | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = root or ROOT
    cfg = load_run_config(config_path)
    params = params_from_config(cfg)
    # 60m: denser bars → keep lookback; daily ok with 48
    bars_in = [dict(b) for b in bars]
    detection = detect_lsp_sweeps(bars_in, params, timeframe=timeframe)
    risk = cfg.get("risk") or {}
    costs = cfg.get("costs") or {}
    execution = cfg.get("execution") or {}
    trades, skipped = simulate_lsp_trades(
        bars_in,
        detection.signals,
        reward_rr=float(risk.get("shadow_reward_rr", 1.5)),
        slippage_bps=float(costs.get("slippage_bps", 0)),
        commission_bps_per_side=float(costs.get("commission_bps_per_side", 0)),
        one_position_at_a_time=bool(execution.get("one_position_at_a_time", True)),
    )
    summary = summarize_trades(trades)
    raw_cfg = config_path.read_bytes()
    payload: dict[str, Any] = {
        "track": "lsp_shadow",
        "live_trading": False,
        "formal_path_a_untouched": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "config_path": str(config_path.as_posix()),
        "config_sha256": hashlib.sha256(raw_cfg).hexdigest(),
        "n_bars": len(bars_in),
        "detection": detection.to_dict(),
        "trades": [t.to_dict() for t in trades],
        "skipped": [s.to_dict() for s in skipped],
        "summary": summary,
        "disclaimer": (
            "纸面影子：因果 VP 扫荡收回；非实盘；未接 1m MSS/Delta；"
            "不改 paper_book / entry_filter。"
        ),
    }
    if extra_meta:
        payload["bar_meta"] = extra_meta
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out_name = f"lsp_shadow_{symbol}_{timeframe}_{len(bars_in)}bars.json"
    out_path = assert_shadow_destination(root, SHADOW_DIR / out_name)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["path"] = str(out_path.relative_to(root))
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="LSP shadow runner (daily / 60m)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--code", default="", help="variety code, e.g. CF / MA")
    ap.add_argument(
        "--tf",
        choices=("daily", "60", "both"),
        default="both",
        help="timeframe(s) to run",
    )
    ap.add_argument("--config", type=Path, default=DEFAULT_CFG)
    args = ap.parse_args()

    results: list[dict[str, Any]] = []
    if args.demo:
        bars = demo_bars()
        for tf in ("daily", "60") if args.tf == "both" else (args.tf,):
            # demo uses same synthetic series for both labels
            payload = run_one(bars, args.config, symbol="DEMO", timeframe=tf)
            results.append(payload)
            s = payload["summary"]
            print(
                f"[lsp] DEMO {tf}: signals={payload['detection']['n_signals']} "
                f"trades={s.get('n')} win={s.get('win_rate')} avgR={s.get('avg_r')} → {payload['path']}"
            )
        return 0

    code = str(args.code or "").upper()
    if not code:
        print("需要 --demo 或 --code", file=sys.stderr)
        return 2

    tfs = ("daily", "60") if args.tf == "both" else (args.tf,)
    for tf in tfs:
        if tf == "daily":
            bars = load_daily_bars(code)
            meta = {"source": "load_free_bars"}
        else:
            bars, pack = load_minute_bars(ROOT, code, "60")
            meta = {
                "source": pack.get("source"),
                "symbol": pack.get("symbol"),
                "note": pack.get("note"),
                "ok": pack.get("ok"),
            }
            if not bars:
                print(f"[lsp] {code} 60m 无数据: {pack.get('note')}", file=sys.stderr)
                continue
        if len(bars) < 20:
            print(f"[lsp] {code} {tf}: bars too few ({len(bars)})", file=sys.stderr)
            continue
        payload = run_one(bars, args.config, symbol=code, timeframe=tf, extra_meta=meta)
        results.append(payload)
        s = payload["summary"]
        print(
            f"[lsp] {code} {tf}: bars={payload['n_bars']} signals={payload['detection']['n_signals']} "
            f"trades={s.get('n')} win={s.get('win_rate')} avgR={s.get('avg_r')} sumR={s.get('sum_r')} "
            f"→ {payload['path']}"
        )
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
