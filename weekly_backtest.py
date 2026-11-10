# -*- coding: utf-8 -*-
"""Path-A weekly KPI from the same simulate engine as historical_backtest.

Paper only. Headline equity/ret/dd come from historical_simulate (next_open + costs).
paper_book equity is a side note only — never overlays ret_pct.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TZ = ZoneInfo("Asia/Shanghai")


def _paper_book_equity() -> float | None:
    try:
        from paper_book import load_paper_positions

        pb = load_paper_positions(ROOT)
        if pb.get("ok") and pb.get("equity") is not None:
            return float(pb["equity"])
    except Exception:
        return None
    return None


def _slice_curve_kpis(curve: list[dict], days: int) -> dict:
    """Window KPIs from equity_curve tail (last `days` steps of equity change)."""
    if not curve:
        return {
            "window_start": None,
            "window_end": None,
            "window_trade_days": 0,
            "window_equity_start": None,
            "window_equity_end": None,
            "window_ret_pct": None,
            "window_max_dd_pct": None,
        }
    n = max(1, int(days))
    # Need n+1 points to cover n day-to-day moves; take last n+1 if available.
    win = curve[-(n + 1) :] if len(curve) > n else list(curve)
    eq0 = float(win[0]["equity"])
    peak = eq0
    max_dd = 0.0
    for row in win:
        eq = float(row["equity"])
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)
    eq1 = float(win[-1]["equity"])
    ret = (eq1 / eq0 - 1.0) * 100.0 if eq0 else 0.0
    return {
        "window_start": win[0].get("date"),
        "window_end": win[-1].get("date"),
        "window_trade_days": max(0, len(win) - 1),
        "window_equity_start": round(eq0, 2),
        "window_equity_end": round(eq1, 2),
        "window_ret_pct": round(ret, 3),
        "window_max_dd_pct": round(max_dd, 3),
    }


def run(days: int = 7) -> dict:
    # GitHub weekly: densify seat ranks (esp. DCE/EM) so desk charts are readable.
    try:
        from member_rank import backfill_member_lookback

        bf = backfill_member_lookback(
            lookback_calendar_days=max(14, int(days) + 7),
            dce=True,
            coverage=True,
        )
        print(
            f"[weekly] member backfill days={bf.get('days')} "
            f"dce={bf.get('dce')} em={bf.get('eastmoney')} "
            f"cov_ok={bf.get('coverage_ok')}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly] member backfill soft-fail: {exc}")

    import historical_backtest as hb

    p = hb._load_cfg()
    mode = p.get("entry_filter") or "seats"
    if mode not in ("base", "p0", "carry", "oi", "member", "climax", "seats", "roll", "ctf"):
        mode = "seats"

    try:
        sim = hb._simulate_cfg(p, mode)
    except Exception as exc:  # noqa: BLE001
        now = datetime.now(TZ)
        out = {
            "ok": False,
            "insufficient": True,
            "engine": "historical_simulate",
            "asof": now.strftime("%Y-%m-%d"),
            "trade_days": 0,
            "equity_end": float(p["equity0"]),
            "ret_pct": 0.0,
            "max_dd_pct": 0.0,
            "win_rate": None,
            "avg_held": 0.0,
            "violations": 0,
            "conclusion": "继续L1",
            "summary": f"周度模拟失败：{exc}",
            "fill_price": p.get("fill_price"),
            "live_trading": False,
            "detail": json.dumps({"error": str(exc)}, ensure_ascii=False),
        }
        (ROOT / "weekly_backtest_latest.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return out

    if not sim.get("ok"):
        now = datetime.now(TZ)
        out = {
            "ok": False,
            "insufficient": True,
            "engine": "historical_simulate",
            "asof": now.strftime("%Y-%m-%d"),
            "trade_days": 0,
            "equity_end": float(p["equity0"]),
            "ret_pct": 0.0,
            "max_dd_pct": 0.0,
            "win_rate": None,
            "avg_held": 0.0,
            "violations": 0,
            "conclusion": "继续L1",
            "summary": "周度模拟未成功（sim.ok=false）。",
            "fill_price": sim.get("fill_price") or p.get("fill_price"),
            "live_trading": False,
            "detail": json.dumps({"sim": {k: sim.get(k) for k in ("errors", "summary")}}, ensure_ascii=False),
        }
        (ROOT / "weekly_backtest_latest.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return out

    curve = sim.get("equity_curve") or []
    win = _slice_curve_kpis(curve, days)
    paper_eq = _paper_book_equity()

    # Headline KPIs = full simulate (same口径 as historical); window_* = recent slice.
    equity_end = float(sim.get("equity_end") or p["equity0"])
    ret_pct = float(sim.get("ret_pct") or 0.0)
    max_dd = float(sim.get("max_dd_pct") or 0.0)
    conclusion = sim.get("conclusion") or "继续L1"

    summary = (
        f"{sim.get('start')}->{sim.get('end')} 模拟权益 {equity_end:.0f}（{ret_pct:+.2f}%），"
        f"MaxDD {max_dd:.2f}%，成交{sim.get('closed_trades')}笔，"
        f"fill={sim.get('fill_price')}，近{days}日窗 "
        f"{win.get('window_ret_pct')}% / dd {win.get('window_max_dd_pct')}%。"
        f" 引擎=historical_simulate；paper_book权益旁注={paper_eq}。"
    )
    out = {
        "ok": True,
        "insufficient": False,
        "engine": "historical_simulate",
        "schema_version": sim.get("schema_version"),
        "live_trading": False,
        "start": sim.get("start"),
        "end": sim.get("end"),
        "trade_days": sim.get("trade_days"),
        "equity_end": round(equity_end, 2),
        "ret_pct": round(ret_pct, 3),
        "max_dd_pct": round(max_dd, 3),
        "gross_ret_pct": sim.get("gross_ret_pct"),
        "gross_max_dd_pct": sim.get("gross_max_dd_pct"),
        "cost_yuan": sim.get("cost_yuan"),
        "win_rate": sim.get("win_rate"),
        "trade_win_rate": sim.get("trade_win_rate"),
        "avg_held": sim.get("avg_held"),
        "closed_trades": sim.get("closed_trades"),
        "violations": 0,
        "conclusion": conclusion,
        "summary": summary,
        "fill_price": sim.get("fill_price"),
        "slippage_ticks": sim.get("slippage_ticks"),
        "availability_lag": sim.get("availability_lag"),
        "git_sha": sim.get("git_sha"),
        "universe_sha256": sim.get("universe_sha256"),
        "execution_rules_sha256": sim.get("execution_rules_sha256"),
        "ledger": "historical_simulate",
        "paper_book_equity": paper_eq,
        **win,
        "detail": json.dumps(
            {
                "mode": sim.get("mode"),
                "exits": sim.get("exits"),
                "window_days": days,
            },
            ensure_ascii=False,
        ),
    }
    path = ROOT / "weekly_backtest_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    run(7)
