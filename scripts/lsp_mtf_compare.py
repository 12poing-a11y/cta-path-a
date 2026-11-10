# -*- coding: utf-8 -*-
"""Compare LSP shadows: daily / 60m / daily-SMA×60m / Path-A-align×60m.

Paper only. Writes data/lsp/shadow/lsp_mtf_compare_<CODE>.json

Usage:
  python scripts/lsp_mtf_compare.py --code CF
  python scripts/lsp_mtf_compare.py --code CF,MA,FG
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lsp_shadow import DEFAULT_CFG, load_daily_bars, load_minute_bars, run_one  # noqa: E402
from signals.lsp_eval import assert_shadow_destination  # noqa: E402
from signals.lsp_mtf import (  # noqa: E402
    DailyBiasParams,
    daily_bias_map,
    detect_lsp_60m_with_daily_filter,
    filter_signals_by_daily_bias,
)
from signals.lsp_profile import detect_lsp_sweeps, load_run_config, params_from_config  # noqa: E402
from signals.lsp_sim import simulate_lsp_trades, summarize_trades  # noqa: E402

SHADOW_DIR = ROOT / "data" / "lsp" / "shadow"


def path_a_align_bias_map(daily_bars: list[dict[str, Any]]) -> dict[str, str]:
    """Path-A style same-sign 20/60 momentum bias at each daily close."""
    closes: list[float] = []
    dates: list[str] = []
    out: dict[str, str] = {}
    for b in daily_bars:
        d = str(b.get("date") or "")[:10]
        if len(d) != 10:
            continue
        try:
            c = float(b["close"])
        except (KeyError, TypeError, ValueError):
            continue
        closes.append(c)
        dates.append(d)
        i = len(closes) - 1
        if i < 60:
            out[d] = "flat"
            continue
        r20 = closes[i] / closes[i - 20] - 1.0
        r60 = closes[i] / closes[i - 60] - 1.0
        if r20 > 0 and r60 > 0:
            out[d] = "long"
        elif r20 < 0 and r60 < 0:
            out[d] = "short"
        else:
            out[d] = "flat"
    return out


def _run_filtered_60m(
    *,
    code: str,
    daily: list[dict[str, Any]],
    bars_60: list[dict[str, Any]],
    cfg_path: Path,
    label: str,
    bias_map: dict[str, str],
    bar_meta: dict[str, Any],
) -> dict[str, Any]:
    cfg = load_run_config(cfg_path)
    params = params_from_config(cfg)
    raw = detect_lsp_sweeps(bars_60, params, timeframe="60")
    kept, rejected = filter_signals_by_daily_bias(raw.signals, bias_map)  # type: ignore[arg-type]
    risk = cfg.get("risk") or {}
    costs = cfg.get("costs") or {}
    execution = cfg.get("execution") or {}
    trades, skipped = simulate_lsp_trades(
        bars_60,
        kept,
        reward_rr=float(risk.get("shadow_reward_rr", 1.5)),
        slippage_bps=float(costs.get("slippage_bps", 0)),
        commission_bps_per_side=float(costs.get("commission_bps_per_side", 0)),
        one_position_at_a_time=bool(execution.get("one_position_at_a_time", True)),
    )
    summary = summarize_trades(trades)
    payload = {
        "track": "lsp_mtf_compare",
        "variant": label,
        "live_trading": False,
        "formal_path_a_untouched": True,
        "symbol": code,
        "timeframe": "60_filtered",
        "n_bars_60": len(bars_60),
        "n_raw_signals": len(raw.signals),
        "n_kept_signals": len(kept),
        "n_rejected": len(rejected),
        "summary": summary,
        "bar_meta": bar_meta,
        "disclaimer": "纸面影子：日线过滤×60m LSP；不改 Path-A。",
    }
    return payload


def compare_code(code: str, cfg_path: Path = DEFAULT_CFG) -> dict[str, Any]:
    code = code.upper()
    daily = load_daily_bars(code)
    bars_60, pack = load_minute_bars(ROOT, code, "60")
    if len(daily) < 80 or len(bars_60) < 80:
        return {
            "ok": False,
            "symbol": code,
            "error": f"bars too few daily={len(daily)} 60m={len(bars_60)}",
        }
    meta60 = {
        "source": pack.get("source"),
        "symbol": pack.get("symbol"),
        "note": pack.get("note"),
    }
    variants: list[dict[str, Any]] = []

    daily_pay = run_one(daily, cfg_path, symbol=code, timeframe="daily", extra_meta={"source": "load_free_bars"})
    variants.append(
        {
            "variant": "daily_lsp",
            "label": "纯日线 LSP",
            "summary": daily_pay["summary"],
            "n_signals": daily_pay["detection"]["n_signals"],
            "path": daily_pay.get("path"),
        }
    )

    m60 = run_one(bars_60, cfg_path, symbol=code, timeframe="60", extra_meta=meta60)
    variants.append(
        {
            "variant": "m60_lsp",
            "label": "纯60m LSP",
            "summary": m60["summary"],
            "n_signals": m60["detection"]["n_signals"],
            "path": m60.get("path"),
        }
    )

    sma_bias = daily_bias_map(daily, DailyBiasParams(sma_len=20))
    sma_pay = _run_filtered_60m(
        code=code,
        daily=daily,
        bars_60=bars_60,
        cfg_path=cfg_path,
        label="daily_sma20_x_60m",
        bias_map=sma_bias,
        bar_meta=meta60,
    )
    variants.append(
        {
            "variant": "daily_sma20_x_60m",
            "label": "日线SMA20过滤 × 60m入场",
            "summary": sma_pay["summary"],
            "n_signals": sma_pay["n_kept_signals"],
            "n_raw_signals": sma_pay["n_raw_signals"],
            "n_rejected": sma_pay["n_rejected"],
        }
    )

    pa_bias = path_a_align_bias_map(daily)
    pa_pay = _run_filtered_60m(
        code=code,
        daily=daily,
        bars_60=bars_60,
        cfg_path=cfg_path,
        label="path_a_align_x_60m",
        bias_map=pa_bias,
        bar_meta=meta60,
    )
    variants.append(
        {
            "variant": "path_a_align_x_60m",
            "label": "日线20/60同向过滤 × 60m入场",
            "summary": pa_pay["summary"],
            "n_signals": pa_pay["n_kept_signals"],
            "n_raw_signals": pa_pay["n_raw_signals"],
            "n_rejected": pa_pay["n_rejected"],
        }
    )

    # Also materialize filtered packs for audit
    pack_mtf = detect_lsp_60m_with_daily_filter(daily, bars_60)
    out = {
        "ok": True,
        "symbol": code,
        "live_trading": False,
        "n_daily": len(daily),
        "n_60m": len(bars_60),
        "variants": variants,
        "mtf_pack_meta": {
            "n_raw": pack_mtf["n_raw_signals"],
            "n_kept": pack_mtf["n_kept_signals"],
            "n_rejected": pack_mtf["n_rejected"],
        },
        "disclaimer": (
            "纸面对照：日线定方向、60m找扫荡收回入场；"
            "零成本控制；不改 paper_book / entry_filter。"
        ),
    }
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    path = assert_shadow_destination(ROOT, SHADOW_DIR / f"lsp_mtf_compare_{code}.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["path"] = str(path.relative_to(ROOT))
    return out


def _print_table(pack: dict[str, Any]) -> None:
    print(f"\n=== {pack.get('symbol')} ===")
    if not pack.get("ok"):
        print(" ", pack.get("error"))
        return
    print(f"  daily_bars={pack['n_daily']}  60m_bars={pack['n_60m']}")
    print(f"{'方案':<28} {'信号':>6} {'成交':>6} {'胜率':>8} {'平均R':>8} {'累计R':>8}")
    for v in pack.get("variants") or []:
        s = v.get("summary") or {}
        sig = v.get("n_signals")
        n = int(s.get("n") or 0)
        wr = s.get("win_rate")
        ar = s.get("avg_r")
        sr = s.get("sum_r")
        wr_s = f"{wr:.2%}" if wr is not None else "—"
        ar_s = f"{ar:.3f}" if ar is not None else "—"
        sr_s = f"{sr:.2f}" if sr is not None else "—"
        print(f"{str(v.get('label')):<28} {sig:>6} {n:>6} {wr_s:>8} {ar_s:>8} {sr_s:>8}")


def main() -> int:
    ap = argparse.ArgumentParser(description="LSP MTF compare (daily filter × 60m)")
    ap.add_argument("--code", default="CF", help="comma-separated codes")
    ap.add_argument("--config", type=Path, default=DEFAULT_CFG)
    args = ap.parse_args()
    codes = [c.strip().upper() for c in str(args.code).split(",") if c.strip()]
    rows = []
    for code in codes:
        pack = compare_code(code, args.config)
        rows.append(pack)
        _print_table(pack)
        if pack.get("path"):
            print(f"  → {pack['path']}")
    return 0 if any(r.get("ok") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
