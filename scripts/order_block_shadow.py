# -*- coding: utf-8 -*-
"""Run the order-block shadow baseline.

Writes data/order_block/shadow/ only. Does not place orders and does not
touch formal Path-A latest artifacts or execution_rules.json.

Usage:
  python scripts/order_block_shadow.py --demo
  python scripts/order_block_shadow.py --bars bars.json
  python scripts/order_block_shadow.py --code RB
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

from signals.order_block import detect_order_blocks, load_run_config, params_from_config  # noqa: E402
from signals.order_block_eval import (  # noqa: E402
    ablation_plan,
    assert_shadow_destination,
    summarize_trades,
    walk_forward_plan,
)
from signals.order_block_sim import simulate_retest_trades  # noqa: E402

SHADOW_DIR = ROOT / "data" / "order_block" / "shadow"


def demo_bars() -> list[dict[str, Any]]:
    """One long break, one retest, then a target hit. Offline and deterministic."""
    rows = [
        (10, 11, 9, 10),
        (10, 12, 9, 11),
        (11, 13, 10, 12),
        (12, 14, 11, 13),
        (13, 20, 12, 19),
        (19, 19.5, 14, 15),
        (15, 16, 13, 14),
        (14, 17, 13, 16),
        (16, 18, 12, 13),
        (13, 26, 13, 25),
        (25, 27, 24, 26),
        (26, 26, 14, 18),
        (18, 19, 15, 18),
        (18, 20, 16, 19),
        (19, 30, 18, 29),
    ]
    out = []
    for i, (o, h, l, c) in enumerate(rows):
        out.append(
            {
                "date": f"2024-01-{i + 2:02d}",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 1,
            }
        )
    return out


def load_bars_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("bars")
    if not isinstance(payload, list):
        raise ValueError("bars file must be a list or an object with a bars list")
    return payload


def load_market_bars(code: str) -> list[dict[str, Any]]:
    from market_data import load_free_bars

    bars, _meta = load_free_bars(code)
    return bars


def run_shadow(
    bars: list[dict[str, Any]],
    config_path: Path,
    *,
    symbol: str,
    root: Path | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Detect, simulate, and write one shadow JSON. Returns the payload."""
    root = root or ROOT
    cfg = load_run_config(config_path)
    params = params_from_config(cfg)
    # Copy so detection's float coercion cannot surprise the caller.
    bars_in = [dict(b) for b in bars]
    detection = detect_order_blocks(bars_in, params)
    risk = cfg.get("risk") or {}
    costs = cfg.get("costs") or {}
    execution = cfg.get("execution") or {}
    trades, skipped = simulate_retest_trades(
        bars_in,
        detection.signals,
        reward_rr=float(risk.get("shadow_reward_rr", 1.5)),
        slippage_bps=float(costs.get("slippage_bps", 0)),
        commission_bps_per_side=float(costs.get("commission_bps_per_side", 0)),
        one_position_at_a_time=bool(execution.get("one_position_at_a_time", True)),
    )
    raw_cfg = config_path.read_bytes()
    payload: dict[str, Any] = {
        "track": "order_block_shadow",
        "live_trading": False,
        "formal_path_a_untouched": True,
        "symbol": symbol,
        "config_path": str(config_path),
        "config_sha256": hashlib.sha256(raw_cfg).hexdigest(),
        "bar_count": len(bars_in),
        "claims": {
            "alpha": False,
            "promoted_to_formal": False,
            "role": "location_stop",
            "note": "Order block is a shadow location and stop study. No edge is claimed.",
        },
        "order_blocks": [o.to_dict() for o in detection.order_blocks],
        "signals": [s.to_dict() for s in detection.signals],
        "unzoned_breaks": [u.to_dict() for u in detection.unzoned_breaks],
        "trades": [t.to_dict() for t in trades],
        "skipped_signals": [s.to_dict() for s in skipped],
        "metrics": summarize_trades(trades),
        "evaluation": {
            "ablation": ablation_plan(),
            "walk_forward": walk_forward_plan(),
        },
    }
    dest_dir = out_dir or (root / "data" / "order_block" / "shadow")
    filename = f"ob_shadow_{symbol}_{len(bars_in)}bars.json"
    dest = assert_shadow_destination(root, dest_dir / filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["output_path"] = str(dest)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Order-block shadow baseline (no orders)")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "order_block" / "baseline.json",
    )
    parser.add_argument("--demo", action="store_true", help="run the built-in series")
    parser.add_argument("--bars", type=Path, help="OHLC JSON file")
    parser.add_argument("--code", default="", help="continuous symbol via market_data.load_free_bars")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    sources = sum(bool(x) for x in (args.demo, args.bars, args.code))
    if sources != 1:
        parser.error("choose exactly one of --demo, --bars, or --code")
    if args.demo:
        bars = demo_bars()
        symbol = "DEMO"
    elif args.bars:
        bars = load_bars_file(args.bars)
        symbol = args.bars.stem.upper()
    else:
        bars = load_market_bars(args.code.strip().upper())
        symbol = args.code.strip().upper()

    try:
        payload = run_shadow(
            bars,
            args.config,
            symbol=symbol,
            out_dir=args.out_dir,
        )
    except ValueError as exc:
        print(f"[ob-shadow] {exc}", file=sys.stderr)
        return 2
    metrics = payload["metrics"]
    print(
        f"[ob-shadow] symbol={payload['symbol']} bars={payload['bar_count']} "
        f"zones={len(payload['order_blocks'])} signals={len(payload['signals'])} "
        f"trades={metrics['trade_count']} wrote={payload['output_path']}"
    )
    print("[ob-shadow] shadow only; formal Path-A latest was not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
