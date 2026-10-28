# -*- coding: utf-8 -*-
"""Research credibility gates for Path-A paper reports (no live orders).

Blocks formal signal/backtest artifacts when calendar or ATR sanity fails.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def parse_ymd(value: str | None) -> date | None:
    s = str(value or "").strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def atr_close_ok(close: float | None, atr: float | None, *, max_ratio: float = 0.25) -> bool:
    """ATR should be a fraction of price; reject absurd scales."""
    if close is None or atr is None:
        return False
    try:
        c = float(close)
        a = float(atr)
    except (TypeError, ValueError):
        return False
    if c <= 0 or a < 0:
        return False
    if a == 0:
        return True
    return a < c * float(max_ratio)


def validate_bar_date(
    bar_date: str | None,
    *,
    asof: str | None = None,
    today: date | None = None,
    allow_future_days: int = 0,
) -> tuple[bool, str]:
    d = parse_ymd(bar_date)
    if d is None:
        return False, "bar_date_unparsed"
    if not is_weekday(d):
        return False, "bar_date_weekend"
    ref = parse_ymd(asof) or (today or date.today())
    if d > ref + timedelta(days=max(0, int(allow_future_days))):
        return False, "bar_date_future"
    return True, "ok"


def validate_signal_row(row: dict[str, Any], *, asof: str | None = None) -> list[str]:
    """Return list of failure codes (empty = pass). Soft fields may skip."""
    fails: list[str] = []
    code = str(row.get("code") or "?")
    close = row.get("close")
    atr = row.get("atr")
    if close is not None and atr is not None and not atr_close_ok(close, atr):
        fails.append(f"{code}:atr_vs_close")
    bar = row.get("bar_date") or row.get("date")
    ok, reason = validate_bar_date(str(bar) if bar else None, asof=asof)
    if not ok and bar:
        fails.append(f"{code}:{reason}")
    return fails


def validate_signals(
    signals: list[dict[str, Any]],
    *,
    asof: str | None = None,
    max_bad_ratio: float = 0.15,
) -> dict[str, Any]:
    """Gate a daily signal list. Fail hard if too many ATR/date anomalies."""
    bad: list[str] = []
    checked = 0
    for row in signals:
        if not isinstance(row, dict):
            continue
        if row.get("close") is None and row.get("atr") is None:
            continue
        checked += 1
        bad.extend(validate_signal_row(row, asof=asof))
    n = max(checked, 1)
    ratio = len({b.split(":")[0] for b in bad}) / n
    # Count unique codes with failures
    bad_codes = sorted({b.split(":")[0] for b in bad})
    ok = len(bad_codes) / n <= float(max_bad_ratio) and not any(
        "bar_date_future" in b or "bar_date_weekend" in b for b in bad
    )
    # Any future/weekend bar is hard fail
    hard = [b for b in bad if "bar_date_future" in b or "bar_date_weekend" in b]
    if hard:
        ok = False
    return {
        "ok": ok,
        "checked": checked,
        "bad_n": len(bad_codes),
        "bad_codes": bad_codes,
        "failures": bad[:80],
        "bad_ratio": round(ratio, 4),
        "asof": asof,
    }


def validate_backtest_meta(meta: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Reject backtest reports with impossible end dates / day counts."""
    today = today or date.today()
    end = parse_ymd(str(meta.get("end") or ""))
    start = parse_ymd(str(meta.get("start") or ""))
    fails: list[str] = []
    if end is None:
        fails.append("end_unparsed")
    else:
        if end > today:
            fails.append("end_in_future")
        if not is_weekday(end):
            fails.append("end_weekend")
    trade_days = meta.get("trade_days")
    if start and end and trade_days is not None:
        try:
            td = int(trade_days)
        except (TypeError, ValueError):
            td = -1
        cal = (end - start).days + 1
        # Futures sessions ≪ calendar days; if trade_days ≈ calendar span, suspect.
        if td > 0 and cal > 0 and td >= int(cal * 0.95):
            fails.append("trade_days_looks_like_calendar")
        if td > 320 and start and end and (end - start).days < 400:
            # ~1y window should be ~240 sessions, not 367
            fails.append("trade_days_too_dense")
    return {"ok": not fails, "failures": fails, "end": str(end or ""), "start": str(start or "")}
