# -*- coding: utf-8 -*-
"""CTA L1 Path-A daily paper update. Sina/Tencent bars, iFinD only if those are short."""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ifind_call import active_slot, usage_report  # noqa: E402
from member_rank import load_member_changes  # noqa: E402
from path_a_filters import bucket_reason, entry_block, member_reason  # noqa: E402
from public_curve import load_curves  # noqa: E402
from position_rules import (  # noqa: E402
    apply_portfolio_caps,
    compound_equity,
    risk_budget_yuan,
)

TZ = ZoneInfo("Asia/Shanghai")
EQUITY_STATE_PATH = ROOT / "equity_state.json"


def _load_universe():
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    equity_base = float(cfg.get("equity", 200_000))
    compound = bool(cfg.get("equity_compound", True))
    risk_pct = float(cfg.get("risk_pct", 1.5))
    l1_mult = float(cfg.get("l1_mult", 1.0))
    max_positions = int(cfg.get("max_positions", 3))
    max_gross_pct = float(cfg.get("max_gross_exposure_pct", 50))
    max_port_risk = float(cfg.get("max_portfolio_risk_pct", 10))
    max_per_bucket = int(cfg.get("max_per_bucket", 1))
    min_r20 = float(cfg.get("min_r20_pct", 3))
    min_r60 = float(cfg.get("min_r60_pct", 5))
    symbols = cfg.get("symbols") or []
    return (
        equity_base,
        compound,
        risk_pct,
        l1_mult,
        max_positions,
        max_gross_pct,
        max_port_risk,
        max_per_bucket,
        min_r20,
        min_r60,
        symbols,
    )


def _load_live_equity(equity_base: float) -> tuple[float, dict]:
    """Paper equity from equity_state.json (updated by weekly / prior days)."""
    state = {
        "equity_base": equity_base,
        "equity": equity_base,
        "peak": equity_base,
        "asof": None,
        "source": "universe",
    }
    if EQUITY_STATE_PATH.exists():
        try:
            raw = json.loads(EQUITY_STATE_PATH.read_text(encoding="utf-8"))
            state.update(raw if isinstance(raw, dict) else {})
        except Exception:
            pass
    live = float(state.get("equity") or equity_base)
    if live <= 0:
        live = equity_base
    state["equity"] = live
    state["equity_base"] = equity_base
    return live, state


(
    EQUITY_BASE,
    EQUITY_COMPOUND,
    RISK_PCT,
    L1_MULT,
    MAX_POSITIONS,
    MAX_GROSS_PCT,
    MAX_PORT_RISK_PCT,
    MAX_PER_BUCKET,
    MIN_R20_PCT,
    MIN_R60_PCT,
    UNIVERSE,
) = _load_universe()
LIVE_EQUITY, _EQUITY_STATE = _load_live_equity(EQUITY_BASE)
EQUITY = compound_equity(LIVE_EQUITY, EQUITY_BASE, EQUITY_COMPOUND)
L1_RISK = risk_budget_yuan(EQUITY, RISK_PCT, L1_MULT)


def _entry_mode() -> str:
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    mode = cfg.get("entry_filter") or "p0"
    if mode not in ("p0", "carry", "oi", "member", "climax"):
        return "p0"
    return mode


def _fetch_snapshot(u: dict, curves: dict, mode: str) -> dict:
    """OHLCV from Sina and Tencent. iFinD runs only when that history is short or stale."""
    from historical_backtest import atr14, fetch_history, ret_n

    hist, meta = fetch_history(u, n=120)
    if len(hist) < 61:
        raise RuntimeError(f"bars {len(hist)} source={meta.get('source')}")
    i = len(hist) - 1
    r20 = ret_n(hist, i, 20)
    r60 = ret_n(hist, i, 60)
    atr = atr14(hist, i)
    direction = "空仓"
    if r20 is not None and r60 is not None and r20 != 0 and r60 != 0:
        if (r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0):
            direction = "多" if r20 > 0 else "空"
    blocked = None
    if direction in ("多", "空") and r20 is not None and r60 is not None:
        blocked = entry_block(
            mode,
            hist,
            i,
            direction,
            hist[i]["date"],
            u["code"],
            atr,
            curves,
            {},
            [],
        )
    return {
        "close": hist[i]["close"],
        "r20": round(r20, 4) if r20 is not None else None,
        "r60": round(r60, 4) if r60 is not None else None,
        "atr": round(atr, 2) if atr is not None else None,
        "volume": hist[i].get("volume"),
        "source": meta.get("source"),
        "bar_date": hist[i]["date"],
        "prev_date": hist[i - 1]["date"],
        "sina_n": meta.get("sina_n"),
        "tencent_n": meta.get("tencent_n"),
        "ifind": meta.get("ifind"),
        "block": blocked,
    }


def _signal(u: dict, snap: dict, *, risk_budget: float) -> dict:
    close, atr, r20, r60 = snap.get("close"), snap.get("atr"), snap.get("r20"), snap.get("r60")
    risk_per_lot = (atr * u["mult"]) if atr is not None else None
    align = "冲突/不足"
    direction = "空仓"
    if r20 is not None and r60 is not None and r20 != 0 and r60 != 0:
        if (r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0):
            align = "同向"
            direction = "多" if r20 > 0 else "空"

    lots = 0
    if align == "同向" and risk_per_lot and risk_per_lot > 0:
        lots = int(math.floor(risk_budget / risk_per_lot))

    if align != "同向":
        action = "空仓（20日与60日不同向）"
    elif lots <= 0:
        action = f"有{direction}向，1.5%仍不足1手（每手约{risk_per_lot}）"
    else:
        action = (
            f"候选：{direction}{lots}手（待门槛/板块/Top{MAX_POSITIONS}/"
            f"名义≤{MAX_GROSS_PCT}%/风险≤{MAX_PORT_RISK_PCT}%）"
        )

    today = datetime.now(TZ).strftime("%Y%m%d")
    return {
        "code": u["code"],
        "name": u["name"],
        "ticker": u["ticker"],
        "bucket": u["bucket"],
        "mult": u["mult"],
        "date": today,
        "close": close,
        "atr": round(atr, 2) if atr is not None else None,
        "risk_per_lot": round(risk_per_lot, 1) if risk_per_lot is not None else None,
        "r20": r20,
        "r60": r60,
        "align": align,
        "direction": direction if align == "同向" else "空仓",
        "lots_raw": lots,
        "data_source": snap.get("source"),
        "bar_date": snap.get("bar_date"),
        "lots_l1": lots,
        "lots_full": lots,
        "selected": False,
        "action": action,
    }


def is_weekday_cn() -> bool:
    return datetime.now(TZ).weekday() < 5


def _apply_caps(signals: list[dict], *, sizing_equity: float) -> dict:
    cands = []
    for s in signals:
        if s.get("align") != "同向":
            continue
        lots = int(s.get("lots_raw") or s.get("lots_l1") or 0)
        if lots <= 0 or not s.get("close"):
            continue
        cands.append(
            {
                "code": s["code"],
                "direction": s.get("direction"),
                "lots": lots,
                "close": s.get("close"),
                "mult": s.get("mult"),
                "r20": s.get("r20"),
                "r60": s.get("r60"),
                "atr": s.get("atr"),
                "bucket": s.get("bucket"),
            }
        )
    selected, meta = apply_portfolio_caps(
        cands,
        equity=sizing_equity,
        max_positions=MAX_POSITIONS,
        max_gross_exposure_pct=MAX_GROSS_PCT,
        max_portfolio_risk_pct=MAX_PORT_RISK_PCT,
        max_per_bucket=MAX_PER_BUCKET,
        min_r20_pct=MIN_R20_PCT,
        min_r60_pct=MIN_R60_PCT,
    )
    by_code = {c["code"]: c for c in selected}
    weak = set(meta.get("weak_filtered") or [])
    bucket_skip = set(meta.get("bucket_skipped") or [])
    for s in signals:
        code = s.get("code")
        if code in by_code:
            lots = int(by_code[code]["lots"])
            s["lots_l1"] = lots
            s["lots_full"] = lots
            s["selected"] = True
            s["action"] = (
                f"路径A记账：记{s.get('direction')}{lots}手"
                f"（Top{MAX_POSITIONS}·名义≤{MAX_GROSS_PCT}%·风险≤{MAX_PORT_RISK_PCT}%·不下单）"
            )
        else:
            raw = int(s.get("lots_raw") or 0)
            if s.get("align") == "同向" and raw > 0:
                s["lots_l1"] = 0
                s["lots_full"] = 0
                s["selected"] = False
                if code in weak:
                    s["action"] = f"同向但动量不足（需|r20|≥{MIN_R20_PCT}%且|r60|≥{MIN_R60_PCT}%）"
                elif code in bucket_skip:
                    s["action"] = f"同板块已有更强信号（每板块最多{MAX_PER_BUCKET}个）"
                else:
                    s["action"] = (
                        f"有信号但未入选（限{MAX_POSITIONS}品种/"
                        f"名义≤{MAX_GROSS_PCT}%/风险≤{MAX_PORT_RISK_PCT}%）"
                    )
            else:
                s["selected"] = False
    return meta


def main():
    now = datetime.now(TZ)
    live, state = _load_live_equity(EQUITY_BASE)
    sizing_eq = compound_equity(live, EQUITY_BASE, EQUITY_COMPOUND)
    risk_budget = risk_budget_yuan(sizing_eq, RISK_PCT, L1_MULT)
    print(
        f"[cta] start {now.isoformat()} equity_base={EQUITY_BASE} live={live} "
        f"sizing={sizing_eq} compound={EQUITY_COMPOUND} risk={risk_budget} "
        f"max_pos={MAX_POSITIONS} gross≤{MAX_GROSS_PCT}% atr_risk≤{MAX_PORT_RISK_PCT}% "
        f"bucket≤{MAX_PER_BUCKET} min_r={MIN_R20_PCT}/{MIN_R60_PCT} ifind={active_slot()}"
    )
    if not is_weekday_cn():
        print("[cta] skip: weekend")
        out = {"asof": now.strftime("%Y%m%d"), "skipped": "weekend"}
        (ROOT / "l1_report_risk15.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0

    mode = _entry_mode()
    print(f"[cta] entry_filter={mode}")
    curves = load_curves([u["code"] for u in UNIVERSE])
    signals = []
    snaps = []
    for u in UNIVERSE:
        print(f"[cta] fetch {u['code']}...")
        try:
            snap = _fetch_snapshot(u, curves, mode)
            snaps.append(snap)
            sig = _signal(u, snap, risk_budget=risk_budget)
            if snap.get("block"):
                sig["block"] = snap["block"]
            signals.append(sig)
            print(
                f"  {u['code']} src={snap.get('source')} date={snap.get('bar_date')} "
                f"close={sig['close']} r20={sig['r20']} r60={sig['r60']} "
                f"atr={sig['atr']} lots={sig['lots_l1']} {sig['direction']}"
            )
        except Exception as e:
            signals.append(
                {
                    "code": u["code"],
                    "name": u["name"],
                    "error": str(e)[:300],
                    "lots_l1": 0,
                    "lots_raw": 0,
                    "selected": False,
                    "direction": "空仓",
                    "action": f"拉取失败: {e}",
                }
            )
            print(f"  ERR {u['code']}: {e}")
            snaps.append({})

    if mode == "member":
        days = sorted({s.get("prev_date") or s.get("bar_date") for s in snaps if s.get("bar_date")})
        member = load_member_changes(days, [u["code"] for u in UNIVERSE]) if days else {}
        for sig in signals:
            if sig.get("block") or sig.get("direction") not in ("多", "空"):
                continue
            reason = member_reason(sig["direction"], (member.get(sig["code"]) or {}).get(sig.get("bar_date")))
            if reason:
                sig["block"] = reason
    if mode == "climax":
        for sig in signals:
            if sig.get("block") or sig.get("direction") not in ("多", "空"):
                continue
            peers = [
                other.get("r20")
                for other in signals
                if other.get("code") != sig.get("code") and other.get("bucket") == sig.get("bucket")
            ]
            reason = bucket_reason(sig["direction"], [p for p in peers if p is not None])
            if reason:
                sig["block"] = reason
    for sig in signals:
        if sig.get("block"):
            sig["lots_raw"] = 0
            sig["lots_l1"] = 0
            sig["lots_full"] = 0
            sig["selected"] = False
            sig["action"] = sig["block"]

    port_meta = _apply_caps(signals, sizing_equity=sizing_eq)
    port_meta["sizing_equity"] = round(sizing_eq, 2)
    port_meta["equity_compound"] = EQUITY_COMPOUND
    print(
        f"[cta] portfolio selected={port_meta.get('selected')} "
        f"gross={port_meta.get('gross_after')} ({port_meta.get('gross_pct')}%) "
        f"atr_risk={port_meta.get('atr_risk_after')} ({port_meta.get('atr_risk_pct')}%) "
        f"scale={port_meta.get('scale')} weak={port_meta.get('weak_filtered')} "
        f"bucket_skip={port_meta.get('bucket_skipped')}"
    )

    report = {
        "asof": now.strftime("%Y%m%d"),
        "updated_at": now.isoformat(),
        "equity_base": EQUITY_BASE,
        "equity": sizing_eq,
        "equity_live": live,
        "equity_compound": EQUITY_COMPOUND,
        "risk_pct": RISK_PCT,
        "l1_mult": L1_MULT,
        "l1_risk_yuan": risk_budget,
        "max_positions": MAX_POSITIONS,
        "max_gross_exposure_pct": MAX_GROSS_PCT,
        "max_portfolio_risk_pct": MAX_PORT_RISK_PCT,
        "max_per_bucket": MAX_PER_BUCKET,
        "min_r20_pct": MIN_R20_PCT,
        "min_r60_pct": MIN_R60_PCT,
        "data_source": "sina+tencent primary, iFinD fallback",
        "entry_filter": mode,
        "ifind_calls": usage_report()["count"],
        "ifind_call_log": usage_report()["calls"],
        "ifind_slot": active_slot(),
        "portfolio": port_meta,
        "equity_state": {
            "asof": state.get("asof"),
            "source": state.get("source"),
            "peak": state.get("peak"),
        },
        "signals": signals,
    }
    path = ROOT / "l1_report_risk15.json"
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(blob, encoding="utf-8")
    (ROOT / "l1_report.json").write_text(blob, encoding="utf-8")
    arch = ROOT / "archive"
    arch.mkdir(exist_ok=True)
    (arch / f"l1_report_{report['asof']}.json").write_text(blob, encoding="utf-8")
    rep = usage_report()
    print(f"[ifind] calls={rep['count']}")
    print(f"[cta] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
