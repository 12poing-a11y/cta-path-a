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
    universe: list[dict[str, Any]] | None = None,
    max_bad_ratio: float = 0.0,
) -> dict[str, Any]:
    """Strict pre-publication gate for required fields, prices, ATR and contract metadata."""
    import math

    failures: list[str] = []
    rows = [row for row in signals if isinstance(row, dict)]
    expected = {
        str(item.get("code") or "").upper(): item
        for item in (universe or [])
        if isinstance(item, dict) and item.get("code")
    }
    seen: set[str] = set()
    counts: dict[str, int] = {}
    optional_missing: dict[str, list[str]] = {}
    for row in rows:
        code = str(row.get("code") or "?").upper()
        counts[code] = counts.get(code, 0) + 1
        if code in seen:
            failures.append(f"{code}:duplicate_code")
        seen.add(code)
        required = ("close", "atr", "r20", "r60", "bar_date", "mult")
        missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
        if missing:
            failures.extend(f"{code}:missing_{key}" for key in missing)
            continue

        numeric: dict[str, float] = {}
        for key in ("close", "atr", "r20", "r60", "mult"):
            try:
                numeric[key] = float(row[key])
            except (TypeError, ValueError):
                failures.append(f"{code}:invalid_{key}")
        if len(numeric) != 5:
            continue
        if any(not math.isfinite(value) for value in numeric.values()):
            failures.append(f"{code}:non_finite_numeric")
            continue

        close = numeric["close"]
        atr = numeric["atr"]
        if close <= 0 or close > 1_000_000:
            failures.append(f"{code}:price_out_of_range")
        if atr <= 0:
            failures.append(f"{code}:atr_non_positive")
        elif close > 0 and atr >= close * 0.25:
            failures.append(f"{code}:atr_vs_close")

        cfg = expected.get(code)
        if expected and cfg is None:
            failures.append(f"{code}:not_in_universe")
        elif cfg is not None:
            try:
                expected_mult = float(cfg.get("mult"))
                if not math.isclose(numeric["mult"], expected_mult, rel_tol=0.0, abs_tol=1e-9):
                    failures.append(f"{code}:multiplier_mismatch")
            except (TypeError, ValueError):
                failures.append(f"{code}:universe_multiplier_invalid")
            try:
                tick = float(cfg.get("tick") or 0)
                if tick > 0 and close > 0:
                    ticks = close / tick
                    if abs(ticks - round(ticks)) > 1e-5:
                        failures.append(f"{code}:price_off_tick")
            except (TypeError, ValueError):
                failures.append(f"{code}:universe_tick_invalid")

        ok, reason = validate_bar_date(str(row.get("bar_date")), asof=asof)
        if not ok:
            failures.append(f"{code}:{reason}")

        absent_optional = [
            key for key in ("volume", "oi", "ret_1d")
            if row.get(key) is None
        ]
        if absent_optional:
            optional_missing[code] = absent_optional

    if expected:
        missing_codes = sorted(set(expected) - seen)
        extra_codes = sorted(seen - set(expected))
        failures.extend(f"{code}:missing_symbol" for code in missing_codes)
        failures.extend(f"{code}:unexpected_symbol" for code in extra_codes)

    checked = len(rows)
    bad_codes = sorted({item.split(":")[0] for item in failures})
    bad_ratio = len(bad_codes) / max(checked, 1)
    ok = not failures and bad_ratio <= float(max_bad_ratio)
    return {
        "ok": ok,
        "checked": checked,
        "expected": len(expected) if expected else None,
        "bad_n": len(bad_codes),
        "bad_codes": bad_codes,
        "failures": failures[:200],
        "bad_ratio": round(bad_ratio, 4),
        "optional_missing": optional_missing,
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
