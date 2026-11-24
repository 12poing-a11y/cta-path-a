# -*- coding: utf-8 -*-
"""Month-contract daily bars for the live ``main_map`` (R5a).

The backtest builds ``main_map`` / the roll-free signal series from the monthly contracts under
``.cache/contracts``.  The daily report needs the same files for TODAY's bar, so it calls
``ensure_contract_bars(code, upto, root)`` before building them:

* read ``.cache/contracts/{CONTRACT}.json`` first; fetch only what is missing / stale;
* only the contracts that can matter: the previous main contract, the delivery months that expired
  in the last ``recent_days`` (they were the main contract inside the signal window) and the nearest three listed
  delivery months on the calendar;
* write what was fetched back to the cache (merged by date), and report the number of requests
  and the time spent so the caller can log it.

Nothing here raises: a failed fetch is recorded and the caller falls back (R6c ``adj_fallback``).
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]


def _parse_day(value: str | date) -> date:
    if isinstance(value, date):
        return value
    s = str(value)[:10]
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def nearest_listed_contracts(code: str, upto: str | date, n: int = 3, *, rules: dict | None = None) -> list[str]:
    """The ``n`` nearest listed delivery months whose last trade day is not before ``upto``."""
    from research.data_quality.calendar import estimate_last_trade_day, load_delivery_rules, product_rule

    rules = rules or load_delivery_rules()
    d = _parse_day(upto)
    code_u = str(code).upper()
    pr = product_rule(code_u, rules)
    months = pr.get("months") or list(range(1, 13))
    out: list[str] = []
    y, m = d.year, d.month
    for _ in range(36):
        if m in months:
            contract = f"{code_u}{y % 100:02d}{m:02d}"
            explicit = (rules.get("last_trade_dates") or {}).get(contract)
            if explicit:
                s = str(explicit).replace("-", "")[:8]
                ltd = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            else:
                ltd = estimate_last_trade_day(y, m, pr.get("last_trade_rule") or "month_day_10")
            if d <= ltd:
                out.append(contract)
                if len(out) >= n:
                    break
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def recent_expired_contracts(
    code: str, upto: str | date, days: int = 150, *, rules: dict | None = None
) -> list[str]:
    """Delivery months whose last trade day fell in ``[upto - days, upto)``.

    These were the live main contract inside the signal window (60-bar returns, ATR, roll
    adjustment), so the roll-free series needs their own daily bars.  Expired contracts are
    complete once cached, so they cost requests only the first time."""
    from datetime import timedelta

    from research.data_quality.calendar import estimate_last_trade_day, load_delivery_rules, product_rule

    rules = rules or load_delivery_rules()
    d = _parse_day(upto)
    start = d - timedelta(days=int(days))
    code_u = str(code).upper()
    pr = product_rule(code_u, rules)
    months = pr.get("months") or list(range(1, 13))
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (d.year, d.month):
        if m in months:
            contract = f"{code_u}{y % 100:02d}{m:02d}"
            explicit = (rules.get("last_trade_dates") or {}).get(contract)
            if explicit:
                s = str(explicit).replace("-", "")[:8]
                ltd = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            else:
                ltd = estimate_last_trade_day(y, m, pr.get("last_trade_rule") or "month_day_10")
            if start <= ltd < d:
                out.append(contract)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _contract_expired(contract: str, upto: date, rules: dict | None = None) -> bool:
    from research.data_quality.calendar import (
        estimate_last_trade_day,
        load_delivery_rules,
        parse_contract_month,
        product_rule,
    )

    parsed = parse_contract_month(contract)
    if parsed is None:
        return False
    code, year, month = parsed
    rules = rules or load_delivery_rules()
    pr = product_rule(code, rules)
    explicit = (rules.get("last_trade_dates") or {}).get(contract)
    if explicit:
        s = str(explicit).replace("-", "")[:8]
        ltd = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    else:
        ltd = estimate_last_trade_day(year, month, pr.get("last_trade_rule") or "month_day_10")
    return ltd < upto


def _read_cached(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data if isinstance(data, list) else data.get("bars") or []
    return [b for b in rows if isinstance(b, dict) and b.get("date")]


def _write_cache(path: Path, contract: str, bars: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"contract": contract.upper(), "n": len(bars), "bars": bars, "source": "sina_exact_contract"}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def ensure_contract_bars(
    code: str,
    upto: str | date,
    root: Path | None = None,
    *,
    prev_main: str | None = None,
    fetcher: Callable[[str], list[dict]] | None = None,
    extra: list[str] | None = None,
    n_listed: int = 3,
    recent_days: int = 150,
) -> dict[str, Any]:
    """Make sure the contracts that matter for ``code`` have a bar for ``upto``.

    Returns ``{"code", "upto", "wanted", "cached", "fetched", "failed", "requests", "seconds"}``.
    ``fetcher(contract) -> list[bar]`` defaults to ``market_data.fetch_sina_exact_contract``.
    """
    root = Path(root or ROOT)
    d = _parse_day(upto)
    upto_s = d.isoformat()
    wanted: list[str] = []
    for c in (
        ([prev_main] if prev_main else [])
        + nearest_listed_contracts(code, d, n_listed)
        + recent_expired_contracts(code, d, recent_days)
        + list(extra or [])
    ):
        c = str(c or "").upper()
        if re.fullmatch(r"[A-Z]+\d{4}", c) and c not in wanted:
            wanted.append(c)
    report: dict[str, Any] = {
        "code": str(code).upper(),
        "upto": upto_s,
        "wanted": wanted,
        "cached": [],
        "fetched": [],
        "failed": [],
        "requests": 0,
        "seconds": 0.0,
    }
    if fetcher is None:
        from market_data import fetch_sina_exact_contract as fetcher  # type: ignore[assignment]
    t0 = time.perf_counter()
    for contract in wanted:
        path = root / ".cache" / "contracts" / f"{contract}.json"
        rows = _read_cached(path)
        last = max((str(b["date"])[:10] for b in rows), default=None)
        if last is not None and last >= upto_s:
            report["cached"].append(contract)
            continue
        if last is not None and _contract_expired(contract, d):
            report["cached"].append(contract)  # delivered: the cache is complete
            continue
        report["requests"] += 1
        try:
            got = fetcher(contract) or []
        except Exception as exc:  # noqa: BLE001
            report["failed"].append({"contract": contract, "error": str(exc)[:120]})
            continue
        if not got:
            report["failed"].append({"contract": contract, "error": "empty"})
            continue
        by = {str(b["date"])[:10]: b for b in rows}
        for b in got:
            by[str(b["date"])[:10]] = b
        merged = [by[k] for k in sorted(by)]
        try:
            _write_cache(path, contract, merged)
        except OSError as exc:
            report["failed"].append({"contract": contract, "error": f"write: {exc}"[:120]})
            continue
        report["fetched"].append(contract)
    report["seconds"] = round(time.perf_counter() - t0, 3)
    return report
