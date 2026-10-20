# -*- coding: utf-8 -*-
"""Path-A weekly paper PnL from local daily reports / signal ledger."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")
def _cfg():
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    equity = float(cfg.get("equity", 200_000))
    mult = {s["code"]: s["mult"] for s in cfg.get("symbols", [])}
    return equity, mult


EQUITY0, MULT = _cfg()


def _load_reports():
    """Prefer archived daily snapshots if present; else current report only."""
    archive = ROOT / "archive"
    reports = []
    if archive.exists():
        for p in sorted(archive.glob("l1_report_*.json")):
            try:
                reports.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    cur = ROOT / "l1_report_risk15.json"
    if cur.exists():
        reports.append(json.loads(cur.read_text(encoding="utf-8")))
    # dedupe by asof
    by = {}
    for r in reports:
        asof = str(r.get("asof") or "")
        if asof:
            by[asof] = r
    return [by[k] for k in sorted(by)]


def _sign(direction: str) -> int:
    if direction == "多":
        return 1
    if direction == "空":
        return -1
    return 0


def run(days: int = 7) -> dict:
    reps = _load_reports()
    if len(reps) < 2:
        now = datetime.now(TZ)
        return {
            "ok": True,
            "insufficient": True,
            "asof": now.strftime("%Y-%m-%d"),
            "trade_days": len(reps),
            "equity_end": EQUITY0,
            "ret_pct": 0.0,
            "max_dd_pct": 0.0,
            "win_rate": None,
            "avg_held": 0.0,
            "violations": 0,
            "conclusion": "继续L1",
            "summary": f"样本不足（仅{len(reps)}个交易日快照）。需≥2日收盘才能估算纸面PnL。",
            "detail": json.dumps({"asofs": [r.get("asof") for r in reps]}, ensure_ascii=False),
        }

    # use last N reports
    reps = reps[-(days + 1) :]
    equity = EQUITY0
    peak = equity
    max_dd = 0.0
    day_rets = []
    held_counts = []
    violations = 0

    # positions from day i applied to move i -> i+1
    for i in range(len(reps) - 1):
        a, b = reps[i], reps[i + 1]
        sig_a = {s["code"]: s for s in a.get("signals", []) if "code" in s}
        sig_b = {s["code"]: s for s in b.get("signals", []) if "code" in s}
        pnl = 0.0
        held = 0
        for code, s in sig_a.items():
            lots = int(s.get("lots_l1") or 0)
            direction = s.get("direction") or "空仓"
            # rule check
            align = s.get("align")
            if lots > 0 and align != "同向":
                violations += 1
            if lots <= 0:
                continue
            held += 1
            if code not in sig_b or sig_b[code].get("close") is None or s.get("close") is None:
                continue
            px0, px1 = float(s["close"]), float(sig_b[code]["close"])
            pnl += (px1 - px0) * MULT.get(code, 10) * lots * _sign(direction)
        equity += pnl
        day_rets.append(pnl)
        held_counts.append(held)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)

    wins = sum(1 for x in day_rets if x > 0)
    win_rate = (wins / len(day_rets) * 100) if day_rets else None
    ret_pct = (equity / EQUITY0 - 1) * 100
    avg_held = sum(held_counts) / len(held_counts) if held_counts else 0

    if max_dd >= 20:
        conclusion = "暂停"
    elif max_dd >= 12 or ret_pct <= -5:
        conclusion = "减仓观察"
    elif abs(ret_pct) < 0.5 and len(day_rets) >= 5:
        conclusion = "参数微调"
    else:
        conclusion = "继续L1"

    start = reps[0].get("asof")
    end = reps[-1].get("asof")
    summary = (
        f"{start}->{end} 纸面权益 {equity:.0f}（{ret_pct:+.2f}%），"
        f"MaxDD {max_dd:.2f}%，日胜率 {win_rate:.1f}%（样本{len(day_rets)}），"
        f"均持仓品种 {avg_held:.1f}，规则违约 {violations}。"
    )
    out = {
        "ok": True,
        "insufficient": False,
        "start": start,
        "end": end,
        "trade_days": len(day_rets),
        "equity_end": round(equity, 2),
        "ret_pct": round(ret_pct, 3),
        "max_dd_pct": round(max_dd, 3),
        "win_rate": round(win_rate, 2) if win_rate is not None else None,
        "avg_held": round(avg_held, 2),
        "violations": violations,
        "conclusion": conclusion,
        "summary": summary,
        "detail": json.dumps({"day_pnls": day_rets}, ensure_ascii=False),
    }
    path = ROOT / "weekly_backtest_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    run(7)
