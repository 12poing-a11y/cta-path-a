# -*- coding: utf-8 -*-
"""CTA L1 Path-A daily paper update. Sina/Tencent bars, iFinD only if those are short."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
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
from vol_factor_combo import vol_bypass_cfg  # noqa: E402
from position_rules import (  # noqa: E402
    apply_portfolio_caps,
    book_usage_from_positions,
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


def _vol_bypass() -> dict:
    return vol_bypass_cfg(_universe_cfg().get("vol_bypass"))


def _lab_edge_bypass() -> dict:
    return lab_edge_bypass_cfg(_universe_cfg().get("lab_edge_bypass"))


def _fetch_snapshot(u: dict, curves: dict, mode: str) -> dict:
    """LEGACY (pre-R5a) snapshot: raw continuous series, 120 bars.  Kept only for the
    ``--signal-path legacy`` comparison; the daily report uses ``compute_signals`` (signal_core)."""
    from historical_backtest import fetch_history

    hist, meta = fetch_history(u, n=120)
    return _snapshot_from_hist(u, hist, meta, curves, mode)


def _snapshot_from_hist(u: dict, hist: list, meta: dict, curves: dict, mode: str) -> dict:
    """LEGACY r20/r60/ATR on the raw continuous bars (roll spreads included)."""
    from historical_backtest import atr14, ret_n

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
        "tqsdk": meta.get("tqsdk"),
        "tqsdk_n": meta.get("tqsdk_n"),
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
        # daily_update derives signals from Sina/Tencent main continuous series,
        # not an executable delivery-month contract quote.
        "price_basis": "continuous",
        "bar_date": snap.get("bar_date"),
        "lots_l1": lots,
        "lots_full": lots,
        "selected": False,
        "action": action,
    }


def _hist_ret_1d(hist: list) -> float | None:
    try:
        c0 = float(hist[-2]["close"])
        c1 = float(hist[-1]["close"])
        return (c1 / c0) - 1.0 if c0 > 0 else None
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def _signal_from_core(u: dict, hist: list, res: dict, *, data_source, observe_min_lots: int) -> dict:
    """Report row for one code from ``signal_core.path_a_candidate`` (R5a)."""
    i = len(hist) - 1
    close = hist[i]["close"]
    aligned = bool(res["aligned"])
    direction = res["direction"] if aligned else "空仓"
    sz = res.get("sizing")
    lots = int(sz["lots"]) if sz is not None else 0
    bumped = bool(sz["min_lots_bumped"]) if sz is not None else False
    stop = sz["stop"] if sz is not None else None
    target = sz["target"] if sz is not None else None
    risk_per_lot = sz["risk_per_lot"] if sz is not None else None
    r20, r60, atr = res["r20"], res["r60"], res["atr"]
    if not aligned:
        action = "空仓（20日与60日不同向）"
    elif lots <= 0:
        action = f"有{direction}向，1.5%仍不足1手（每手约{round(risk_per_lot, 1) if risk_per_lot is not None else None}）"
    elif bumped:
        action = (
            f"候选：{direction}{lots}手（观察袖套抬至{observe_min_lots}手·"
            f"待门槛/板块/Top{MAX_POSITIONS}/"
            f"名义≤{MAX_GROSS_PCT}%/风险≤{MAX_PORT_RISK_PCT}%）"
        )
    else:
        action = (
            f"候选：{direction}{lots}手（待门槛/板块/Top{MAX_POSITIONS}/"
            f"名义≤{MAX_GROSS_PCT}%/风险≤{MAX_PORT_RISK_PCT}%）"
        )
    sig = {
        "code": u["code"],
        "name": u["name"],
        "ticker": u["ticker"],
        "bucket": u["bucket"],
        "mult": u["mult"],
        "sleeve": str(u.get("sleeve") or "").strip() or None,
        "date": datetime.now(TZ).strftime("%Y%m%d"),
        "close": close,
        "atr": round(atr, 2) if atr is not None else None,
        "risk_per_lot": round(risk_per_lot, 1) if risk_per_lot is not None else None,
        "stop_atr_mult": STOP_ATR_MULT,
        "reward_rr": REWARD_RR,
        "stop": round(stop, 4) if stop is not None else None,
        "target": round(target, 4) if target is not None else None,
        # R5a: unrounded ATR distances (what the backtest sizes with)
        "stop_dist": sz["stop_dist"] if sz is not None else None,
        "target_dist": sz["target_dist"] if sz is not None else None,
        "r20": round(r20, 3) if r20 is not None else None,
        "r60": round(r60, 3) if r60 is not None else None,
        "ret_1d": None,
        "volume": hist[i].get("volume"),
        "oi": hist[i].get("oi") or hist[i].get("open_interest"),
        "align": "同向" if aligned else "冲突/不足",
        "direction": direction if aligned else "空仓",
        "lots_raw": lots,
        "min_lots_bumped": bumped,
        "data_source": data_source,
        "price_basis": "continuous",
        "bar_date": hist[i]["date"],
        "lots_l1": lots,
        "lots_full": lots,
        "selected": False,
        "action": action,
        "signal_path": "signal_core",
        "core_status": res["status"],
    }
    r1 = _hist_ret_1d(hist)
    sig["ret_1d"] = round(r1, 6) if r1 is not None else None
    if res.get("seat_label") is not None:
        sig["seat"] = res["seat_label"]
    if res.get("seat_short"):
        sig["seat_short"] = True
    cy = res.get("carry")
    if cy is not None:
        gap = cy.get("gap_pct")
        sig["carry_gap_pct"] = None if gap is None else round(gap, 4)
        sig["carry_bypass"] = cy.get("label")
        if cy.get("mult") is not None and 0 < cy["mult"] < 1.0 and not cy.get("reason"):
            sig["carry_scale"] = cy["mult"]
            if res["status"] == "lots0":
                sig["block"] = f"{cy.get('label')}后不足1手"
    if res.get("blocked"):
        sig["block"] = res["blocked"]
        sig["block_kind"] = res.get("block_kind")
    if res.get("vol_reason"):
        sig["vol_block"] = res["vol_reason"]
    return sig


def compute_signals(
    universe: list[dict],
    bars: dict[str, list],
    *,
    mode: str,
    bypass: dict,
    vbypass: dict,
    curves: dict | None,
    member_loader=None,
    risk_budget: float,
    lag: int | None = None,
    contract_root=None,
    min_seat_days: int | None = None,
    observe_min_lots: int | None = None,
    errors: dict[str, str] | None = None,
    data_sources: dict[str, str] | None = None,
    day: str | None = None,
    inputs: tuple | None = None,
) -> tuple[list[dict], dict]:
    """Today's Path-A report rows, computed by the SAME code as ``historical_backtest.simulate``.

    * r20 / r60 / ATR / vol come from the roll-free series (``main_map`` + ``adjusted``) built on
      the injected ``bars`` and the contract store ``contract_root`` (a cache root or a
      ``ContractStore``, e.g. a snapshot bundle cut at ``day``; no network here);
    * seats / carry books are lagged by ``lag`` sessions exactly like the backtest
      (``lag_member`` / ``lag_curves_carry`` over the covered session dates);
    * the filter order, stop / target distance and lots formula live in ``signal_core``.
    ``curves`` is the raw (un-lagged) curve book ``{code: {"carry": {day: pair}}}``; ``member_loader(dates, codes)``
    returns the raw seat book ``{code: {day: {inst, foreign, holder}}}`` (member-change book for mode ``member``).
    ``day`` (R5b): the session being signalled — peers without a bar on ``day`` are left out (as in
    simulate); ``inputs`` = prebuilt ``(main_map, adj)`` for these bars (shared with the paper engine).
    """
    import bisect

    import historical_backtest as hb
    from signal_core import build_signal_inputs, covered_dates, path_a_candidate

    from research.data_quality.contract_store import ContractStore

    root = contract_root if isinstance(contract_root, ContractStore) else (Path(contract_root) if contract_root else ROOT)
    lag = hb.DEFAULT_AVAILABILITY_LAG if lag is None else int(lag)
    min_seat_days = hb.MIN_SEAT_DAYS if min_seat_days is None else int(min_seat_days)
    omin = int(OBSERVE_MIN_LOTS if observe_min_lots is None else observe_min_lots)
    series = {u["code"]: {"meta": dict(u), "hist": bars[u["code"]]} for u in universe if bars.get(u["code"])}
    dates = covered_dates(series)
    if len(dates) < hb.WARMUP + 5:
        from collections import Counter

        hits = Counter(h["date"] for s in series.values() for h in s["hist"])
        dates = sorted(hits)[-hb.LOOKBACK_DAYS :]
    main_map, adj = inputs if inputs is not None else build_signal_inputs(series, root=root)
    curves_l = hb.lag_curves_carry(curves or {}, dates, lag)
    member_raw = member_loader(dates, [c for c in series]) if member_loader is not None else {}
    member_l = hb.lag_member(member_raw or {}, dates, lag)
    seat_dates = {
        c: sorted(str(k) for k, v in (m or {}).items() if isinstance(v, dict)) for c, m in member_l.items()
    }

    def _seat_days_upto(code_: str, day_: str) -> int:
        return bisect.bisect_right(seat_dates.get(code_) or [], str(day_))

    signals: list[dict] = []
    info: dict = {"dates_n": len(dates), "adj_fallback_codes": [], "main_map_none_last_day": [], "core": {}}
    for u in universe:
        code = u["code"]
        hist = bars.get(code)
        if not hist:
            signals.append(
                {
                    "code": code,
                    "name": u["name"],
                    "error": str((errors or {}).get(code) or "no bars")[:300],
                    "lots_l1": 0,
                    "lots_raw": 0,
                    "selected": False,
                    "direction": "空仓",
                    "action": f"拉取失败: {(errors or {}).get(code) or 'no bars'}",
                }
            )
            continue
        i = len(hist) - 1
        sleeve = str(u.get("sleeve") or "").strip()

        def _peers(code=code):
            out = []
            for oc, os_ in series.items():
                if oc == code or os_["meta"].get("bucket") != u.get("bucket"):
                    continue
                if day is not None and os_["hist"][-1]["date"] != day:
                    continue
                a_ = adj.get(oc)
                oi = len(os_["hist"]) - 1
                out.append(a_.ret_n(oi, 20) if a_ is not None else hb.ret_n(os_["hist"], oi, 20))
            return [p for p in out if p is not None]

        res = path_a_candidate(
            code,
            hist,
            i,
            adj=adj.get(code),
            meta=u,
            params={
                "mode": mode,
                "min_r20": MIN_R20_PCT,
                "min_r60": MIN_R60_PCT,
                "stop_atr_mult": STOP_ATR_MULT,
                "reward_rr": REWARD_RR,
                "day_risk": risk_budget,
                "min_lots": omin if sleeve == "observe" else 0,
                "min_lots_guard_frac": 0.25,
                "bypass": bypass,
                "vbypass": vbypass,
            },
            ctx={
                "day": hist[i]["date"],
                "curves": curves_l,
                "member": member_l,
                "min_seat_days": min_seat_days,
                "seat_days_upto": _seat_days_upto,
                "peer_r20_fn": _peers,
            },
            composite_trend_fn=hb.composite_trend,
        )
        info["core"][code] = res
        sig = _signal_from_core(
            u, hist, res, data_source=(data_sources or {}).get(code), observe_min_lots=omin
        )
        a_ = adj.get(code)
        if a_ is not None:
            lo = max(1, i - 59)
            fb = sum(1 for j in range(lo, i + 1) if a_.fallback[j])
            rl = sum(1 for j in range(lo, i + 1) if a_.roll[j])
            sig["adj_fallback"] = fb > 0
            sig["adj_fallback_days_60"] = fb
            sig["adj_roll_days_60"] = rl
            sig["adj_last_day_fallback"] = bool(a_.fallback[i])
            sig["adj_note"] = (
                f"本日信号含换月价差（近60日有{fb}天缺主力合约日线，该品种按原始连续序列计算）" if fb > 0 else None
            )
            if fb > 0:
                info["adj_fallback_codes"].append(code)
        if main_map.main(code, hist[i]["date"]) is None:
            info["main_map_none_last_day"].append(code)
        signals.append(sig)
    info["main_map_usable"] = {c: main_map.usable(c) for c in series}
    return signals, info


def _liquid_listed(code: str, day: str, n: int = 6) -> list[str]:
    """Listed contracts on ``day`` in the liquid curve months (``public_curve.MONTHS``), nearest ``n``.
    Sina's main often sits beyond the three calendar-nearest months (MA main 2609 vs near month 2605)."""
    from public_curve import MONTHS
    from research.data_quality.calendar import listed_contracts_on

    months = set(MONTHS.get(str(code).upper(), range(1, 13)))
    return [c for c in listed_contracts_on(code, day) if int(c[-2:]) in months][:n]


def _ensure_contracts(universe: list[dict], bars: dict[str, list], *, root=None) -> dict:
    """R5a: make sure the contract daily files behind today's ``main_map`` exist (see
    ``research.data_quality.contract_cache``).  Returns request / timing statistics."""
    from research.data_quality.contract_cache import ensure_contract_bars
    from research.data_quality.main_map import build_main_map

    root = root or _contract_source()
    series = {u["code"]: {"meta": dict(u), "hist": bars[u["code"]]} for u in universe if bars.get(u["code"])}
    try:
        prelim = build_main_map(series, root=root)
    except Exception as exc:  # noqa: BLE001
        prelim = None
        print(f"[contracts] prelim main_map soft-fail: {exc}")
    stats = {"requests": 0, "seconds": 0.0, "fetched": [], "failed": [], "cached_n": 0, "codes": {}}
    for code, pack in series.items():
        hist = pack["hist"]
        upto = str(hist[-1]["date"])[:10]
        prev_main = None
        if prelim is not None:
            for b in reversed(hist[:-1]):
                m = prelim.main(code, str(b["date"])[:10])
                if m:
                    prev_main = m
                    break
        try:
            r = ensure_contract_bars(code, upto, root, prev_main=prev_main, extra=_liquid_listed(code, upto))
        except Exception as exc:  # noqa: BLE001
            r = {"requests": 0, "seconds": 0.0, "fetched": [], "failed": [{"error": str(exc)[:120]}], "cached": []}
        stats["requests"] += int(r.get("requests") or 0)
        stats["seconds"] += float(r.get("seconds") or 0.0)
        stats["fetched"] += r.get("fetched") or []
        stats["failed"] += [dict(f, code=code) for f in (r.get("failed") or [])]
        stats["cached_n"] += len(r.get("cached") or [])
        stats["codes"][code] = {k: r.get(k) for k in ("wanted", "fetched", "requests", "seconds")}
    stats["seconds"] = round(stats["seconds"], 3)
    return stats


def _legacy_postfilters(
    signals: list[dict], snaps: list[dict], *, mode: str, bypass: dict, curves: dict, seat_days: list[str]
) -> None:
    """LEGACY (pre-R5a) member / seats / climax / carry / observe-floor passes on the raw rows.
    Seat and carry books are NOT lagged here (same-day), unlike the backtest."""
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
        seats = load_member_seats(seat_days, [u["code"] for u in UNIVERSE]) if seat_days else {}
        for sig in signals:
            if sig.get("direction") not in ("多", "空"):
                continue
            reason, label = seat_decision(
                sig["direction"], (seats.get(sig["code"]) or {}).get(sig.get("bar_date"))
            )
            sig["seat"] = label
            if reason and not sig.get("block"):
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
    for sig in signals:
        if sig.get("block"):
            sig["lots_raw"] = 0
            sig["lots_l1"] = 0
            sig["lots_full"] = 0
    # observe min_lots re-applied after the blocks
    for sig in signals:
        if sig.get("block") or sig.get("sleeve") != "observe":
            continue
        if sig.get("align") != "同向" or sig.get("direction") not in ("多", "空"):
            continue
        if OBSERVE_MIN_LOTS <= 0:
            continue
        try:
            atr_f = float(sig.get("atr") or 0.0)
            close_f = float(sig.get("close") or 0.0)
        except (TypeError, ValueError):
            continue
        if atr_f <= 0 or close_f <= 0 or atr_f >= close_f * 0.25:
            continue
        if int(sig.get("lots_raw") or 0) < OBSERVE_MIN_LOTS:
            sig["lots_raw"] = sig["lots_l1"] = sig["lots_full"] = int(OBSERVE_MIN_LOTS)
            sig["min_lots_bumped"] = True


def is_weekday_cn() -> bool:
    return datetime.now(TZ).weekday() < 5


def _load_paper_held() -> dict | None:
    """Read-only: open positions of ``paper_book_latest.json`` (None when absent / not ok).

    The daily report runs BEFORE ``refresh_paper_book``, so this book still contains
    positions that today's refresh may close — the quota it blocks is conservative."""
    try:
        path = ROOT / "paper_book_latest.json"
        if not path.is_file():
            return None
        book = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(book, dict) or not book.get("ok"):
        return None
    pos = book.get("positions")
    return pos if isinstance(pos, dict) else None


def _caps_on_rows(signals: list[dict], *, sizing_equity: float, held: dict | None) -> tuple[list[dict], dict]:
    """Legacy caps (book = ``paper_book_latest.json`` positions as of the previous run)."""
    held_codes: set[str] = set(held or {})
    held_book = held is not None
    if held_book:
        sig_close = {str(s.get("code")): s.get("close") for s in signals if s.get("close")}
        sig_atr = {str(s.get("code")): s.get("atr") for s in signals if s.get("atr")}
        used_g, used_r, held_buckets = book_usage_from_positions(
            held, price_by_code=sig_close, atr_by_code=sig_atr
        )
        eq_ = float(sizing_equity) if float(sizing_equity) > 0 else 1.0
        gross_cap_pct = max(0.0, float(MAX_GROSS_PCT) - used_g / eq_ * 100.0)
        risk_cap_pct = max(0.0, float(MAX_PORT_RISK_PCT) - used_r / eq_ * 100.0)
        max_pos = max(0, int(MAX_POSITIONS) - len(held_codes))
    else:
        held_buckets = None
        gross_cap_pct = MAX_GROSS_PCT
        risk_cap_pct = MAX_PORT_RISK_PCT
        max_pos = MAX_POSITIONS
    cands = []
    for s in signals:
        if s.get("align") != "同向":
            continue
        if held_book and str(s.get("code")) in held_codes:
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
    caps_kw: dict = {}
    if held_book:
        caps_kw["existing_buckets"] = held_buckets
    selected, meta = apply_portfolio_caps(
        cands,
        equity=sizing_equity,
        max_positions=max_pos,
        max_gross_exposure_pct=gross_cap_pct,
        max_portfolio_risk_pct=risk_cap_pct,
        max_per_bucket=MAX_PER_BUCKET,
        min_r20_pct=MIN_R20_PCT,
        min_r60_pct=MIN_R60_PCT,
        **caps_kw,
    )
    if held_book:
        meta["held_book"] = {
            "held_n": len(held_codes),
            "used_gross_pct": round(used_g / eq_ * 100.0, 2),
            "used_atr_risk_pct": round(used_r / eq_ * 100.0, 2),
            "gross_left_pct": round(gross_cap_pct, 2),
            "risk_left_pct": round(risk_cap_pct, 2),
            "held_buckets": held_buckets,
            "note": "日报先于 refresh_paper_book 运行；held 含当天可能平掉的仓位，偏保守（旧格式账本；R5b 引擎账本按回测同序）",
        }
    return selected, meta


def _apply_caps(
    signals: list[dict], *, sizing_equity: float, held: dict | None = None, engine_pick: tuple | None = None
) -> dict:
    """Portfolio caps for today's candidates.

    ``held`` (R4): open book (``paper_book_latest.json`` positions, read-only).  Its notional /
    ATR risk is deducted from the gross / risk budget, its sectors from the bucket cap and its
    count from the position cap; held codes do not compete as new candidates.
    ``held=None`` keeps the original behaviour exactly.
    ``engine_pick`` (R5b) = ``(selected, meta)`` from ``paper_book.plan_entries`` (caps already applied
    on the book after today's exits); only the report rows are labelled here."""
    held_codes: set[str] = set(held or {})
    held_book = held is not None
    if engine_pick is not None:
        selected = [dict(c) for c in engine_pick[0]]
        meta = dict(engine_pick[1])
    else:
        selected, meta = _caps_on_rows(signals, sizing_equity=sizing_equity, held=held)
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
                if held_book and code in held_codes:
                    s["action"] = "已在模拟账本持仓（占用组合额度，不重复开仓）"
                elif code in weak:
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



def _member_loader(mode: str):
    """Raw (un-lagged) member books over the window dates, same loaders as ``simulate``."""

    def _load(dates: list[str], codes: list[str]) -> dict:
        if mode == "member":
            return load_member_changes(dates, codes)
        if mode in ("seats", "roll"):
            return load_member_seats(dates, codes)
        return {}

    return _load


_CONTRACT_SOURCE = None  # R7a-D: --contract-bundle store (None = the local cache under ROOT)


def _contract_source():
    return _CONTRACT_SOURCE if _CONTRACT_SOURCE is not None else ROOT


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Daily Path-A report")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="compute the report only: no root l1_report*.json / archive / paper_book / Notion / minute / desk / IV / sentiment writes",
    )
    ap.add_argument("--out", default=None, help="with --dry-run: write the report JSON here")
    ap.add_argument(
        "--signal-path",
        choices=("core", "legacy"),
        default="core",
        help="core = shared signal_core path (R5a, default); legacy = pre-R5a raw path (comparison only)",
    )
    ap.add_argument(
        "--paper-book",
        default=None,
        help="paper book to run (default: root paper_book_latest.json); an R5b engine book is advanced "
        "with the backtest engine, a legacy book keeps the legacy refresh",
    )
    ap.add_argument(
        "--paper-out",
        default=None,
        help="with --dry-run: write the advanced R5b book here (never the root paper_book_latest.json)",
    )
    ap.add_argument(
        "--contract-bundle",
        default=None,
        help="read month-contract bars from this frozen bundle (*.contracts.json[.gz]) instead of the local "
        "cache; nothing is fetched",
    )
    args, _unknown = ap.parse_known_args(argv)
    if args.out and not args.dry_run:
        ap.error("--out requires --dry-run")
    if args.paper_out and not args.dry_run:
        ap.error("--paper-out requires --dry-run")
    if args.paper_out and Path(args.paper_out).resolve() == (ROOT / "paper_book_latest.json").resolve():
        ap.error("--paper-out must not be the root paper_book_latest.json")
    return args


def _engine_book_context(book_path: Path, bars: dict, curves: dict | None) -> dict | None:
    """R5b: advance an engine book (``"engine": "R5b"``) to today's session with the backtest engine.

    Stamps the delivery calendar / contract-fill overlay on today's bars (cache only, as simulate
    does), builds the shared engine and rolls the book: yesterday's pending orders fill at today's
    open, then every position is managed on today's bar.  Returns None for a legacy book."""
    import bisect

    import historical_backtest as hb
    import numpy as np
    import paper_book as pb
    from signal_core import build_signal_inputs, covered_dates

    book = pb._load(Path(book_path))
    if not pb.is_engine_book(book):
        return None
    settings = pb.engine_settings()
    series = {u["code"]: {"meta": dict(u), "hist": bars[u["code"]]} for u in UNIVERSE if bars.get(u["code"])}
    csrc = _contract_source()
    contract_pack = hb.prepare_pack_for_execution((series, {}, {}), root=csrc)
    dates = covered_dates(series)
    day = dates[-1]
    main_map, adj = build_signal_inputs(series, root=csrc)
    eng = pb.build_engine(
        series, settings, main_map=main_map, adj=adj, curves=curves, contract_root=csrc, minute_root=ROOT
    )

    def _prev(d):
        k = bisect.bisect_left(dates, d)
        return dates[k - 1] if k > 0 else None

    def _next(d):
        k = bisect.bisect_right(dates, d)
        if k < len(dates):
            return dates[k]
        return str(np.busday_offset(d, 1, roll="forward"))  # weekday calendar (CN holidays not modelled)

    def _between(a, b):
        return [x for x in dates if (not a or x > a) and x <= b]

    rolled = pb.roll_engine_book(
        book, day, engine_for_day=lambda d: eng, prev_day_fn=_prev, next_day_fn=_next, days_between=_between
    )
    return {
        "book": book,
        "path": Path(book_path),
        "settings": settings,
        "day": day,
        "eng": eng,
        "inputs": (main_map, adj),
        "rolled": rolled,
        "contract_pack": {k: (contract_pack or {}).get(k) for k in ("fill_series", "ok", "error")},
    }


def _refresh_side_data() -> tuple[dict, dict]:
    """Minute bars, desk research and option-IV refreshes (network / cache writers; skipped by --dry-run)."""
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

    # Desk research soft refresh — split packs so slow/network (heavy) cannot
    # block fast desk pages (core). Never paper_book / formal BT / seats.
    try:
        from research.desk_daily_refresh import refresh_desk_research_split

        print("[cta] refresh desk research (core then heavy)...")
        desk_r = refresh_desk_research_split(ROOT)
        print(
            f"[desk-research] ok={desk_r.get('ok')} "
            f"seconds={desk_r.get('seconds_total')} → {desk_r.get('path')}"
        )
        for label in ("core", "heavy"):
            sub = desk_r.get(label) or {}
            print(
                f"[desk-research:{label}] n_ok={sub.get('n_ok')} "
                f"n_fail={sub.get('n_fail')} {sub.get('seconds_total')}s"
            )
            for step in sub.get("steps") or []:
                if not step.get("ok"):
                    print(
                        f"::warning title=desk research {label}/{step.get('id')} soft-fail::"
                        f"{step.get('error') or 'failed'}"
                    )
    except Exception as exc:  # noqa: BLE001
        print(f"[desk-research] soft-fail: {exc}")
        print(f"::warning title=desk research soft-fail::{exc}")

    # Option IV daily backfill (CZCE/SHFE). Soft: asof empty not poison-cached.
    iv_summary: dict = {"ok": False}
    try:
        from iv_breakout import refresh_option_iv

        print("[cta] refresh option IV...")
        iv_summary = refresh_option_iv(ROOT)
        print(
            f"[cta] option_iv asof={iv_summary.get('asof')} "
            f"fetched={iv_summary.get('fetched')} cached={iv_summary.get('cached')} "
            f"missing={iv_summary.get('missing')} soft_empty={iv_summary.get('soft_empty')}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[cta] option_iv soft-fail: {exc}")
        print(f"::warning title=option IV refresh failed::{exc}")
        iv_summary = {"ok": False, "error": str(exc)[:300]}
    return minute_summary, iv_summary


def main(argv=None):
    args = _parse_args(argv)
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
        if args.dry_run:
            if args.out:
                Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0
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
    if lab_bypass.get("enabled") and not args.dry_run:
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
    signal_path = args.signal_path
    global _CONTRACT_SOURCE
    _CONTRACT_SOURCE = None
    if args.contract_bundle:
        from research.data_quality.contract_store import load_bundle

        _CONTRACT_SOURCE = load_bundle(args.contract_bundle)
        print(f"[contracts] source = bundle {args.contract_bundle} ({len(_CONTRACT_SOURCE.known_contracts())} contracts)")
    paper_book_path = Path(args.paper_book) if args.paper_book else ROOT / "paper_book_latest.json"
    engine_ctx = None
    engine_error = None
    vbypass = _vol_bypass()
    signals = []
    snaps = []
    bars: dict = {}
    fetch_errors: dict = {}
    data_sources: dict = {}
    contract_stats = None
    if signal_path == "legacy":
        for u in UNIVERSE:
            print(f"[cta] fetch {u['code']}...")
            try:
                snap = _fetch_snapshot(u, curves, mode)
                snaps.append(snap)
                sig = _signal(u, snap, risk_budget=risk_budget)
                if snap.get("block"):
                    sig["block"] = snap["block"]
                sig["signal_path"] = "legacy"
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
    else:
        from historical_backtest import LOOKBACK_DAYS, fetch_history

        for u in UNIVERSE:
            print(f"[cta] fetch {u['code']}...")
            try:
                hist, meta = fetch_history(u, n=LOOKBACK_DAYS)
                if len(hist) < 61:
                    raise RuntimeError(f"bars {len(hist)} source={meta.get('source')}")
                bars[u["code"]] = hist
                data_sources[u["code"]] = meta.get("source")
                snaps.append(
                    {
                        "source": meta.get("source"),
                        "bar_date": hist[-1]["date"],
                        "prev_date": hist[-2]["date"],
                        "n": len(hist),
                    }
                )
                print(f"  {u['code']} src={meta.get('source')} date={hist[-1]['date']} bars={len(hist)}")
            except Exception as e:
                fetch_errors[u["code"]] = f"{e}"
                snaps.append({})
                print(f"  ERR {u['code']}: {e}")
        contract_stats = _ensure_contracts(UNIVERSE, bars)
        print(
            f"[contracts] requests={contract_stats['requests']} seconds={contract_stats['seconds']} "
            f"fetched={len(contract_stats['fetched'])} failed={len(contract_stats['failed'])}"
        )
        try:
            engine_ctx = _engine_book_context(paper_book_path, bars, curves)
        except Exception as exc:  # noqa: BLE001
            engine_ctx = None
            engine_error = str(exc)[:300]
            print(f"::warning title=R5b paper book not advanced::{exc}")
        if engine_ctx is not None:
            import paper_book as _pb

            sizing_eq, risk_budget = _pb.sizing_for(engine_ctx["rolled"]["sizing_equity"], engine_ctx["settings"])
            rolled = engine_ctx["rolled"]
            # a freshly seeded book already at ``day`` comes back as a no-op without the roll counters
            print(
                f"[paper-R5b] book={engine_ctx['path'].name} day={engine_ctx['day']} "
                f"rolled={rolled.get('days_rolled', [])} filled={rolled.get('opened_n', 0)} "
                f"closed={rolled.get('closed_n', 0)} noop={bool(rolled.get('noop'))} sizing={sizing_eq} risk={risk_budget}"
            )
        # placeholder rows until compute_signals (after the seat ensure stage)
        signals = [
            {"code": u["code"], "name": u["name"], "bar_date": (bars.get(u["code"]) or [{}])[-1].get("date")}
            for u in UNIVERSE
        ]

    observe_coverage: dict = {
        "complete": False,
        "bars_ok": [],
        "bars_missing": [],
        "seats_ok": [],
        "seats_missing": [],
        "seat_fill": {},
    }
    bar_ok = [s["code"] for s in signals if s.get("bar_date") and not str(s.get("error") or "")]
    bar_ok = [c for c in bar_ok if c not in fetch_errors]
    bar_miss = [u["code"] for u in UNIVERSE if u["code"] not in set(bar_ok)]
    observe_coverage["bars_ok"] = bar_ok
    observe_coverage["bars_missing"] = bar_miss

    # Observation sample: all 20 must have seats — exchange → 东财 → 新浪.
    # Short lookback densifies DCE/EM so 席位页 is not stuck on 2–3 sparse days.
    from market_data import latest_expected_session_date

    seat_date_cap = latest_expected_session_date().isoformat()
    seat_days = sorted({
        str(s.get("bar_date"))
        for s in snaps
        if s.get("bar_date") and str(s.get("bar_date")) <= seat_date_cap
    })
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
            stats = ensure_member_days(seat_days, dce=True, public_first=True)
            print(
                f"  [observe] member ensure days={stats['days']} "
                f"shfe={stats['shfe']} czce={stats['czce']} "
                f"dce={stats['dce']} em={stats.get('eastmoney', 0)}"
            )
        codes = [u["code"] for u in UNIVERSE]
        requested = seat_days[-1]
        cov = ensure_universe_member_coverage(requested, codes)
        observe_coverage["seats_ok"] = cov.get("ok") or []
        observe_coverage["seats_missing"] = cov.get("missing") or []
        observe_coverage["seat_fill"] = cov.get("filled") or {}
        observe_coverage["seat_ymd"] = cov.get("ymd")
        observe_coverage["seats_requested"] = requested
        observe_coverage["seats_deferred"] = False
        print(
            f"  [observe] seats {cov.get('n_ok')}/{cov.get('n_codes')} "
            f"missing={cov.get('missing')} filled={cov.get('filled')}"
        )
        # 15:30 CST daily often runs before CZCE/Sina publish today's seat books.
        # Snap bar_dates are usually a single day — walk prior weekdays for a complete book.
        if observe_coverage["seats_missing"]:
            try:
                cursor = date.fromisoformat(str(requested)[:10])
            except ValueError:
                cursor = None
            tried = {str(requested)[:10]}
            for _ in range(8):
                if cursor is None:
                    break
                cursor -= timedelta(days=1)
                if cursor.weekday() >= 5:
                    continue
                prior = cursor.isoformat()
                if prior in tried:
                    continue
                tried.add(prior)
                prior_cov = ensure_universe_member_coverage(prior, codes)
                if prior_cov.get("complete"):
                    observe_coverage["seats_deferred"] = True
                    observe_coverage["seats_used"] = prior
                    print(
                        f"::notice::seats asof {requested} incomplete "
                        f"missing={observe_coverage['seats_missing']}; "
                        f"prior {prior} complete — defer observe gate"
                    )
                    break
    else:
        observe_coverage["seats_missing"] = [u["code"] for u in UNIVERSE]

    if signal_path == "legacy":
        _legacy_postfilters(
            signals, snaps, mode=mode, bypass=bypass, curves=curves, seat_days=seat_days
        )
    else:
        signals, core_info = compute_signals(
            UNIVERSE,
            bars,
            mode=mode,
            bypass=bypass,
            vbypass=vbypass,
            curves=curves,
            member_loader=_member_loader(mode),
            risk_budget=risk_budget,
            contract_root=_contract_source(),
            errors=fetch_errors,
            data_sources=data_sources,
            day=None if engine_ctx is None else engine_ctx["day"],
            inputs=None if engine_ctx is None else engine_ctx["inputs"],
        )
        if core_info.get("adj_fallback_codes"):
            print(f"[cta] adj_fallback (roll spreads in signal): {core_info['adj_fallback_codes']}")
    seats_ready = (
        not observe_coverage["seats_missing"] or observe_coverage.get("seats_deferred")
    )
    observe_coverage["complete"] = (
        not observe_coverage["bars_missing"] and bool(seats_ready)
    )
    if observe_coverage.get("seats_deferred"):
        print(
            f"[cta] OBSERVE SEATS DEFERRED requested={observe_coverage.get('seats_requested')} "
            f"used={observe_coverage.get('seats_used')} "
            f"missing_today={observe_coverage['seats_missing']}"
        )
    elif not observe_coverage["complete"]:
        print(
            f"[cta] OBSERVE INCOMPLETE bars_missing={observe_coverage['bars_missing']} "
            f"seats_missing={observe_coverage['seats_missing']}"
        )

    if args.dry_run:
        minute_summary = {"ok": 0, "fail": 0, "periods": ["15", "60"], "skipped": "dry-run", "rows": []}
        iv_summary = {"ok": False, "skipped": "dry-run"}
    else:
        minute_summary, iv_summary = _refresh_side_data()

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

    engine_pick = None
    if engine_ctx is not None:
        import paper_book as _pb

        engine_pick = _pb.plan_entries(
            core_info["core"],
            eng=engine_ctx["eng"],
            pos=engine_ctx["rolled"]["positions"],
            day=engine_ctx["day"],
            sizing_equity=sizing_eq,
            settings=engine_ctx["settings"],
            exclude={str(s.get("code")) for s in signals if s.get("block")},
        )
        port_meta = _apply_caps(
            signals, sizing_equity=sizing_eq, held=engine_ctx["rolled"]["positions"], engine_pick=engine_pick
        )
    else:
        port_meta = _apply_caps(signals, sizing_equity=sizing_eq, held=_load_paper_held())
    port_meta["sizing_equity"] = round(sizing_eq, 2)
    port_meta["equity_compound"] = EQUITY_COMPOUND
    print(
        f"[cta] portfolio selected={port_meta.get('selected')} "
        f"gross={port_meta.get('gross_after')} ({port_meta.get('gross_pct')}%) "
        f"atr_risk={port_meta.get('atr_risk_after')} ({port_meta.get('atr_risk_pct')}%) "
        f"scale={port_meta.get('scale')} weak={port_meta.get('weak_filtered')} "
        f"bucket_skip={port_meta.get('bucket_skipped')}"
    )

    # T-DU / DU-01: formal asof = expected session day (not wall-clock run day).
    from market_data import latest_expected_session_date
    from research_quality import validate_signals

    session_date = latest_expected_session_date(now)
    asof_ymd = session_date.strftime("%Y%m%d")
    session_iso = session_date.isoformat()
    quality = validate_signals(
        signals,
        asof=asof_ymd,
        universe=UNIVERSE,
        expected_session=session_date,
    )
    stale = list(quality.get("stale_codes") or [])
    ahead = list(quality.get("ahead_codes") or [])
    if stale or ahead:
        print(
            f"[cta] STALE FUSE session={session_iso} "
            f"stale={stale or []} ahead={ahead or []}"
        )
    if not quality.get("ok"):
        print(
            f"[cta] QUALITY GATE FAIL session={session_iso} "
            f"bad={quality.get('bad_codes')} "
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
        port_meta["stale_fuse"] = True
    else:
        print(
            f"[cta] quality ok session={session_iso} "
            f"checked={quality.get('checked')} bad_n={quality.get('bad_n')}"
        )
    engine_book = None
    engine_summary = None
    if engine_ctx is not None:
        import paper_book as _pb

        pending = list(engine_pick[0]) if quality.get("ok") else []
        engine_book = _pb.attach_pending(engine_ctx["book"], engine_ctx["rolled"], pending, engine_pick[1])
        engine_summary = {
            "engine": _pb.ENGINE_TAG,
            "book": str(engine_ctx["path"]),
            "asof": engine_book.get("asof"),
            "days_rolled": engine_book.get("days_rolled"),
            "noop": bool(engine_book.get("noop")),
            "sizing_equity_raw": engine_ctx["rolled"]["sizing_equity"],
            "equity_mtm": engine_book.get("equity_mtm"),
            "filled": [(r["code"], r["direction"], r["lots"], r["entry"]) for r in engine_book.get("opened_today") or []],
            "closed": [(r["code"], r["reason"], r["exit"]) for r in engine_book.get("closed_today") or []],
            "held": sorted(engine_book.get("positions") or {}),
            "pending": [
                (c["code"], c["direction"], int(c["lots"]), c.get("signal_date"))
                for c in engine_book.get("pending") or []
            ],
            "contract_pack": engine_ctx["contract_pack"],
        }
    elif engine_error:
        engine_summary = {"engine": "R5b", "error": engine_error}

    # Paper-only MDS+EHI sentiment sleeve (ChatGPT share); never sizes Path-A lots.
    sentiment_meta: dict = {"ok": False}
    try:
        if args.dry_run:
            raise RuntimeError("skipped (dry-run: shadow snapshot not written)")
        from sentiment_mds import OUT as _SENT_OUT, build_snapshot, write_snapshot

        seat_rows = []
        seats_book = {}
        day_key = seat_days[-1] if seat_days else None
        prev_key = seat_days[-2] if len(seat_days) >= 2 else None
        if day_key:
            load_days = [prev_key, day_key] if prev_key else [day_key]
            try:
                ensure_member_days(load_days, dce=True, public_first=True)
            except Exception as densify_exc:  # noqa: BLE001
                print(f"[sentiment] seat densify soft-fail: {densify_exc}")
            seats_book = load_member_seats(load_days, [u["code"] for u in UNIVERSE])
        for sig in signals:
            code = str(sig.get("code") or "").upper()
            book = seats_book.get(code) or {}
            day_row = book.get(day_key) if day_key else None
            net = float((day_row or {}).get("inst") or 0.0) if day_row else 0.0
            if prev_key and prev_key in book:
                prev_net = float((book.get(prev_key) or {}).get("inst") or 0.0)
                net_chg = net - prev_net
            else:
                net_chg = 0.0
            seat_rows.append(
                {
                    "code": code,
                    "net": net,
                    "net_chg": net_chg,
                    "ret_1d": sig.get("ret_1d"),
                    "oi": sig.get("oi"),
                    "volume": sig.get("volume"),
                }
            )
        snap_sent = build_snapshot(seat_rows, asof=asof_ymd)
        # 磊定 2026-11-02：日更只写影子，禁止改正式 latest.json
        snap_sent["shadow"] = True
        sent_path = write_snapshot(
            snap_sent, out_dir=_SENT_OUT / "shadow", update_latest=False
        )
        sentiment_meta = {
            "ok": True,
            "path": str(sent_path.name),
            "stance": snap_sent.get("stance"),
            "portfolio_p3": snap_sent.get("portfolio_p3"),
            "longs": snap_sent.get("longs"),
            "shorts": snap_sent.get("shorts"),
            "live": False,
            "shadow": True,
        }
        print(
            f"[sentiment] shadow MDS+EHI stance={snap_sent.get('stance')} "
            f"p3={snap_sent.get('portfolio_p3')} n={snap_sent.get('n')} "
            f"path={sent_path.name} (update_latest=False)"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[sentiment] soft-fail: {exc}")
        sentiment_meta = {"ok": False, "error": str(exc)[:300], "live": False}

    report = {
        "asof": asof_ymd,
        "session_date": session_iso,
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
        "data_source": "bars=sina→TqSdk→iFinD; seats=eastmoney→sina (exchange soft)",
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
        "option_iv": {
            "ok": bool(iv_summary.get("ok")),
            "asof": iv_summary.get("asof"),
            "fetched": iv_summary.get("fetched"),
            "cached": iv_summary.get("cached"),
            "missing": iv_summary.get("missing"),
            "soft_empty": iv_summary.get("soft_empty"),
            "last_ok": iv_summary.get("last_ok"),
            "error": iv_summary.get("error"),
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
        "signal_path": signal_path,
        "dry_run": bool(args.dry_run),
        "contract_cache": (
            None
            if contract_stats is None
            else {
                "requests": contract_stats["requests"],
                "seconds": contract_stats["seconds"],
                "fetched_n": len(contract_stats["fetched"]),
                "cached_n": contract_stats["cached_n"],
                "failed": contract_stats["failed"],
            }
        ),
        "adj_fallback_codes": [s.get("code") for s in signals if s.get("adj_fallback")],
        "paper_book_engine": engine_summary,
    }
    if args.dry_run:
        if engine_book is not None and args.paper_out:
            from paper_book import _atomic_write_json

            _atomic_write_json(Path(args.paper_out), engine_book)
            print(f"[paper-R5b] dry-run: wrote {args.paper_out}")
        blob = json.dumps(report, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(blob, encoding="utf-8")
            print(f"[cta] dry-run: wrote {args.out} (no root / archive / paper_book writes)")
        else:
            print("[cta] dry-run: no --out given; report not written")
        return 0 if quality.get("ok") else 3
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
        if engine_book is not None:
            from paper_book import _atomic_write_json

            if not engine_book.get("noop"):
                _atomic_write_json(engine_ctx["path"], engine_book)
            print(
                f"[paper-R5b] asof={engine_book.get('asof')} held={len(engine_book.get('positions') or {})} "
                f"pending={engine_book.get('pending_n')} noop={bool(engine_book.get('noop'))}"
            )
        elif not engine_error:
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
        try:
            from desk.tech_score import write_tech_score_snapshot

            tech = write_tech_score_snapshot(ROOT)
            print(f"[tech] asof={tech.get('asof')} n={tech.get('n')} → {tech.get('path')}")
        except Exception as exc:
            # Soft-fail (paper publish already done) but make it loud in GHA.
            msg = f"[tech] refresh failed: {exc}"
            print(msg)
            print(f"::warning title=tech_score refresh failed::{exc}")
            print(msg, file=sys.stderr)
        try:
            # SuperTrend observe sleeve (shadow + proxy 模拟仓); does not touch Path-A.
            from scripts.shadow_supertrend import write_proxy_supertrend

            st_meta = write_proxy_supertrend(ROOT)
            print(
                f"[st-proxy] ret={st_meta.get('ret_pct')}% held={st_meta.get('held_n')} "
                f"→ {st_meta.get('proxy')}"
            )
        except Exception as exc:
            print(f"[st-proxy] refresh failed: {exc}")
            print(f"::warning title=supertrend proxy refresh failed::{exc}")
        try:
            # 仓单：交易所日报主源 + 东财库存旁路；软失败，不编造。
            from warehouse_receipt import refresh_warehouse

            wh = refresh_warehouse(ROOT)
            print(
                f"[warehouse] primary={wh.get('primary_n')} bypass={wh.get('bypass_n')} "
                f"missing={wh.get('missing_n')} ex={wh.get('exchange_ymd')}"
            )
            ex_st = wh.get("exchange_status") or {}
            for ex_name in ("SHFE", "DCE"):
                pack = ex_st.get(ex_name) or {}
                if pack and not pack.get("ok"):
                    print(
                        f"::warning title=warehouse {ex_name} primary down::"
                        f"{pack.get('error') or 'empty'}; EM bypass in use"
                    )
        except Exception as exc:
            print(f"[warehouse] refresh failed: {exc}")
            print(f"::warning title=warehouse refresh failed::{exc}")
        try:
            # Rewrite vol engine snapshot from warmed IV cache (desk IV panel).
            from vol_engine import run_universe

            print("[cta] refresh vol_engine snapshot...")
            vol_pack = run_universe(
                ROOT,
                refresh_iv=False,
                fetch_calendar=False,
                write_data=True,
                write_oos=False,
            )
            iv_dates = sorted(
                {
                    str((r.get("iv") or {}).get("date") or "")
                    for r in (vol_pack.get("reports") or [])
                    if (r.get("iv") or {}).get("date")
                }
            )
            print(
                f"[vol] ok={vol_pack.get('ok')} codes={len(vol_pack.get('codes') or [])} "
                f"iv_dates={iv_dates[-3:] if iv_dates else []}"
            )
        except Exception as exc:
            print(f"[vol] refresh failed: {exc}")
            print(f"::warning title=vol_engine refresh failed::{exc}")
        try:
            # Keep desk_composite_latest.json aligned with today's L1 report (final signal
            # marks it 过期 otherwise). Soft: needs desk deps (requirements-desk.txt).
            from desk.composite_eval import desk_composite_score

            comp = desk_composite_score(ROOT, write=True)
            print(
                f"[composite] ok={comp.get('ok')} score={comp.get('desk_score')} "
                f"asof={comp.get('asof')}"
            )
        except Exception as exc:
            print(f"[composite] refresh failed: {exc}")
            print(f"::warning title=desk composite refresh failed::{exc}")
        try:
            # Research-only shadow attribution ledger + category win rates.
            # Soft: never mutates paper_book / entry_filter / formal Path-A.
            from research.shadow_perf import refresh_shadow_perf

            sp = refresh_shadow_perf(ROOT, write=True)
            print(
                f"[shadow_perf] asof={sp.get('asof')} n={sp.get('n_ledger')} "
                f"new={sp.get('n_candidates_new')} → {sp.get('path')}"
            )
            try:
                from research.shadow_perf.attribution import build_shadow_attribution

                attr = build_shadow_attribution(ROOT, write=True)
                print(
                    f"[shadow_attr] ok={attr.get('ok')} n={attr.get('n_trades')} "
                    f"→ {attr.get('path')}"
                )
            except Exception as attr_exc:  # noqa: BLE001
                print(f"[shadow_attr] soft-fail: {attr_exc}")
            try:
                from research.vol_observe import build_vol_observe

                vo = build_vol_observe(ROOT, write=True)
                print(f"[vol_observe] n={vo.get('n')} → {vo.get('path')}")
            except Exception as vo_exc:  # noqa: BLE001
                print(f"[vol_observe] soft-fail: {vo_exc}")
        except Exception as exc:
            print(f"[shadow_perf] refresh failed: {exc}")
            print(f"::warning title=shadow_perf refresh failed::{exc}")
        try:
            # Options research: gamma cache snaps + optional live Bid/Ask accumulate + BT.
            # Soft: never writes paper_book / formal historical_backtest.
            from research.options.chain_store import accumulate_live_bidask, collect_code_from_cache
            from research.options.backtest.engine import run_credit_vertical_bt
            from research.options.risk_report import build_risk_report

            n_snap = 0
            for code in ("CF", "SR", "MA"):
                for r in collect_code_from_cache(ROOT, code, limit=5):
                    if r.get("error"):
                        print(f"[options-chain] {code} {r.get('asof')} soft-fail: {r['error']}")
                    else:
                        n_snap += 1
            print(f"[options-chain] soft collect n={n_snap}")
            try:
                # Fast Bid/Ask only; 45s/code cap — must not hang daily_update.
                acc = accumulate_live_bidask(
                    ROOT, codes=["CF", "SR", "MA"], overall_deadline_s=45.0
                )
                print(
                    f"[options-chain] live bid/ask ok={acc.get('n_ok')} "
                    f"fail={acc.get('n_fail')}"
                )
            except Exception as live_exc:
                print(f"[options-chain] live bid/ask soft-fail: {live_exc}")
            try:
                from research.options.upgrade_gate import write_gate

                gate = write_gate(ROOT)
                print(f"[options-upgrade] {gate.get('reminder')}")
                if gate.get("ready"):
                    print(
                        "::notice title=options F2 sample ready::"
                        f"{gate.get('next_upgrade_id')}: {gate.get('next_upgrade_title')}"
                    )
            except Exception as gate_exc:
                print(f"[options-upgrade] gate soft-fail: {gate_exc}")
            bt = run_credit_vertical_bt(ROOT, codes=["CF", "SR", "MA"], write=True)
            m = bt.get("metrics") or {}
            print(
                f"[options-bt] state={bt.get('strategy_state')} "
                f"n_closed={m.get('n_closed')} → {bt.get('path')}"
            )
            risk = build_risk_report(ROOT, write=True)
            print(f"[options-risk] → {risk.get('path')}")
        except Exception as exc:
            print(f"[options-research] soft-fail: {exc}")
            print(f"::warning title=options research soft-fail::{exc}")
    else:
        print("[paper] skip: quality gate failed")
    # Observation incomplete or quality fail → non-zero so CI does not publish formal.
    if not quality.get("ok"):
        return 3
    return 0 if observe_coverage.get("complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())
