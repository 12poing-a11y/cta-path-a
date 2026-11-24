# -*- coding: utf-8 -*-
"""Shared Path-A entry-candidate computation (R5a).

``historical_backtest.simulate`` (the backtest) and ``daily_update`` (the daily report) must
derive their entry candidates from the same code, otherwise the two can give opposite
verdicts on the same day (R6c made the backtest roll-free; the report was still raw).

``path_a_candidate`` evaluates ONE code on ONE bar index and returns everything both callers
need: r20 / r60 / ATR (roll-free when ``adj`` is given), direction, the filter verdicts in the
backtest's order (momentum gate -> entry_block/seats -> carry bypass -> vol bypass), the ATR
stop / target distances and the lots.  The caller keeps its own counters and portfolio caps.

Inputs are plain data (no network, no files): the caller injects bars, the adjusted series, the
(already lagged) seat / carry books.
"""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from path_a_filters import carry_bypass_decision, entry_block, seat_decision
from vol_factor_combo import vol_entry_block

WARMUP_BARS = 60  # same value as historical_backtest.WARMUP (kept local to avoid a cycle)


def covered_dates(series: dict[str, dict[str, Any]]) -> list[str]:
    """Sessions covered by at least ``max(3, n_codes // 3)`` codes (the backtest's date axis)."""
    hits: Counter = Counter()
    for s in series.values():
        for h in s["hist"]:
            hits[h["date"]] += 1
    min_cover = max(3, len(series) // 3)
    return sorted(d for d, c in hits.items() if c >= min_cover)


def build_signal_inputs(
    series: dict[str, dict[str, Any]],
    *,
    root: Path | None = None,
    start: str | None = None,
    adjusted: bool = True,
):
    """``(main_map, adj)`` exactly as ``simulate`` builds them (R6b-fix / R6c)."""
    from research.data_quality.adjusted import build_adjusted_pack
    from research.data_quality.main_map import build_main_map

    main_map = build_main_map(series, root=root, start=start)
    adj = build_adjusted_pack(series, main_map, root=root) if adjusted else {}
    return main_map, adj


def sizing(
    close: float,
    atr: float,
    direction: str,
    mult: float,
    *,
    day_risk: float,
    stop_atr_mult: float,
    reward_rr: float,
    carry_mult: float = 1.0,
    min_lots: int = 0,
    min_lots_guard_frac: float | None = None,
) -> dict[str, Any]:
    """ATR stop / target distances and lots (the backtest's formula)."""
    stop_dist = stop_atr_mult * atr
    target_dist = reward_rr * stop_dist
    if direction == "多":
        stop = close - stop_dist
        target = close + target_dist
    else:
        stop = close + stop_dist
        target = close - target_dist
    risk_per_lot = stop_dist * mult
    lots = int(math.floor(day_risk / risk_per_lot)) if risk_per_lot > 0 else 0
    if carry_mult < 1.0 and lots > 0:
        lots = int(math.floor(lots * carry_mult))
    bumped = False
    if min_lots > 0 and lots < min_lots:
        ok = True
        if min_lots_guard_frac is not None:
            ok = 0 < atr < float(close) * float(min_lots_guard_frac)
        if ok:
            lots = int(min_lots)
            bumped = True
    return {
        "stop_dist": stop_dist,
        "target_dist": target_dist,
        "stop": stop,
        "target": target,
        "risk_per_lot": risk_per_lot,
        "lots": lots,
        "min_lots_bumped": bumped,
    }


def path_a_candidate(
    code: str,
    hist: list[dict],
    i: int,
    *,
    adj: Any,
    meta: dict[str, Any],
    params: dict[str, Any],
    ctx: dict[str, Any],
    ret_n_fn: Callable | None = None,
    atr14_fn: Callable | None = None,
    composite_trend_fn: Callable | None = None,
    vol_hist_fn: Callable | None = None,
    entry_block_fn: Callable | None = None,
    seat_decision_fn: Callable | None = None,
    carry_decision_fn: Callable | None = None,
    vol_block_fn: Callable | None = None,
) -> dict[str, Any]:
    """Evaluate one code at bar ``i``.

    ``*_fn`` hooks default to the real filters; ``simulate`` passes its own module-level names so
    tests that monkeypatch ``historical_backtest.entry_block`` etc. keep working.

    params: mode, min_r20, min_r60, stop_atr_mult, reward_rr, day_risk, min_lots,
            min_lots_guard_frac, bypass (carry_bypass_cfg), vbypass (vol_bypass_cfg)
    ctx:    day (str), curves, member (lagged books), min_seat_days, seat_days_upto
            (callable code, day -> int), peer_r20_fn (callable -> list[float]) for 'climax'

    Returned ``status``:
      no_atr / no_ret   inputs missing (nothing else is meaningful)
      no_signal         not a Path-A signal (weak, or 20/60 conflict); ``r20/r60/atr`` and, when
                        aligned, an un-filtered ``sizing`` are still returned (display only)
      blocked           entry_block / carry / vol filter said no (``blocked`` holds the reason)
      lots0             passed every filter but lots == 0
      ok                a candidate (``candidate`` is the dict the caps consume)
    """
    entry_block_fn = entry_block_fn or entry_block
    seat_decision_fn = seat_decision_fn or seat_decision
    carry_decision_fn = carry_decision_fn or carry_bypass_decision
    vol_block_fn = vol_block_fn or vol_entry_block
    mode = params["mode"]
    res: dict[str, Any] = {
        "code": code,
        "status": None,
        "r20": None,
        "r60": None,
        "atr": None,
        "direction": None,
        "aligned": False,
        "gate_ok": False,
        "fac": None,
        "seat_short": False,
        "seat_label": None,
        "blocked": None,
        "block_kind": None,
        "carry": None,
        "vol_reason": None,
        "sizing": None,
        "lots": 0,
        "candidate": None,
    }
    if ret_n_fn is None or atr14_fn is None:
        from historical_backtest import atr14 as _atr14, ret_n as _ret_n

        ret_n_fn = ret_n_fn or _ret_n
        atr14_fn = atr14_fn or _atr14

    a = adj.atr14(i) if adj is not None else atr14_fn(hist, i)
    res["atr"] = a
    if a is None or a <= 0:
        res["status"] = "no_atr"
        return res

    fac = None
    if mode == "ctf":
        if composite_trend_fn is None:
            from historical_backtest import composite_trend as composite_trend_fn
        fac = composite_trend_fn(hist, i)
        res["fac"] = fac
        if fac is None or fac["f"] == 0:
            res["status"] = "no_signal"
            return res
        direction = "多" if fac["f"] > 0 else "空"
        score = abs(fac["f"]) * 100.0
        r20, r60 = score, score
        res.update(r20=r20, r60=r60, direction=direction, aligned=True, gate_ok=True)
    else:
        r20 = adj.ret_n(i, 20) if adj is not None else ret_n_fn(hist, i, 20)
        r60 = adj.ret_n(i, 60) if adj is not None else ret_n_fn(hist, i, 60)
        res.update(r20=r20, r60=r60)
        if r20 is None or r60 is None:
            res["status"] = "no_ret"
            return res
        aligned = r20 != 0 and r60 != 0 and ((r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0))
        res["aligned"] = aligned
        direction = ("多" if r20 > 0 else "空") if aligned else None
        res["direction"] = direction
        gate_ok = (
            abs(r20) >= params["min_r20"]
            and abs(r60) >= params["min_r60"]
            and ((r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0))
        )
        res["gate_ok"] = gate_ok
        if not gate_ok:
            res["status"] = "no_signal"
            if aligned:
                res["sizing"] = sizing(
                    hist[i]["close"], a, direction, float(meta["mult"]),
                    day_risk=params["day_risk"], stop_atr_mult=params["stop_atr_mult"],
                    reward_rr=params["reward_rr"], min_lots=params.get("min_lots") or 0,
                    min_lots_guard_frac=params.get("min_lots_guard_frac"),
                )
            return res

    day = ctx["day"]
    curves = ctx.get("curves") or {}
    member = ctx.get("member") or {}
    peers: list = []
    if mode == "climax" and ctx.get("peer_r20_fn") is not None:
        peers = ctx["peer_r20_fn"]()
    block_mode = "seats" if mode == "roll" else mode
    member_used = member
    min_seat_days = ctx.get("min_seat_days")
    if (
        mode in ("seats", "roll")
        and min_seat_days
        and ctx["seat_days_upto"](code, day) < int(min_seat_days)
    ):
        member_used = {}
        res["seat_short"] = True
    blocked = None if mode == "ctf" else entry_block_fn(
        block_mode, hist, i, direction, day, code, a, curves, member_used, peers
    )
    if mode in ("seats", "roll") and not blocked:
        _reason, label = seat_decision_fn(direction, (member_used.get(code) or {}).get(day))
        res["seat_label"] = label
    if blocked:
        res.update(status="blocked", blocked=blocked, block_kind="entry_filter")
        return res

    carry_mult = 1.0
    bypass = params.get("bypass") or {}
    if bypass.get("enabled"):
        pair = ((curves.get(code) or {}).get("carry") or {}).get(day)
        by_reason, carry_mult, by_label, gap = carry_decision_fn(
            direction,
            pair,
            extreme_gap_pct=float(bypass["extreme_gap_pct"]),
            action=str(bypass["action"]),
            scale=float(bypass["scale"]),
        )
        res["carry"] = {"reason": by_reason, "mult": carry_mult, "label": by_label, "gap_pct": gap}
        if by_reason:
            res.update(status="blocked", blocked=by_reason, block_kind="carry")
            return res
    vbypass = params.get("vbypass") or {}
    if vbypass.get("enabled"):
        vh = vol_hist_fn(code, hist) if vol_hist_fn is not None else (
            adj.vol_hist() if adj is not None else hist
        )
        vol_reason = vol_block_fn(
            vh,
            i,
            enabled=True,
            action=str(vbypass.get("action") or "observe"),
            short_n=int(vbypass["short_n"]),
            mid_n=int(vbypass["mid_n"]),
            long_n=int(vbypass["long_n"]),
            expand_ratio=float(vbypass["expand_ratio"]),
            compress_ratio=float(vbypass["compress_ratio"]),
        )
        res["vol_reason"] = vol_reason
        if vol_reason:
            res.update(status="blocked", blocked=vol_reason, block_kind="vol")
            return res

    close = hist[i]["close"]
    sz = sizing(
        close, a, direction, float(meta["mult"]),
        day_risk=params["day_risk"], stop_atr_mult=params["stop_atr_mult"],
        reward_rr=params["reward_rr"], carry_mult=carry_mult,
        min_lots=params.get("min_lots") or 0, min_lots_guard_frac=params.get("min_lots_guard_frac"),
    )
    res["sizing"] = sz
    res["lots"] = sz["lots"]
    if sz["lots"] <= 0:
        res["status"] = "lots0"
        return res
    res["status"] = "ok"
    res["candidate"] = {
        "code": code,
        "direction": direction,
        "lots": sz["lots"],
        "close": close,
        "mult": meta["mult"],
        "r20": round(r20, 3),
        "r60": round(r60, 3),
        "atr": round(a, 2),
        "bucket": meta.get("bucket"),
        "entry": close,
        "stop": sz["stop"],
        "target": sz["target"],
        "reason": "composite_trend" if mode == "ctf" else "path_a_rr2",
        "factor": None if fac is None else round(fac["f"], 6),
    }
    return res
