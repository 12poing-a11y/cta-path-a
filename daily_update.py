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
from member_rank import (  # noqa: E402
    ensure_member_days,
    ensure_universe_member_coverage,
    load_member_changes,
    load_member_seats,
)
from path_a_filters import (  # noqa: E402
    bucket_reason,
    carry_bypass_cfg,
    carry_bypass_decision,
    entry_block,
    member_reason,
    seat_decision,
)
from lab_signal import (  # noqa: E402
    lab_edge_bypass_cfg,
    lab_edge_decision,
    refresh_latest as refresh_lab_signals,
)
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
    sel = cfg.get("selection") or {}
    stop_atr_mult = float(sel.get("stop_atr_mult") or cfg.get("stop_atr_mult") or 1)
    reward_rr = float(sel.get("reward_rr") or cfg.get("reward_rr") or 2)
    symbols = cfg.get("symbols") or []
    observe = cfg.get("observe") if isinstance(cfg.get("observe"), dict) else {}
    observe_min_lots = int(observe.get("min_lots") or 0)
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
        stop_atr_mult,
        reward_rr,
        symbols,
        observe_min_lots,
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
    STOP_ATR_MULT,
    REWARD_RR,
    UNIVERSE,
    OBSERVE_MIN_LOTS,
) = _load_universe()
LIVE_EQUITY, _EQUITY_STATE = _load_live_equity(EQUITY_BASE)
EQUITY = compound_equity(LIVE_EQUITY, EQUITY_BASE, EQUITY_COMPOUND)
L1_RISK = risk_budget_yuan(EQUITY, RISK_PCT, L1_MULT)


def _universe_cfg() -> dict:
    return json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))


def _entry_mode() -> str:
    cfg = _universe_cfg()
    mode = cfg.get("entry_filter") or "base"
    if mode not in ("base", "p0", "carry", "oi", "member", "climax", "seats"):
        return "base"
    return mode


def _carry_bypass() -> dict:
    return carry_bypass_cfg(_universe_cfg().get("carry_bypass"))


def _lab_edge_bypass() -> dict:
    return lab_edge_bypass_cfg(_universe_cfg().get("lab_edge_bypass"))


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
    ret_1d = None
    try:
        c0 = float(hist[i - 1]["close"])
        c1 = float(hist[i]["close"])
        if c0 > 0:
            ret_1d = (c1 / c0) - 1.0
    except (TypeError, ValueError, KeyError, IndexError):
        ret_1d = None
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
        "ret_1d": round(ret_1d, 6) if ret_1d is not None else None,
        "volume": hist[i].get("volume"),
        "oi": hist[i].get("oi") or hist[i].get("open_interest"),
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
    stop_dist = (STOP_ATR_MULT * atr) if atr is not None else None
    risk_per_lot = (stop_dist * u["mult"]) if stop_dist is not None else None
    align = "冲突/不足"
    direction = "空仓"
    if r20 is not None and r60 is not None and r20 != 0 and r60 != 0:
        if (r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0):
            align = "同向"
            direction = "多" if r20 > 0 else "空"

    lots = 0
    stop = target = None
    sleeve = str(u.get("sleeve") or "").strip() or None
    min_lots_bumped = False
    if align == "同向" and risk_per_lot and risk_per_lot > 0 and close is not None and stop_dist is not None:
        lots = int(math.floor(risk_budget / risk_per_lot))
        if direction == "多":
            stop = close - stop_dist
            target = close + REWARD_RR * stop_dist
        else:
            stop = close + stop_dist
            target = close - REWARD_RR * stop_dist
        # Observe-sleeve metals: floor to observe.min_lots so high-margin names can enter paper book.
        if (
            sleeve == "observe"
            and OBSERVE_MIN_LOTS > 0
            and lots < OBSERVE_MIN_LOTS
            and atr is not None
            and atr > 0
            and atr < float(close) * 0.25
        ):
            lots = int(OBSERVE_MIN_LOTS)
            min_lots_bumped = True

    if align != "同向":
        action = "空仓（20日与60日不同向）"
    elif lots <= 0:
        action = f"有{direction}向，1.5%仍不足1手（每手约{risk_per_lot}）"
    elif min_lots_bumped:
        action = (
            f"候选：{direction}{lots}手（观察袖套抬至{OBSERVE_MIN_LOTS}手·"
            f"待门槛/板块/Top{MAX_POSITIONS}/"
            f"名义≤{MAX_GROSS_PCT}%/风险≤{MAX_PORT_RISK_PCT}%）"
        )
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
        "sleeve": sleeve,
        "date": today,
        "close": close,
        "atr": round(atr, 2) if atr is not None else None,
        "risk_per_lot": round(risk_per_lot, 1) if risk_per_lot is not None else None,
        "stop_atr_mult": STOP_ATR_MULT,
        "reward_rr": REWARD_RR,
        "stop": round(stop, 4) if stop is not None else None,
        "target": round(target, 4) if target is not None else None,
        "r20": r20,
        "r60": r60,
        "ret_1d": snap.get("ret_1d"),
        "volume": snap.get("volume"),
        "oi": snap.get("oi"),
        "align": align,
        "direction": direction if align == "同向" else "空仓",
        "lots_raw": lots,
        "min_lots_bumped": min_lots_bumped,
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
            sleeve_note = "·观察袖套" if s.get("sleeve") == "observe" else ""
            bump_note = "·已抬min_lots" if s.get("min_lots_bumped") else ""
            s["action"] = (
                f"路径A记账：记{s.get('direction')}{lots}手"
                f" 止损{s.get('stop')} 止盈{s.get('target')}"
                f"（止损{STOP_ATR_MULT:g}×ATR·盈亏比{REWARD_RR:g}·"
                f"Top{MAX_POSITIONS}·名义≤{MAX_GROSS_PCT}%·风险≤{MAX_PORT_RISK_PCT}%"
                f"{sleeve_note}{bump_note}·不下单）"
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
    bypass = _carry_bypass()
    lab_bypass = _lab_edge_bypass()
    print(
        f"[cta] entry_filter={mode} carry_bypass={bypass.get('enabled')} "
        f"lab_edge={lab_bypass.get('enabled')}"
    )
    lab_pack = {}
    if lab_bypass.get("enabled"):
        try:
            lab_pack = refresh_lab_signals(root=ROOT, cfg=lab_bypass)
            print(
                f"[cta] lab_edge date={lab_pack.get('panel_date')} "
                f"ok={lab_pack.get('ok')} n={lab_pack.get('n_codes')}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[cta] lab_edge refresh soft-fail: {exc}")
            lab_pack = {}
    need_curves = mode not in ("base", "seats") or bool(bypass.get("enabled"))
    curves = load_curves([u["code"] for u in UNIVERSE]) if need_curves else {}
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

    observe_coverage: dict = {
        "complete": False,
        "bars_ok": [],
        "bars_missing": [],
        "seats_ok": [],
        "seats_missing": [],
        "seat_fill": {},
    }
    bar_ok = [s["code"] for s in signals if s.get("bar_date") and not str(s.get("error") or "")]
    bar_miss = [u["code"] for u in UNIVERSE if u["code"] not in set(bar_ok)]
    observe_coverage["bars_ok"] = bar_ok
    observe_coverage["bars_missing"] = bar_miss

    # Observation sample: all 20 must have seats — exchange → 东财 → 新浪.
    # Short lookback densifies DCE/EM so 席位页 is not stuck on 2–3 sparse days.
    seat_days = sorted({s.get("bar_date") for s in snaps if s.get("bar_date")})
    if seat_days:
        try:
            from member_rank import backfill_member_lookback

            end_ymd = str(seat_days[-1]).replace("-", "")[:8]
            bf = backfill_member_lookback(
                lookback_calendar_days=10,
                end=end_ymd,
                dce=True,
                coverage=False,
            )
            print(
                f"  [observe] member lookback days={bf.get('days')} "
                f"shfe={bf.get('shfe')} czce={bf.get('czce')} "
                f"dce={bf.get('dce')} em={bf.get('eastmoney', 0)}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [observe] member lookback soft-fail: {exc}")
            stats = ensure_member_days(seat_days, dce=True)
            print(
                f"  [observe] member ensure days={stats['days']} "
                f"shfe={stats['shfe']} czce={stats['czce']} "
                f"dce={stats['dce']} em={stats.get('eastmoney', 0)}"
            )
        cov = ensure_universe_member_coverage(seat_days[-1], [u["code"] for u in UNIVERSE])
        observe_coverage["seats_ok"] = cov.get("ok") or []
        observe_coverage["seats_missing"] = cov.get("missing") or []
        observe_coverage["seat_fill"] = cov.get("filled") or {}
        observe_coverage["seat_ymd"] = cov.get("ymd")
        print(
            f"  [observe] seats {cov.get('n_ok')}/{cov.get('n_codes')} "
            f"missing={cov.get('missing')} filled={cov.get('filled')}"
        )
    else:
        observe_coverage["seats_missing"] = [u["code"] for u in UNIVERSE]

    if mode == "member":
        days = sorted({s.get("prev_date") or s.get("bar_date") for s in snaps if s.get("bar_date")})
        member = load_member_changes(days, [u["code"] for u in UNIVERSE]) if days else {}
        for sig in signals:
            if sig.get("block") or sig.get("direction") not in ("多", "空"):
                continue
            reason = member_reason(sig["direction"], (member.get(sig["code"]) or {}).get(sig.get("bar_date")))
            if reason:
                sig["block"] = reason
    if mode == "seats":
        days = seat_days
        seats = load_member_seats(days, [u["code"] for u in UNIVERSE]) if days else {}
        for sig in signals:
            if sig.get("direction") not in ("多", "空"):
                continue
            reason, label = seat_decision(
                sig["direction"], (seats.get(sig["code"]) or {}).get(sig.get("bar_date"))
            )
            sig["seat"] = label
            if reason and not sig.get("block"):
                sig["block"] = reason
    observe_coverage["complete"] = (
        not observe_coverage["bars_missing"] and not observe_coverage["seats_missing"]
    )
    if not observe_coverage["complete"]:
        print(
            f"[cta] OBSERVE INCOMPLETE bars_missing={observe_coverage['bars_missing']} "
            f"seats_missing={observe_coverage['seats_missing']}"
        )

    # Batch 15m/60m into .cache/akshare/minute (CI commits; local desk git pull).
    minute_summary: dict = {"ok": 0, "fail": 0, "periods": ["15", "60"], "rows": []}
    try:
        from minute_data import refresh_universe_minutes

        print("[cta] refresh minute 15/60...")
        minute_summary = refresh_universe_minutes(
            ROOT,
            [u["code"] for u in UNIVERSE],
            periods=("15", "60"),
            force=True,
            verify_em=False,
        )
        print(
            f"[cta] minute ok={minute_summary.get('ok')} fail={minute_summary.get('fail')}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[cta] minute soft-fail: {exc}")
        minute_summary = {
            "ok": 0,
            "fail": len(UNIVERSE) * 2,
            "periods": ["15", "60"],
            "error": str(exc)[:300],
            "rows": [],
        }
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
    # Soft carry extreme bypass: after seats/entry_filter; missing gap does not block.
    if bypass.get("enabled"):
        for sig in signals:
            if sig.get("direction") not in ("多", "空"):
                continue
            day = sig.get("bar_date") or sig.get("date")
            pair = ((curves.get(sig["code"]) or {}).get("carry") or {}).get(day)
            reason, mult, label, gap = carry_bypass_decision(
                sig["direction"],
                pair,
                extreme_gap_pct=float(bypass["extreme_gap_pct"]),
                action=str(bypass["action"]),
                scale=float(bypass["scale"]),
            )
            sig["carry_gap_pct"] = None if gap is None else round(gap, 4)
            sig["carry_bypass"] = label
            if reason and not sig.get("block"):
                sig["block"] = reason
            elif not sig.get("block") and mult < 1.0 and mult > 0:
                for key in ("lots_raw", "lots_l1", "lots_full"):
                    if sig.get(key):
                        sig[key] = int(math.floor(float(sig[key]) * mult))
                sig["carry_scale"] = mult
                if int(sig.get("lots_l1") or 0) <= 0:
                    sig["block"] = f"{label}后不足1手"
    # Lab edge: annotate only under action=observe (decision page vetoes).
    # action=block also tags block reason but does not replace seats filter alone.
    if lab_bypass.get("enabled"):
        from lab_signal import load_latest_pack

        pack = load_latest_pack(ROOT) if not lab_pack.get("scores") else {
            "ok": bool(lab_pack.get("ok")),
            "date": lab_pack.get("panel_date"),
            "n_codes": lab_pack.get("n_codes") or 0,
            "scores": lab_pack.get("scores") or {},
            "percentiles": lab_pack.get("percentiles") or {},
            "members": lab_pack.get("members") or [],
            "reason": lab_pack.get("reason"),
        }
        for sig in signals:
            if sig.get("direction") not in ("多", "空"):
                continue
            edge = lab_edge_decision(sig["direction"], sig["code"], pack, lab_bypass)
            sig["lab_edge"] = edge.get("label")
            sig["lab_score"] = edge.get("score")
            sig["lab_pct"] = edge.get("percentile")
            if (
                lab_bypass.get("action") == "block"
                and edge.get("block")
                and not sig.get("block")
            ):
                sig["block"] = edge["block"]
    for sig in signals:
        if sig.get("block"):
            sig["lots_raw"] = 0
            sig["lots_l1"] = 0
            sig["lots_full"] = 0
            sig["selected"] = False
            sig["action"] = sig["block"]

    # Re-apply observe min_lots after seats/carry/lab blocks (high-margin metals).
    for sig in signals:
        if sig.get("block") or sig.get("sleeve") != "observe":
            continue
        if sig.get("align") != "同向" or sig.get("direction") not in ("多", "空"):
            continue
        if OBSERVE_MIN_LOTS <= 0:
            continue
        atr = sig.get("atr")
        close = sig.get("close")
        try:
            atr_f = float(atr) if atr is not None else 0.0
            close_f = float(close) if close is not None else 0.0
        except (TypeError, ValueError):
            continue
        if atr_f <= 0 or close_f <= 0 or atr_f >= close_f * 0.25:
            continue
        lots = int(sig.get("lots_raw") or 0)
        if lots < OBSERVE_MIN_LOTS:
            sig["lots_raw"] = int(OBSERVE_MIN_LOTS)
            sig["lots_l1"] = int(OBSERVE_MIN_LOTS)
            sig["lots_full"] = int(OBSERVE_MIN_LOTS)
            sig["min_lots_bumped"] = True
            if not str(sig.get("action") or "").startswith("路径A"):
                sig["action"] = (
                    f"候选：{sig.get('direction')}{OBSERVE_MIN_LOTS}手"
                    f"（观察袖套抬至{OBSERVE_MIN_LOTS}手·待组合帽）"
                )

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

    asof_ymd = now.strftime("%Y%m%d")
    from research_quality import validate_signals

    quality = validate_signals(signals, asof=asof_ymd)
    if not quality.get("ok"):
        print(
            f"[cta] QUALITY GATE FAIL bad={quality.get('bad_codes')} "
            f"failures={quality.get('failures')[:12]}"
        )
        for sig in signals:
            sig["selected"] = False
            sig["lots_l1"] = 0
            sig["lots_raw"] = 0
            sig["lots_full"] = 0
            if not str(sig.get("action") or "").startswith("质量门禁"):
                sig["action"] = f"质量门禁阻断: {','.join(quality.get('bad_codes') or [])}"
        port_meta["selected"] = []
        port_meta["quality_blocked"] = True
    else:
        print(
            f"[cta] quality ok checked={quality.get('checked')} "
            f"bad_n={quality.get('bad_n')}"
        )

    # Paper-only MDS+EHI sentiment sleeve (ChatGPT share); never sizes Path-A lots.
    sentiment_meta: dict = {"ok": False}
    try:
        from sentiment_mds import build_snapshot, write_snapshot

        seat_rows = []
        seats_book = {}
        if seat_days:
            seats_book = load_member_seats(seat_days[-1:], [u["code"] for u in UNIVERSE])
        day_key = seat_days[-1] if seat_days else None
        for sig in signals:
            code = str(sig.get("code") or "").upper()
            book = (seats_book.get(code) or {}).get(day_key) if day_key else None
            net = float((book or {}).get("inst") or 0.0) if book else 0.0
            seat_rows.append(
                {
                    "code": code,
                    "net": net,
                    "net_chg": net,
                    "ret_1d": sig.get("ret_1d"),
                    "oi": sig.get("oi"),
                    "volume": sig.get("volume"),
                }
            )
        snap_sent = build_snapshot(seat_rows, asof=asof_ymd)
        sent_path = write_snapshot(snap_sent)
        sentiment_meta = {
            "ok": True,
            "path": str(sent_path.name),
            "stance": snap_sent.get("stance"),
            "portfolio_p3": snap_sent.get("portfolio_p3"),
            "longs": snap_sent.get("longs"),
            "shorts": snap_sent.get("shorts"),
            "live": False,
        }
        print(
            f"[sentiment] paper MDS+EHI stance={snap_sent.get('stance')} "
            f"p3={snap_sent.get('portfolio_p3')} n={snap_sent.get('n')}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[sentiment] soft-fail: {exc}")
        sentiment_meta = {"ok": False, "error": str(exc)[:300], "live": False}

    report = {
        "asof": asof_ymd,
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
        "data_source": "bars=sina+tencent→iFinD; seats=eastmoney→sina (exchange soft)",
        "entry_filter": mode,
        "carry_bypass": bypass,
        "lab_edge_bypass": lab_bypass,
        "observe_coverage": observe_coverage,
        "observe_min_lots": OBSERVE_MIN_LOTS,
        "observe_sleeve_codes": [
            str(u.get("code") or "").upper()
            for u in UNIVERSE
            if str(u.get("sleeve") or "") == "observe"
        ],
        "min_lots_bumped": [
            s.get("code") for s in signals if s.get("min_lots_bumped")
        ],
        "minute_summary": {
            "ok": minute_summary.get("ok"),
            "fail": minute_summary.get("fail"),
            "periods": minute_summary.get("periods"),
            "error": minute_summary.get("error"),
        },
        "quality": quality,
        "quality_ok": bool(quality.get("ok")),
        "sentiment_mds": sentiment_meta,
        "live_trading": False,
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
    # Formal report only when quality passes; otherwise write quarantine artifact.
    arch = ROOT / "archive"
    arch.mkdir(exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if quality.get("ok"):
        path = ROOT / "l1_report_risk15.json"
        path.write_text(blob, encoding="utf-8")
        (ROOT / "l1_report.json").write_text(blob, encoding="utf-8")
        (arch / f"l1_report_{report['asof']}.json").write_text(blob, encoding="utf-8")
        print(f"[cta] wrote {path}")
    else:
        qpath = ROOT / "l1_report_quality_failed.json"
        qpath.write_text(blob, encoding="utf-8")
        (arch / f"l1_report_quality_failed_{report['asof']}.json").write_text(
            blob, encoding="utf-8"
        )
        print(f"[cta] QUALITY: formal report withheld; wrote {qpath}")
    rep = usage_report()
    print(f"[ifind] calls={rep['count']}")
    if observe_coverage.get("complete"):
        print(
            f"[cta] observe coverage OK "
            f"bars={len(observe_coverage.get('bars_ok') or [])} "
            f"seats={len(observe_coverage.get('seats_ok') or [])}"
        )
    if quality.get("ok"):
        try:
            from paper_book import refresh_paper_book

            paper = refresh_paper_book(ROOT, report=report)
            if paper.get("ok"):
                print(
                    f"[paper] asof={paper.get('asof')} held={paper.get('held_n')} "
                    f"opened={paper.get('opened_n')} closed={paper.get('closed_n')}"
                )
            else:
                print("[paper] skip:", paper.get("error"))
        except Exception as exc:
            print(f"[paper] refresh failed: {exc}")
    else:
        print("[paper] skip: quality gate failed")
    # Observation incomplete or quality fail → non-zero so CI does not publish formal.
    if not quality.get("ok"):
        return 3
    return 0 if observe_coverage.get("complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
