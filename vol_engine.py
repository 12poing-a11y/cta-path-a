# -*- coding: utf-8 -*-
"""Volatility Engine V1 — state screen + strategy selection matrix (paper only).

Four dimensions: RV percentile, IV percentile, VRP (IV−RV), IV velocity.
Outputs buy_vol / sell_vol / direction / no_trade research tags. Soft-annotate
only for sell-vol; does **not** change Path-A ``entry_filter=seats``.
No naked short straddles, no full Delta-Gamma hedge engine.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

DEFAULT_CODES = ("CF", "SR", "MA", "TA", "RU", "AG", "RB")

# Soft thresholds (research defaults).
RV_WIN = 20
RV_LOOKBACK = 250
IV_THIN_N = 20
LOW_PCT = 30.0
HIGH_PCT = 70.0
VRP_SELL_MIN = 0.03  # IV − RV (both decimal annualized)
IV_FALL_Z = -0.5
CALENDAR_RATIO = 1.15
ANNUALIZE = math.sqrt(252.0)

# Sentiment × vol tiers (research). Aligns with final_signal hard veto ≥60.
SENT_SOFT_CONV = 40.0
SENT_HARD_CONV = 60.0
SENT_EXTREME_CONV = 75.0


def vol_engine_cfg(raw: dict | None = None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    action = str(src.get("action") or "annotate").strip().lower()
    if action not in ("annotate", "observe", "off"):
        action = "annotate"
    return {
        "enabled": bool(src.get("enabled", True)),
        "action": action,  # sell-vol soft annotate by default
        "rv_win": int(src.get("rv_win") or RV_WIN),
        "rv_lookback": int(src.get("rv_lookback") or RV_LOOKBACK),
        "iv_thin_n": int(src.get("iv_thin_n") or IV_THIN_N),
        "low_pct": float(src.get("low_pct") if src.get("low_pct") is not None else LOW_PCT),
        "high_pct": float(
            src.get("high_pct") if src.get("high_pct") is not None else HIGH_PCT
        ),
        "vrp_sell_min": float(
            src.get("vrp_sell_min") if src.get("vrp_sell_min") is not None else VRP_SELL_MIN
        ),
        "calendar_ratio": float(
            src.get("calendar_ratio")
            if src.get("calendar_ratio") is not None
            else CALENDAR_RATIO
        ),
        "live_trading": False,
        "note": str(src.get("note") or ""),
    }


def _ymd(text: str) -> str:
    return str(text or "").replace("-", "")[:8]


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _closes(bars: list[dict]) -> tuple[list[float], list[str]]:
    closes: list[float] = []
    dates: list[str] = []
    for row in bars or []:
        try:
            c = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if c <= 0:
            continue
        closes.append(c)
        dates.append(str(row.get("date") or ""))
    return closes, dates


def realized_vol_series(
    closes: list[float],
    *,
    win: int = RV_WIN,
) -> list[float | None]:
    """Annualized sample std of 1-day returns over rolling ``win`` (None until ready)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if win < 2 or n < win + 1:
        return out
    for i in range(win, n):
        rets: list[float] = []
        ok = True
        for j in range(i - win + 1, i + 1):
            prev = closes[j - 1]
            if prev <= 0 or closes[j] <= 0:
                ok = False
                break
            rets.append(closes[j] / prev - 1.0)
        if not ok or len(rets) < 2:
            continue
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
        out[i] = math.sqrt(max(0.0, var)) * ANNUALIZE
    return out


def percentile_rank(history: list[float], value: float) -> float | None:
    """Percentile of ``value`` within ``history`` (inclusive). None if empty."""
    if not history:
        return None
    xs = sorted(float(x) for x in history)
    n = len(xs)
    # Fraction of observations ≤ value.
    le = sum(1 for x in xs if x <= value)
    return 100.0 * le / n


def rv_percentile_at(
    closes: list[float],
    *,
    win: int = RV_WIN,
    lookback: int = RV_LOOKBACK,
    end: int | None = None,
) -> dict[str, Any]:
    """RV20 annualized + percentile vs prior ``lookback`` RV observations."""
    series = realized_vol_series(closes, win=win)
    i = (len(closes) - 1) if end is None else int(end)
    if i < 0 or i >= len(series) or series[i] is None:
        return {
            "ok": False,
            "rv20": None,
            "rv_pct": None,
            "n_hist": 0,
        }
    rv = float(series[i])
    start = max(0, i - lookback + 1)
    hist = [float(v) for v in series[start : i + 1] if v is not None]
    pct = percentile_rank(hist, rv)
    return {
        "ok": True,
        "rv20": round(rv, 6),
        "rv_pct": round(pct, 2) if pct is not None else None,
        "n_hist": len(hist),
    }


def iv_percentile_series(
    iv_by_date: dict[str, float],
    dates_ymd: list[str],
    *,
    thin_n: int = IV_THIN_N,
) -> dict[str, Any]:
    """Latest IV + percentile over available history aligned to ``dates_ymd``."""
    ordered: list[tuple[str, float]] = []
    for d in dates_ymd:
        ymd = _ymd(d)
        if ymd in iv_by_date and iv_by_date[ymd] is not None:
            ordered.append((ymd, float(iv_by_date[ymd])))
    if not ordered:
        return {
            "ok": False,
            "iv": None,
            "iv_pct": None,
            "n_hist": 0,
            "iv_thin": True,
            "date": None,
        }
    vals = [v for _, v in ordered]
    last_d, last_iv = ordered[-1]
    pct = percentile_rank(vals, last_iv)
    thin = len(vals) < thin_n
    return {
        "ok": True,
        "iv": round(last_iv, 6),
        "iv_pct": round(pct, 2) if pct is not None else None,
        "n_hist": len(vals),
        "iv_thin": thin,
        "date": last_d,
    }


def vrp_value(iv: float | None, rv20: float | None) -> float | None:
    """Variance risk premium proxy: IV − current RV20 (research limitation noted)."""
    if iv is None or rv20 is None:
        return None
    return round(float(iv) - float(rv20), 6)


def iv_velocity(
    iv_by_date: dict[str, float],
    dates_ymd: list[str],
    *,
    z_win: int = 20,
) -> dict[str, Any]:
    """ΔIV vs prior session + z-score of ΔIV over recent window."""
    ordered: list[float] = []
    for d in dates_ymd:
        ymd = _ymd(d)
        if ymd in iv_by_date:
            ordered.append(float(iv_by_date[ymd]))
    if len(ordered) < 2:
        return {"ok": False, "delta_iv": None, "z": None, "n": len(ordered)}
    deltas = [ordered[i] - ordered[i - 1] for i in range(1, len(ordered))]
    delta = deltas[-1]
    window = deltas[-z_win:] if len(deltas) >= 2 else deltas
    if len(window) < 2:
        return {
            "ok": True,
            "delta_iv": round(delta, 6),
            "z": None,
            "n": len(ordered),
        }
    mu = sum(window) / len(window)
    var = sum((x - mu) ** 2 for x in window) / (len(window) - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    z = (delta - mu) / sd if sd > 1e-12 else 0.0
    return {
        "ok": True,
        "delta_iv": round(delta, 6),
        "z": round(z, 4),
        "n": len(ordered),
    }


def vol_state_score(
    rv_pct: float | None,
    iv_pct: float | None,
) -> dict[str, Any]:
    """0–100 intensity from RV/IV percentiles (prefer max of available)."""
    parts = [p for p in (rv_pct, iv_pct) if p is not None]
    if not parts:
        return {"score": None, "label": "unknown", "parts": []}
    score = round(sum(parts) / len(parts), 1)
    if score >= HIGH_PCT:
        label = "high"
    elif score <= LOW_PCT:
        label = "low"
    else:
        label = "mid"
    return {"score": score, "label": label, "parts": parts}


def vol_pricing_score(
    *,
    vrp: float | None,
    iv_pct: float | None,
    vrp_sell_min: float = VRP_SELL_MIN,
) -> dict[str, Any]:
    """Option rich/cheap: high IV% + positive VRP → rich; low IV% + neg VRP → cheap."""
    if vrp is None and iv_pct is None:
        return {"score": None, "label": "unknown", "rich": None}
    # Map to 0–100 where 100 = rich / expensive to buy vol.
    bits: list[float] = []
    if iv_pct is not None:
        bits.append(float(iv_pct))
    if vrp is not None:
        # Center VRP around sell threshold → ~50 at 0, >70 when VRP large.
        bits.append(max(0.0, min(100.0, 50.0 + (float(vrp) / max(vrp_sell_min, 1e-6)) * 25.0)))
    score = round(sum(bits) / len(bits), 1)
    if score >= HIGH_PCT or (vrp is not None and vrp >= vrp_sell_min and (iv_pct or 0) >= HIGH_PCT):
        label = "rich"
        rich = True
    elif score <= LOW_PCT or (vrp is not None and vrp < 0 and (iv_pct or 100) <= LOW_PCT):
        label = "cheap"
        rich = False
    else:
        label = "fair"
        rich = None
    return {"score": score, "label": label, "rich": rich}


def momentum_20_60(closes: list[float]) -> dict[str, Any]:
    """Path-A style 20/60 same-sign momentum on latest bar."""
    n = len(closes)
    if n < 61 or closes[-1] <= 0 or closes[-21] <= 0 or closes[-61] <= 0:
        return {"ok": False, "side": 0, "r20": None, "r60": None}
    r20 = (closes[-1] / closes[-21] - 1.0) * 100.0
    r60 = (closes[-1] / closes[-61] - 1.0) * 100.0
    same = (r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0)
    strong = abs(r20) >= 3.0 and abs(r60) >= 5.0
    side = int(math.copysign(1, r20)) if same and strong else 0
    return {
        "ok": True,
        "side": side,
        "r20": round(r20, 3),
        "r60": round(r60, 3),
    }


def trend_score_pack(
    *,
    path_a_side: int | None = None,
    path_a_selected: bool = False,
    mom_side: int = 0,
    breakout_side: int = 0,
) -> dict[str, Any]:
    """Directional research score in [-100, 100] from existing signals only."""
    score = 0.0
    if path_a_side in (1, -1):
        score += 40.0 * path_a_side * (1.25 if path_a_selected else 0.8)
    if mom_side in (1, -1):
        score += 30.0 * mom_side
    if breakout_side in (1, -1):
        score += 30.0 * breakout_side
    score = max(-100.0, min(100.0, score))
    if score > 15:
        label = "long"
        side = 1
    elif score < -15:
        label = "short"
        side = -1
    else:
        label = "flat"
        side = 0
    return {
        "score": round(score, 1),
        "label": label,
        "side": side,
        "path_a_side": path_a_side,
        "path_a_selected": bool(path_a_selected),
        "mom_side": mom_side,
        "breakout_side": breakout_side,
    }


def calendar_candidate(
    iv_near: float | None,
    iv_far: float | None,
    *,
    ratio_min: float = CALENDAR_RATIO,
) -> dict[str, Any]:
    """Near-month IV clearly above far → calendar / roll-vol research stub."""
    if iv_near is None or iv_far is None or iv_far <= 0:
        return {"ok": False, "tag": None, "ratio": None}
    ratio = float(iv_near) / float(iv_far)
    hit = ratio >= ratio_min
    return {
        "ok": True,
        "tag": "calendar_candidate" if hit else None,
        "ratio": round(ratio, 4),
        "iv_near": round(float(iv_near), 6),
        "iv_far": round(float(iv_far), 6),
    }


def sentiment_tier(
    *,
    direction: str | None,
    conviction_pct: float | None,
    ref_side: int = 0,
) -> dict[str, Any]:
    """Bucket portfolio sentiment vs trend/Path-A reference side.

    Tiers (research defaults I set):
    - neutral: 震荡 / |把握|<40
    - directed: 有方向但无参考趋势
    - aligned: 与参考同向、把握≥40
    - extreme_crowd: 同向且把握≥75（拥挤）
    - opposed_soft: 反向、把握 40–60
    - opposed_hard: 反向、把握≥60（对齐最终信号硬否决）
    """
    text = str(direction or "").strip()
    if text in ("多", "偏多", "long", "risk_on"):
        dir_side = 1
    elif text in ("空", "偏空", "short", "risk_off"):
        dir_side = -1
    else:
        dir_side = 0
    try:
        conv = float(conviction_pct) if conviction_pct is not None else 0.0
    except (TypeError, ValueError):
        conv = 0.0
    conv = max(0.0, min(100.0, conv))
    ref = int(ref_side or 0)

    if dir_side == 0 or conv < SENT_SOFT_CONV:
        tier = "neutral"
        align = "neutral"
    elif ref != 0 and dir_side == -ref:
        align = "opposed"
        tier = "opposed_hard" if conv >= SENT_HARD_CONV else "opposed_soft"
    elif ref != 0 and dir_side == ref:
        align = "aligned"
        tier = "extreme_crowd" if conv >= SENT_EXTREME_CONV else "aligned"
    else:
        # Directed sentiment, flat trend reference.
        align = "directed"
        tier = "extreme_crowd" if conv >= SENT_EXTREME_CONV else "directed"

    return {
        "tier": tier,
        "align": align,
        "direction": text or "—",
        "dir_side": dir_side,
        "conviction_pct": round(conv, 1),
        "ref_side": ref,
        "label": f"{tier}/{text or '—'}·{conv:.0f}%",
    }


def apply_sentiment_vol_overlay(
    tags: list[str],
    reasons: list[str],
    *,
    sent: dict[str, Any] | None,
    pricing_label: str | None = None,
    iv_high: bool = False,
    true_bo: bool = False,
) -> tuple[list[str], list[str]]:
    """Adjust matrix tags after raw vol rules — concrete combo gates."""
    tags = list(tags)
    reasons = list(reasons)
    sent = sent or {}
    tier = str(sent.get("tier") or "neutral")
    buy_set = {"buy_vol_breakout", "buy_call_or_put"}

    def _strip_buy(msg: str) -> None:
        nonlocal tags
        if any(t in buy_set for t in tags):
            tags = [t for t in tags if t not in buy_set]
            reasons.append(msg)

    # 1) Hard / soft opposed → kill buy-vol chase.
    if tier == "opposed_hard":
        _strip_buy("情绪硬反向(把握≥60) → 压制买波/追方向")
    elif tier == "opposed_soft":
        _strip_buy("情绪软反向(把握40–60) → 买波降观望")

    # 2) Extreme crowd: don't chase buy-vol into rich/high IV; need true breakout.
    if tier == "extreme_crowd":
        richish = (pricing_label == "rich") or iv_high
        if richish:
            _strip_buy("情绪拥挤+波动偏贵 → 不追买波")
        elif any(t in buy_set for t in tags) and not true_bo:
            _strip_buy("情绪拥挤且非真突破确认 → 压低买波")
        # Crowd + sell already tagged: strengthen annotate note.
        if "sell_vol_credit_spread" in tags:
            reasons.append("情绪拥挤同向+卖波条件 → 卖方研究加强（仅标注）")

    # 3) Aligned mid: keep buy; annotate direction support.
    if tier == "aligned" and any(t in buy_set for t in tags):
        reasons.append("情绪同向加强方向研究（非反向策略）")

    # 4) Neutral: no change (noise).
    return tags, reasons


def select_strategy(
    *,
    rv_pct: float | None,
    iv_pct: float | None,
    vrp: float | None,
    iv_z: float | None,
    delta_iv: float | None,
    breakout_side: int = 0,
    breakout_iv_tag: str | None = None,
    iv_thin: bool = False,
    calendar: dict[str, Any] | None = None,
    low_pct: float = LOW_PCT,
    high_pct: float = HIGH_PCT,
    vrp_sell_min: float = VRP_SELL_MIN,
    sentiment: dict[str, Any] | None = None,
    pricing_label: str | None = None,
) -> dict[str, Any]:
    """Rule matrix → research tag (no orders).

    Tags: buy_vol_breakout, buy_call_or_put, sell_vol_credit_spread,
    calendar_candidate, no_trade, research_stub.
    """
    reasons: list[str] = []
    tags: list[str] = []

    # False-breakout dampens buy-vol.
    false_bo = breakout_iv_tag in ("false_suspect", "iv_flat")
    true_bo = breakout_iv_tag == "true_candidate"
    strong_bo = breakout_side != 0 and true_bo
    any_bo = breakout_side != 0

    rv_low = rv_pct is not None and rv_pct <= low_pct
    iv_low = iv_pct is not None and iv_pct <= low_pct
    iv_high = iv_pct is not None and iv_pct >= high_pct
    vol_low = rv_low or iv_low
    iv_falling = (iv_z is not None and iv_z <= IV_FALL_Z) or (
        delta_iv is not None and delta_iv < 0
    )
    vrp_rich = vrp is not None and vrp >= vrp_sell_min

    # Strategy 1/3: buy vol on low-vol breakout when IV not fully expanded.
    # "IV未充分扩张" ≈ not false_suspect and IV percentile not already extreme-high.
    if vol_low and any_bo and not false_bo:
        if iv_high:
            reasons.append("低波突破但IV分位已高 → 压低买波")
        elif true_bo or breakout_iv_tag in (None, "", "iv_missing"):
            tags.append("buy_vol_breakout")
            tags.append("buy_call_or_put")
            reasons.append("低波分位+突破确认且IV未充分扩张 → 买波/方向期权研究")
        else:
            reasons.append(f"突破IV标签={breakout_iv_tag} → 买波观望")

    # Strategy 2: sell vol credit spread (annotate only).
    if iv_high and vrp_rich and iv_falling and not strong_bo:
        tags.append("sell_vol_credit_spread")
        reasons.append("高IV分位+正VRP+IV回落且无强真突破 → 卖方信用价差研究（仅标注）")

    # Strategy 4: calendar when near >> far.
    cal = calendar or {}
    if cal.get("tag") == "calendar_candidate":
        tags.append("calendar_candidate")
        reasons.append(
            f"近月IV/远月IV={cal.get('ratio')} ≥ 阈 → 日历价差候选"
        )

    # Strategy 5/6 stubs.
    if iv_thin:
        tags.append("research_stub")
        reasons.append("IV样本偏薄；偏斜/Gamma对冲仅占位")

    # Sentiment × vol overlay (concrete tiers).
    tags, reasons = apply_sentiment_vol_overlay(
        tags,
        reasons,
        sent=sentiment,
        pricing_label=pricing_label,
        iv_high=iv_high,
        true_bo=true_bo,
    )

    # Conflicts / unclear → no_trade.
    buy = "buy_vol_breakout" in tags or "buy_call_or_put" in tags
    sell = "sell_vol_credit_spread" in tags
    if buy and sell:
        tags = ["no_trade"]
        reasons = ["买波与卖波条件冲突 → 明确空仓"]
    elif false_bo and buy:
        tags = ["no_trade"]
        reasons = ["假突破嫌疑压制买波 → 观望"]
    elif not tags:
        tags = ["no_trade"]
        sent_tier = str((sentiment or {}).get("tier") or "")
        if sent_tier in ("opposed_hard", "opposed_soft"):
            reasons = [f"情绪{sent_tier}且无独立卖波条件 → 空仓/观望"] + reasons
        else:
            reasons = ["条件不清晰 → 空仓/观望"] + ([r for r in reasons if r][:2] or [])

    # Deduplicate empty / keep primary.
    tags = tags or ["no_trade"]
    primary = tags[0]
    # If buy stripped and only stubs left → no_trade.
    if primary == "research_stub" and len(tags) == 1 and not buy and not sell:
        tags = ["no_trade", "research_stub"]
        primary = "no_trade"
        if not any("空仓" in r or "观望" in r for r in reasons):
            reasons.insert(0, "仅余研究占位 → 空仓/观望")

    return {
        "tag": primary,
        "tags": tags,
        "reason": "；".join(reasons) if reasons else "—",
        "false_breakout": false_bo,
        "buy_vol": buy and primary != "no_trade",
        "sell_vol": sell and primary != "no_trade",
        "sentiment_tier": (sentiment or {}).get("tier"),
        "sentiment_align": (sentiment or {}).get("align"),
    }


def latest_breakout_side(bars: list[dict], *, window: int = 20) -> dict[str, Any]:
    """Most recent Donchian breakout on/near last bar (side 0 if none today)."""
    from iv_breakout import detect_breakouts

    events = detect_breakouts(bars, window=window)
    if not events:
        return {"side": 0, "date": None, "event": None}
    last = events[-1]
    # Only treat as active if breakout is on the latest bar.
    last_bar_date = _ymd(str((bars[-1] or {}).get("date") or ""))
    if _ymd(str(last.get("date") or "")) != last_bar_date:
        return {"side": 0, "date": last.get("date"), "event": last, "stale": True}
    return {
        "side": int(last.get("side") or 0),
        "date": last.get("date"),
        "event": last,
        "stale": False,
    }


def _path_a_side_from_report(sig: dict | None) -> tuple[int | None, bool]:
    if not isinstance(sig, dict):
        return None, False
    selected = bool(sig.get("selected"))
    direction = str(sig.get("direction") or "").strip()
    if direction in ("多", "偏多"):
        return 1, selected
    if direction in ("空", "偏空"):
        return -1, selected
    return 0, selected


def _load_l1_sig_map(root: Path) -> dict[str, dict]:
    path = Path(root) / "l1_report.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    out: dict[str, dict] = {}
    for row in data.get("signals") or []:
        if isinstance(row, dict) and row.get("code"):
            out[str(row["code"]).upper()] = row
    return out


def _term_structure_shfe(root: Path, code: str, trade_date: str) -> dict[str, Any]:
    """Best-effort near vs next series IV from SHFE table (optional network)."""
    from iv_breakout import CODE_TO_OPTION, _cache_dir, _num, _read_json, _ymd as ymd_fn

    meta = CODE_TO_OPTION.get(code.upper())
    if not meta or meta[0] != "shfe":
        return {"ok": False}
    ymd = ymd_fn(trade_date)
    # Prefer fields already on front-IV cache if present.
    cache = _cache_dir(root) / code.upper() / f"{ymd}.json"
    cached = _read_json(cache)
    if isinstance(cached, dict) and cached.get("iv_far") is not None and cached.get("iv"):
        return calendar_candidate(
            float(cached["iv"]),
            float(cached["iv_far"]),
        ) | {"ok": True, "source": "cache"}

    try:
        import akshare as ak
    except ImportError:
        return {"ok": False, "error": "no_akshare"}
    product = meta[1]
    try:
        frame = ak.option_vol_shfe(symbol=product, trade_date=ymd)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:120]}"}
    if frame is None or getattr(frame, "empty", True):
        return {"ok": False}
    iv_col = "隐含波动率" if "隐含波动率" in frame.columns else None
    vol_col = "成交量" if "成交量" in frame.columns else None
    ser_col = "合约系列" if "合约系列" in frame.columns else frame.columns[0]
    if iv_col is None:
        return {"ok": False}
    rows: list[tuple[str, float, float]] = []
    for _, row in frame.iterrows():
        iv = _num(row.get(iv_col))
        if iv is None or iv <= 0:
            continue
        if iv > 3.0:
            iv = iv / 100.0
        vol = _num(row.get(vol_col)) if vol_col else 0.0
        rows.append((str(row.get(ser_col) or ""), float(iv), float(vol or 0.0)))
    if len(rows) < 2:
        return {"ok": False, "n_series": len(rows)}
    # Sort by series label (month code) then pick top-2 by volume among earliest months.
    rows.sort(key=lambda r: r[0])
    # Take two distinct series with highest volume among first 4 months listed.
    by_ser: dict[str, tuple[float, float]] = {}
    for ser, iv, vol in rows:
        prev = by_ser.get(ser)
        if prev is None or vol > prev[1]:
            by_ser[ser] = (iv, vol)
    ordered = sorted(by_ser.items(), key=lambda kv: kv[0])[:4]
    if len(ordered) < 2:
        return {"ok": False}
    # Near = earliest series; far = next; prefer volume for near if tied.
    near_ser, (iv_n, _) = ordered[0]
    far_ser, (iv_f, _) = ordered[1]
    cal = calendar_candidate(iv_n, iv_f)
    cal["ok"] = True
    cal["near_series"] = near_ser
    cal["far_series"] = far_ser
    cal["source"] = "shfe_live"
    return cal


def evaluate_code(
    root: Path,
    code: str,
    bars: list[dict],
    *,
    cfg: dict | None = None,
    iv_by_date: dict[str, float] | None = None,
    path_a_sig: dict | None = None,
    sentiment_snap: dict | None = None,
    refresh_iv: bool = False,
    max_iv_fetch: int = 80,
    fetch_calendar: bool = False,
) -> dict[str, Any]:
    """Full V1 pack for one code (paper research)."""
    from iv_breakout import (
        classify_breakout_iv,
        load_iv_series,
        option_meta,
    )

    conf = vol_engine_cfg(cfg)
    code = str(code or "").upper()
    meta = option_meta(code)
    closes, dates = _closes(bars)
    if len(closes) < conf["rv_win"] + 5:
        return {
            "ok": False,
            "code": code,
            "error": "bars_short",
            "live_trading": False,
        }

    rv_pack = rv_percentile_at(
        closes,
        win=int(conf["rv_win"]),
        lookback=int(conf["rv_lookback"]),
    )
    # IV: load for recent bar dates (cache-first).
    ymds = [_ymd(d) for d in dates if len(_ymd(d)) == 8]
    need = ymds[-max(60, int(conf["iv_thin_n"]) + 5) :]
    if iv_by_date is None:
        iv_by_date = load_iv_series(
            root,
            code,
            need,
            refresh=refresh_iv,
            max_fetch=max_iv_fetch,
        )
    iv_pack = iv_percentile_series(
        iv_by_date,
        need,
        thin_n=int(conf["iv_thin_n"]),
    )
    vel = iv_velocity(iv_by_date, need)
    vrp = vrp_value(iv_pack.get("iv"), rv_pack.get("rv20"))
    state = vol_state_score(rv_pack.get("rv_pct"), iv_pack.get("iv_pct"))
    pricing = vol_pricing_score(
        vrp=vrp,
        iv_pct=iv_pack.get("iv_pct"),
        vrp_sell_min=float(conf["vrp_sell_min"]),
    )

    mom = momentum_20_60(closes)
    bo = latest_breakout_side(bars, window=20)
    # IV tag on breakout day (or latest vs prev for context).
    last_ymd = ymds[-1] if ymds else ""
    prev_ymd = ymds[-2] if len(ymds) >= 2 else ""
    bo_ymd = _ymd(str((bo.get("event") or {}).get("date") or last_ymd))
    # Find prev trading ymd before breakout.
    prev_of = ""
    for i, d in enumerate(ymds):
        if d == bo_ymd and i > 0:
            prev_of = ymds[i - 1]
            break
    if not prev_of:
        prev_of = prev_ymd
    iv_tag = classify_breakout_iv(
        iv_today=iv_by_date.get(bo_ymd) if bo_ymd else iv_by_date.get(last_ymd),
        iv_prev=iv_by_date.get(prev_of) if prev_of else None,
    )

    pa_side, pa_sel = _path_a_side_from_report(path_a_sig)
    trend = trend_score_pack(
        path_a_side=pa_side,
        path_a_selected=pa_sel,
        mom_side=int(mom.get("side") or 0),
        breakout_side=int(bo.get("side") or 0),
    )

    # Portfolio sentiment vs this name's trend reference.
    if sentiment_snap is None:
        try:
            from desk.sentiment_panel import load_sentiment_snapshot, sentiment_verdict

            sentiment_snap = load_sentiment_snapshot(root)
            sent_verdict = sentiment_verdict(sentiment_snap)
        except Exception:  # noqa: BLE001
            sent_verdict = {
                "direction": "样本不足",
                "conviction_pct": 0.0,
            }
    else:
        try:
            from desk.sentiment_panel import sentiment_verdict

            sent_verdict = sentiment_verdict(sentiment_snap)
        except Exception:  # noqa: BLE001
            sent_verdict = {
                "direction": str((sentiment_snap or {}).get("direction") or "样本不足"),
                "conviction_pct": (sentiment_snap or {}).get("conviction_pct") or 0.0,
            }

    ref_side = int(trend.get("side") or 0)
    if ref_side == 0 and pa_side in (1, -1):
        ref_side = int(pa_side)
    if ref_side == 0 and int(bo.get("side") or 0) != 0 and not bo.get("stale"):
        ref_side = int(bo.get("side") or 0)
    sent = sentiment_tier(
        direction=sent_verdict.get("direction"),
        conviction_pct=sent_verdict.get("conviction_pct"),
        ref_side=ref_side,
    )

    calendar: dict[str, Any] = {"ok": False}
    if fetch_calendar and meta and meta[0] == "shfe" and last_ymd:
        calendar = _term_structure_shfe(root, code, last_ymd)

    matrix = select_strategy(
        rv_pct=rv_pack.get("rv_pct"),
        iv_pct=iv_pack.get("iv_pct"),
        vrp=vrp,
        iv_z=vel.get("z"),
        delta_iv=vel.get("delta_iv"),
        breakout_side=int(bo.get("side") or 0),
        breakout_iv_tag=str(iv_tag.get("tag") or ""),
        iv_thin=bool(iv_pack.get("iv_thin")),
        calendar=calendar if calendar.get("ok") else None,
        low_pct=float(conf["low_pct"]),
        high_pct=float(conf["high_pct"]),
        vrp_sell_min=float(conf["vrp_sell_min"]),
        sentiment=sent,
        pricing_label=str(pricing.get("label") or ""),
    )

    return {
        "ok": True,
        "code": code,
        "product": meta[1] if meta else None,
        "venue": meta[0] if meta else None,
        "live_trading": False,
        "asof": last_ymd or _ymd(dates[-1] if dates else ""),
        "bars_n": len(closes),
        "iv_days": len(iv_by_date),
        "rv": rv_pack,
        "iv": iv_pack,
        "vrp": vrp,
        "iv_velocity": vel,
        "vol_state": state,
        "vol_pricing": pricing,
        "trend": trend,
        "sentiment": sent,
        "momentum": mom,
        "breakout": {
            "side": bo.get("side"),
            "date": bo.get("date"),
            "stale": bo.get("stale"),
            "iv_tag": iv_tag.get("tag"),
            "delta_iv": iv_tag.get("delta_iv"),
        },
        "calendar": calendar,
        "matrix": matrix,
        "cfg": {
            "action": conf["action"],
            "low_pct": conf["low_pct"],
            "high_pct": conf["high_pct"],
            "vrp_sell_min": conf["vrp_sell_min"],
        },
        "note": "研究筛选；卖波仅 annotate；情绪分档叠加；不改 Path-A 入场。",
    }


def run_universe(
    root: Path,
    codes: list[str] | None = None,
    *,
    cfg: dict | None = None,
    refresh_iv: bool = False,
    fetch_calendar: bool = False,
    write_data: bool = True,
    write_oos: bool = True,
) -> dict[str, Any]:
    """Evaluate codes and optionally write desk + OOS JSON."""
    from desk.regime_board import load_local_bars

    root = Path(root)
    codes = [c.strip().upper() for c in (codes or list(DEFAULT_CODES)) if c.strip()]
    sig_map = _load_l1_sig_map(root)
    try:
        from desk.sentiment_panel import load_sentiment_snapshot

        sentiment_snap = load_sentiment_snapshot(root)
    except Exception:  # noqa: BLE001
        sentiment_snap = None
    reports: list[dict[str, Any]] = []
    tag_hist: dict[str, dict[str, int]] = {}

    for code in codes:
        bars, source = load_local_bars(root, code)
        print(f"[vol] {code} bars={len(bars)} source={source}")
        if len(bars) < 40:
            pack = {"ok": False, "code": code, "error": "bars_short", "live_trading": False}
            reports.append(pack)
            continue
        pack = evaluate_code(
            root,
            code,
            bars,
            cfg=cfg,
            path_a_sig=sig_map.get(code),
            sentiment_snap=sentiment_snap,
            refresh_iv=refresh_iv,
            fetch_calendar=fetch_calendar,
        )
        tag = ((pack.get("matrix") or {}).get("tag")) or "n/a"
        print(
            f"  tag={tag} rv_pct={(pack.get('rv') or {}).get('rv_pct')} "
            f"iv_pct={(pack.get('iv') or {}).get('iv_pct')} vrp={pack.get('vrp')} "
            f"state={(pack.get('vol_state') or {}).get('label')} "
            f"pricing={(pack.get('vol_pricing') or {}).get('label')}"
        )
        reports.append(pack)
        # Near-window tag distribution: reuse matrix tag only (single snapshot);
        # optional historical would need full path — V1 stores current + counts.
        th = tag_hist.setdefault(code, {})
        th[tag] = th.get(tag, 0) + 1

    # Enrich tag distribution with a short rolling window when IV history allows.
    for pack in reports:
        if not pack.get("ok"):
            continue
        code = pack["code"]
        # Soft: count recent breakout-day tags from breakout field only (1 obs).
        dist = dict(tag_hist.get(code) or {})
        pack["tag_window"] = {"n": sum(dist.values()), "counts": dist}

    payload = {
        "ok": True,
        "live_trading": False,
        "entry_filter_unchanged": "seats",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "codes": codes,
        "reports": reports,
        "tag_distribution": tag_hist,
        "note": "波动率引擎 V1 研究台；卖波 soft-annotate；无裸卖跨式/完整对冲。",
    }

    if write_data:
        dest = root / "data" / "vol_engine_latest.json"
        _write_json(dest, payload)
        print(f"[vol] wrote {dest}")
    if write_oos:
        dest = root / "lab" / "research" / "oos" / "vol_engine_latest.json"
        _write_json(dest, payload)
        print(f"[vol] wrote {dest}")
    return payload


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Volatility Engine V1 (paper research)")
    p.add_argument(
        "--codes",
        default=",".join(DEFAULT_CODES),
        help="comma-separated Path-A codes",
    )
    p.add_argument("--refresh-iv", action="store_true")
    p.add_argument("--calendar", action="store_true", help="fetch SHFE term structure")
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args()
    codes = [c.strip().upper() for c in str(args.codes).split(",") if c.strip()]
    run_universe(
        ROOT,
        codes,
        refresh_iv=bool(args.refresh_iv),
        fetch_calendar=bool(args.calendar),
        write_data=not args.no_write,
        write_oos=not args.no_write,
    )


if __name__ == "__main__":
    main()
