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

``root`` may also be a :class:`~research.data_quality.contract_store.ContractStore`: a cache store
fetches into its root, a frozen bundle never fetches (missing contracts are reported, not filled).
The formal backtest calls :func:`ensure_listed_contract_bars` (R7a-D) for every contract the listing
calendar makes a ``main_map`` candidate on any day of the window.
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
    root=None,
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
    from research.data_quality.contract_store import resolve_store

    store = resolve_store(root)
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
    if store.cache_root is None:  # frozen bundle: read-only
        for contract in wanted:
            by = store.by_date(contract)
            if by and max(by) >= upto_s or by and _contract_expired(contract, d):
                report["cached"].append(contract)
            else:
                report["failed"].append({"contract": contract, "error": "not in bundle"})
        return report
    root = store.cache_root
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


def listed_candidates(series: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Per code: every contract the listing calendar makes a ``main_map`` candidate on a bar date."""
    from research.data_quality.calendar import listed_contracts_on, load_delivery_rules

    rules = load_delivery_rules()
    out: dict[str, list[str]] = {}
    for code, pack in series.items():
        got: set[str] = set()
        for b in pack.get("hist") or []:
            d = str(b.get("date") or "")[:10]
            if d:
                got.update(listed_contracts_on(code, d, rules=rules))
            c = str(b.get("contract") or "").upper()
            if re.fullmatch(r"[A-Z]+\d{4}", c):
                got.add(c)
        out[code] = sorted(got)
    return out


def ensure_listed_contract_bars(
    series: dict[str, dict[str, Any]],
    root=None,
    *,
    fetcher: Callable[[str], list[dict]] | None = None,
) -> dict[str, Any]:
    """Fill the cache for every listing-calendar candidate of the window (formal backtest, R7a-D).

    A contract is fetched unless its cached bars already reach ``min(window end, last trade day)``
    or it has expired with bars cached.  Returns requests / seconds / fetched / failed / cached_n."""
    from research.data_quality.calendar import contract_last_trade_day, load_delivery_rules
    from research.data_quality.contract_store import resolve_store

    store = resolve_store(root)
    rules = load_delivery_rules()
    cands = listed_candidates(series)
    rep: dict[str, Any] = {
        "wanted_n": sum(len(v) for v in cands.values()),
        "requests": 0,
        "seconds": 0.0,
        "fetched": [],
        "failed": [],
        "cached_n": 0,
        "by_code": {},
    }
    if store.cache_root is None:
        rep["skipped"] = "store is a frozen bundle"
        return rep
    root_p = store.cache_root
    if fetcher is None:
        from market_data import fetch_sina_exact_contract as fetcher  # type: ignore[assignment]
    t0 = time.perf_counter()
    for code, contracts in cands.items():
        hist = series[code].get("hist") or []
        end = max((str(b.get("date") or "")[:10] for b in hist), default=None)
        if not end:
            continue
        end_d = _parse_day(end)
        n_req = 0
        for contract in contracts:
            path = root_p / ".cache" / "contracts" / f"{contract}.json"
            rows = _read_cached(path)
            last = max((str(b["date"])[:10] for b in rows), default=None)
            ltd = contract_last_trade_day(contract, rules)
            need = min(end, ltd.isoformat()) if ltd is not None else end
            if last is not None and (last >= need or (ltd is not None and ltd < end_d)):
                rep["cached_n"] += 1
                continue
            rep["requests"] += 1
            n_req += 1
            try:
                got = fetcher(contract) or []
            except Exception as exc:  # noqa: BLE001
                rep["failed"].append({"code": code, "contract": contract, "error": str(exc)[:120]})
                continue
            if not got:
                rep["failed"].append({"code": code, "contract": contract, "error": "empty"})
                continue
            by = {str(b["date"])[:10]: b for b in rows}
            for b in got:
                by[str(b["date"])[:10]] = b
            try:
                _write_cache(path, contract, [by[k] for k in sorted(by)])
            except OSError as exc:
                rep["failed"].append({"code": code, "contract": contract, "error": f"write: {exc}"[:120]})
                continue
            rep["fetched"].append(contract)
        rep["by_code"][code] = {"candidates": len(contracts), "requests": n_req}
    rep["seconds"] = round(time.perf_counter() - t0, 3)
    return rep
