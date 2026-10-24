# -*- coding: utf-8 -*-
"""P0 measurement gates and P1 entry filters. Exits stay on ATR and trend flip."""
from __future__ import annotations


def fill_cost(meta: dict, price, lots, slippage_ticks: float = 1.0) -> float:
    """One fill: 1 tick of slippage plus the posted per-side fee."""
    lots = abs(int(lots or 0))
    if lots <= 0 or price is None:
        return 0.0
    mult = float(meta.get("mult") or 0)
    tick = float(meta.get("tick") or 0)
    slip = abs(float(slippage_ticks)) * tick * mult * lots
    rate = float(meta.get("fee_rate") or 0)
    yuan = float(meta.get("fee_yuan") or 0)
    fee = 0.0
    if rate:
        fee += abs(float(price)) * mult * lots * rate
    if yuan:
        fee += yuan * lots
    return slip + fee


def measurement_reason(hist: list[dict], i: int, atr, max_atr_pct: float = 8.0) -> str | None:
    """Block a new entry when the bar cannot support an ATR position."""
    bar = hist[i]
    vol = bar.get("volume")
    if vol is None or vol <= 0:
        return "缺成交量"
    close = bar.get("close")
    if atr is None or close is None or close <= 0 or atr <= 0:
        return "缺ATR"
    if atr / close > max_atr_pct / 100.0:
        return "ATR超过收盘8%"
    return None


def oi_reason(hist: list[dict], i: int, direction: str) -> str | None:
    """Long needs OI up. Short needs price down and OI up. Missing OI stays open."""
    if i < 1:
        return None
    oi = hist[i].get("open_interest")
    prev = hist[i - 1].get("open_interest")
    if oi is None or prev is None:
        return None
    price_up = hist[i]["close"] > hist[i - 1]["close"]
    price_dn = hist[i]["close"] < hist[i - 1]["close"]
    oi_up = oi > prev
    if direction == "多":
        if price_up and oi < prev:
            return "上涨减仓"
        if not oi_up:
            return "持仓未增"
        return None
    if not (price_dn and oi_up):
        return "空头需价跌仓增"
    return None


def climax_reason(hist: list[dict], i: int) -> str | None:
    if i < 20:
        return "缺均量"
    vols = []
    for j in range(i - 20, i):
        v = hist[j].get("volume")
        if v is None or v <= 0:
            return "缺均量"
        vols.append(float(v))
    avg = sum(vols) / len(vols)
    today = hist[i].get("volume")
    if today is None or avg <= 0:
        return "缺均量"
    if float(today) > 3 * avg:
        return "高潮日"
    return None


def bucket_reason(direction: str, peer_r20: list[float]) -> str | None:
    vals = sorted(v for v in peer_r20 if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        med = vals[mid]
    else:
        med = (vals[mid - 1] + vals[mid]) / 2
    if direction == "多" and med < 0:
        return "板块中位数反向"
    if direction == "空" and med > 0:
        return "板块中位数反向"
    return None


def carry_reason(direction: str, pair) -> str | None:
    if not pair:
        return "缺升贴水"
    front, nxt = pair
    if front is None or nxt is None:
        return "缺升贴水"
    if direction == "多" and front < nxt:
        return "近月低于次月"
    if direction == "空" and front > nxt:
        return "近月高于次月"
    return None


def carry_gap_pct(pair) -> float | None:
    """Relative front→next gap in percent. Positive = contango (升水)."""
    if not pair or len(pair) < 2:
        return None
    try:
        front, nxt = float(pair[0]), float(pair[1])
    except (TypeError, ValueError):
        return None
    if front <= 0:
        return None
    return (nxt - front) / front * 100.0


def carry_bypass_cfg(raw: dict | None = None) -> dict:
    """Normalize universe/execution carry_bypass block. Default off-safe."""
    src = raw if isinstance(raw, dict) else {}
    action = str(src.get("action") or "block").strip().lower()
    if action not in ("block", "scale"):
        action = "block"
    try:
        thr = float(src.get("extreme_gap_pct") if src.get("extreme_gap_pct") is not None else 1.0)
    except (TypeError, ValueError):
        thr = 1.0
    try:
        scale = float(src.get("scale") if src.get("scale") is not None else 0.5)
    except (TypeError, ValueError):
        scale = 0.5
    return {
        "enabled": bool(src.get("enabled")),
        "extreme_gap_pct": max(0.0, thr),
        "action": action,
        "scale": min(1.0, max(0.0, scale)),
        "note": str(src.get("note") or ""),
    }


def carry_bypass_decision(
    direction: str,
    pair,
    *,
    extreme_gap_pct: float = 1.0,
    action: str = "block",
    scale: float = 0.5,
) -> tuple[str | None, float, str, float | None]:
    """Soft carry extreme gate for NEW entries (does not replace entry_filter).

    Contango (gap ≥ thr): long is adverse → block or scale 多.
    Backwardation (gap ≤ −thr): short is adverse → block or scale 空.
    Missing pair does not block (scale=1, label=缺升贴水).
    Returns (block_reason|None, lots_mult, label, gap_pct).
    """
    gap = carry_gap_pct(pair)
    if gap is None:
        return None, 1.0, "缺升贴水", None
    thr = abs(float(extreme_gap_pct or 0.0))
    if thr <= 0:
        return None, 1.0, "旁路关闭", gap
    if direction == "多" and gap >= thr:
        label = f"升水极端(+{gap:.2f}%)"
        if action == "scale":
            return None, float(scale), f"{label}·减仓", gap
        return "升水极端禁开多", 0.0, label, gap
    if direction == "空" and gap <= -thr:
        label = f"贴水极端({gap:.2f}%)"
        if action == "scale":
            return None, float(scale), f"{label}·减仓", gap
        return "贴水极端禁开空", 0.0, label, gap
    side = "升水" if gap > 0 else ("贴水" if gap < 0 else "平水")
    return None, 1.0, f"{side}{gap:+.2f}%·放行", gap


def member_reason(direction: str, change) -> str | None:
    """Missing member change does not block. Opposite top-20 net-long change does."""
    if change is None:
        return None
    if direction == "多" and change < 0:
        return "会员净多下降"
    if direction == "空" and change > 0:
        return "会员净多上升"
    return None


def _seat_side(net) -> int:
    if net is None:
        return 0
    try:
        val = float(net)
    except (TypeError, ValueError):
        return 0
    if val > 0:
        return 1
    if val < 0:
        return -1
    return 0


def seat_decision(direction: str, book) -> tuple[str | None, str]:
    """Confirm a 20/60 entry with member seats. Never opens the other side.

    Order: follow 机构, then 外资, then the opposite of 家人.
    A seat that points against the trend blocks the entry. That is the
    one-sided rule: do not buy the dip or sell the rally.
    A missing book does not block.
    """
    if not isinstance(book, dict):
        return None, "缺席位"
    want = 1 if direction == "多" else -1
    inst = _seat_side(book.get("inst"))
    foreign = _seat_side(book.get("foreign"))
    holder = _seat_side(book.get("holder"))
    if inst == want:
        return None, "跟随机构"
    if inst == -want:
        return "机构席位反向", "机构席位反向"
    if foreign == want:
        return None, "跟随外资"
    if foreign == -want:
        return "外资席位反向", "外资席位反向"
    if holder == -want:
        return None, "家人对立"
    if holder == want:
        return "与家人同向", "与家人同向"
    return None, "席位持平"


def entry_block(
    mode: str,
    hist: list[dict],
    i: int,
    direction: str,
    day: str,
    code: str,
    atr,
    curves: dict,
    member: dict,
    peer_r20: list[float],
    max_atr_pct: float = 8.0,
) -> str | None:
    if mode == "base":
        return None
    if mode == "seats":
        book = (member.get(code) or {}).get(day)
        return seat_decision(direction, book)[0]
    reason = measurement_reason(hist, i, atr, max_atr_pct)
    if reason:
        return reason
    roll = (curves.get(code) or {}).get("roll_dates") or set()
    if day in roll:
        return "换月窗口"
    if mode == "carry":
        pair = ((curves.get(code) or {}).get("carry") or {}).get(day)
        return carry_reason(direction, pair)
    if mode == "oi":
        return oi_reason(hist, i, direction)
    if mode == "member":
        change = (member.get(code) or {}).get(day)
        return member_reason(direction, change)
    if mode == "climax":
        reason = climax_reason(hist, i)
        if reason:
            return reason
        return bucket_reason(direction, peer_r20)
    return None
