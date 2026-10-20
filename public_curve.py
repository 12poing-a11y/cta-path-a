# -*- coding: utf-8 -*-
"""Dominant-contract rolls and front/next closes from Sina delivery months.

iFinD is asked once per symbol only when fewer than two Sina contracts return bars.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from market_data import fetch_sina_symbol

# Delivery months that actually list. Empty Sina replies are skipped.
MONTHS = {
    "MA": (1, 5, 9),
    "V": (1, 5, 9),
    "EG": (1, 5, 9),
    "M": (1, 3, 5, 7, 8, 9, 11, 12),
    "FG": (1, 5, 9),
    "EB": tuple(range(1, 13)),
    "TA": (1, 5, 9),
    "SA": (1, 5, 9),
    "PP": (1, 5, 9),
    "L": (1, 5, 9),
    "JD": tuple(range(1, 13)),
    "P": (1, 5, 9),
    "RB": (1, 5, 10),
    "FU": tuple(range(1, 13)),
    "CF": (1, 5, 9),
    "BU": tuple(range(1, 13)),
    "RU": (1, 5, 9),
    "AG": tuple(range(1, 13)),
    "SP": (1, 3, 5, 6, 7, 8, 9, 11),
    "SR": (1, 5, 9),
}

_CURVES: dict[str, dict] | None = None


def contract_symbols(code: str, *, back_days: int = 460, forward_days: int = 420) -> list[str]:
    code = str(code or "").upper()
    months = MONTHS.get(code, tuple(range(1, 13)))
    start = date.today() - timedelta(days=back_days)
    end = date.today() + timedelta(days=forward_days)
    y, m = start.year, start.month
    out = []
    while date(y, m, 1) <= end:
        if m in months:
            out.append(f"{code}{y % 100:02d}{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def _expiry(symbol: str) -> int:
    digits = "".join(ch for ch in symbol if ch.isdigit())
    return int(digits[-4:]) if len(digits) >= 4 else 0


def _build_one(code: str) -> dict:
    symbols = contract_symbols(code)
    books: dict[str, dict] = {}
    for sym in symbols:
        try:
            bars = fetch_sina_symbol(sym)
        except Exception:
            bars = []
        if len(bars) < 5:
            continue
        books[sym] = {b["date"]: b for b in bars}
    dates = sorted({d for book in books.values() for d in book})
    dominant: dict[str, str] = {}
    carry: dict[str, tuple[float, float]] = {}
    for d in dates:
        ranked = []
        for sym, book in books.items():
            bar = book.get(d)
            if not bar:
                continue
            oi = bar.get("open_interest") or 0
            vol = bar.get("volume") or 0
            if oi <= 0 and vol <= 0:
                continue
            ranked.append((oi, vol, -_expiry(sym), sym, bar["close"]))
        if not ranked:
            continue
        ranked.sort(reverse=True)
        dominant[d] = ranked[0][3]
        alive = sorted(
            ((_expiry(sym), close) for _oi, _vol, _neg, sym, close in ranked),
            key=lambda x: x[0],
        )
        if len(alive) >= 2:
            carry[d] = (alive[0][1], alive[1][1])
    roll_dates = set()
    prev_d = None
    prev_sym = None
    for d in dates:
        sym = dominant.get(d)
        if prev_sym and sym and sym != prev_sym:
            roll_dates.add(prev_d)
            roll_dates.add(d)
        if sym:
            prev_sym = sym
            prev_d = d
    return {
        "code": code,
        "contracts": len(books),
        "tried": len(symbols),
        "roll_dates": roll_dates,
        "carry": carry,
        "source": "sina" if books else "",
    }


def _ifind_carry(code: str) -> dict[str, tuple[float, float]]:
    """One iFinD quote when Sina did not return two delivery months."""
    try:
        from ifind_call import call
    except Exception:
        return {}
    query = (
        f"{code}主力近月与次近月最近260个交易日的日期、近月收盘价、次月收盘价。"
        f"一张Markdown表，日期YYYY-MM-DD。"
    )
    try:
        res = call("future", "future_quotes", {"query": query})
    except Exception as exc:
        print(f"  [curve] {code} ifind fail {exc}")
        return {}
    if not res.get("ok"):
        print(f"  [curve] {code} ifind not ok")
        return {}
    try:
        text = res["data"]["result"]["content"][0]["text"]
    except Exception:
        return {}
    out = {}
    for line in str(text).splitlines():
        m = re.search(r"(20\d{2}-\d{2}-\d{2}|20\d{6})", line)
        if not m:
            continue
        raw = m.group(1)
        day = raw if "-" in raw else f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        nums = []
        for token in re.findall(r"-?\d+(?:\.\d+)?", line):
            if token.startswith("20") and len(token) >= 8:
                continue
            try:
                nums.append(float(token))
            except ValueError:
                continue
        prices = [n for n in nums if n > 50]
        if len(prices) >= 2:
            out[day] = (prices[0], prices[1])
    print(f"  [curve] {code} ifind carry days={len(out)}")
    return out


def load_curves(codes: list[str]) -> dict[str, dict]:
    global _CURVES
    if _CURVES is not None and all(c in _CURVES for c in codes):
        return _CURVES
    found: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_build_one, c): c for c in codes}
        for fut in as_completed(futs):
            code = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                print(f"  [curve] {code} ERR {exc}")
                row = {
                    "code": code,
                    "contracts": 0,
                    "tried": 0,
                    "roll_dates": set(),
                    "carry": {},
                    "source": "",
                }
            found[code] = row
    for code, row in found.items():
        if int(row.get("contracts") or 0) < 2:
            extra = _ifind_carry(code)
            if extra:
                row["carry"].update(extra)
                row["source"] = (row.get("source") + "+ifind") if row.get("source") else "ifind"
        print(
            f"  [curve] {code} source={row.get('source')} "
            f"contracts={row.get('contracts')}/{row.get('tried')} "
            f"roll={len(row.get('roll_dates') or [])} "
            f"carry={len(row.get('carry') or {})}"
        )
    _CURVES = found
    return found


def curve_coverage(curves: dict) -> dict:
    out = {}
    for code, row in curves.items():
        out[code] = {
            "source": row.get("source"),
            "contracts": row.get("contracts"),
            "roll_days": len(row.get("roll_dates") or []),
            "carry_days": len(row.get("carry") or {}),
        }
    return out
