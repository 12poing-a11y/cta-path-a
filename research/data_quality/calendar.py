# -*- coding: utf-8 -*-
"""Delivery / roll calendar helpers for tradability masks (research approximation)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "configs" / "calendar" / "delivery_rules.json"


def load_delivery_rules(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    path = root / "configs" / "calendar" / "delivery_rules.json"
    return json.loads(path.read_text(encoding="utf-8"))


def exchange_for_product(code: str, rules: dict[str, Any] | None = None) -> str:
    rules = rules or load_delivery_rules()
    code = str(code or "").upper()
    prod = rules.get("by_product") or {}
    if code in prod and prod[code].get("exchange"):
        return str(prod[code]["exchange"])
    return "CZCE"


def product_rule(code: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = rules or load_delivery_rules()
    code = str(code or "").upper()
    out = dict(rules.get("default") or {})
    ex = exchange_for_product(code, rules)
    out.update((rules.get("by_exchange") or {}).get(ex) or {})
    out.update((rules.get("by_product") or {}).get(code) or {})
    out["exchange"] = ex
    out["code"] = code
    return out


def _parse_ymd(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _nth_weekday_on_or_after(d: date) -> date:
    while not _is_weekday(d):
        d += timedelta(days=1)
    return d


def _nth_weekday_on_or_before(d: date) -> date:
    while not _is_weekday(d):
        d -= timedelta(days=1)
    return d


def estimate_last_trade_day(year: int, month: int, rule: str) -> date:
    """Approximate last trading day of a delivery month (not official calendar)."""
    rule = str(rule or "month_day_10")
    if rule == "mid_month_15":
        return _nth_weekday_on_or_before(date(year, month, 15))
    if rule == "month_day_10":
        return _nth_weekday_on_or_before(date(year, month, 10))
    if rule == "third_last_business_day":
        # last calendar day, walk back 3 weekdays
        if month == 12:
            d = date(year, 12, 31)
        else:
            d = date(year, month + 1, 1) - timedelta(days=1)
        seen = 0
        while True:
            if _is_weekday(d):
                seen += 1
                if seen >= 3:
                    return d
            d -= timedelta(days=1)
    return _nth_weekday_on_or_before(date(year, month, 10))


def parse_contract_month(contract: str) -> tuple[str, int, int] | None:
    """CF2701 -> (CF, 2027, 1)."""
    import re

    m = re.fullmatch(r"([A-Za-z]+)(\d{2})(\d{2})", str(contract or "").upper())
    if not m:
        return None
    code, yy, mm = m.group(1), int(m.group(2)), int(m.group(3))
    if not (1 <= mm <= 12):
        return None
    year = 2000 + yy if yy < 80 else 1900 + yy
    return code, year, mm


def session_distance(from_d: date, to_d: date) -> int:
    """Weekday sessions from from_d to to_d inclusive of direction (to - from)."""
    if to_d == from_d:
        return 0
    step = 1 if to_d > from_d else -1
    cur = from_d
    n = 0
    while cur != to_d:
        cur += timedelta(days=step)
        if _is_weekday(cur):
            n += step
        if abs(n) > 400:
            break
    return n


def active_front_contract_on_date(
    code: str,
    bar_date: str | date,
    *,
    rules: dict[str, Any] | None = None,
) -> str | None:
    """Pick the listed front contract still tradeable on ``bar_date`` (calendar approx).

    Does **not** use the current observe month to blanket all history.
    """
    rules = rules or load_delivery_rules()
    d = _parse_ymd(bar_date)
    if d is None:
        return None
    code_u = str(code or "").upper()
    pr = product_rule(code_u, rules)
    months = pr.get("months") or list(range(1, 13))
    y, m = d.year, d.month
    for _ in range(24):
        if m in months:
            contract = f"{code_u}{y % 100:02d}{m:02d}"
            explicit = (rules.get("last_trade_dates") or {}).get(contract)
            if explicit:
                ltd = _parse_ymd(explicit)
            else:
                ltd = estimate_last_trade_day(y, m, pr.get("last_trade_rule") or "month_day_10")
            if ltd is not None and d <= ltd:
                return contract
        m += 1
        if m > 12:
            m = 1
            y += 1
    return None


def delivery_flags_for_date(
    code: str,
    bar_date: str | date,
    *,
    front_contract: str | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return near_delivery / roll_blocked / no_new_position for a session."""
    rules = rules or load_delivery_rules()
    d = _parse_ymd(bar_date)
    if d is None:
        return {"ok": False, "near_delivery": False, "roll_blocked": False, "delivery_restricted": False}
    pr = product_rule(code, rules)
    contract = front_contract or active_front_contract_on_date(code, d, rules=rules)
    parsed = parse_contract_month(contract) if contract else None
    if not parsed:
        return {
            "ok": True,
            "near_delivery": False,
            "roll_blocked": False,
            "delivery_restricted": False,
            "front_contract": contract,
        }
    _, yy, mm = parsed
    # Prefer explicit exchange-style dates when curated in rules
    explicit = (rules.get("last_trade_dates") or {}).get(str(contract).upper())
    if explicit:
        ltd = _parse_ymd(explicit) or estimate_last_trade_day(
            yy, mm, pr.get("last_trade_rule") or "month_day_10"
        )
    else:
        ltd = estimate_last_trade_day(yy, mm, pr.get("last_trade_rule") or "month_day_10")
    # sessions until last trade (positive if before)
    dist = session_distance(d, ltd)
    no_new = int(pr.get("no_new_position_sessions") or 5)
    roll_warn = int(pr.get("roll_warn_sessions") or 10)
    near = 0 <= dist <= roll_warn
    restricted = 0 <= dist <= no_new
    # after last trade: blocked
    if dist < 0:
        restricted = True
        near = True
    return {
        "ok": True,
        "front_contract": contract,
        "last_trade_day": ltd.isoformat(),
        "sessions_to_last_trade": dist,
        "near_delivery": near,
        "roll_blocked": restricted,  # treat hard window as no new position
        "delivery_restricted": restricted,
        "no_new_position": restricted,
        "rule": pr.get("last_trade_rule"),
        "exchange": pr.get("exchange"),
    }


def annotate_bars_with_calendar(
    code: str,
    bars: list[dict[str, Any]],
    *,
    front_contract: str | None = None,
    rules: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Copy bars and stamp delivery flags (does not mutate input)."""
    rules = rules or load_delivery_rules()
    out = []
    for b in bars:
        row = dict(b)
        flags = delivery_flags_for_date(
            code, row.get("date") or row.get("bar_date"), front_contract=front_contract, rules=rules
        )
        if flags.get("delivery_restricted"):
            row["delivery_restricted"] = True
            row["near_delivery"] = True
            row["no_new_position"] = True
            row["roll_blocked"] = True
        elif flags.get("near_delivery"):
            row["near_delivery"] = True
        row["calendar_front"] = flags.get("front_contract")
        row["sessions_to_last_trade"] = flags.get("sessions_to_last_trade")
        out.append(row)
    return out
