# -*- coding: utf-8 -*-
"""Streamlit-free local bar / carry-gap loaders (shared by desk UI, daily_update, tech_score)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from basis_data import carry_gaps_from_akshare


def _num(value: Any) -> float | None:
    if value is None or value is False:
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("+", "").strip()
        if value in ("", "-", "—"):
            return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _read_bars(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    by_date: dict[str, dict] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "")[:10]
        close = _num(row.get("close"))
        if not day or close is None or close <= 0:
            continue
        high = _num(row.get("high"))
        low = _num(row.get("low"))
        if high is None:
            high = close
        if low is None:
            low = close
        if high < low:
            high, low = low, high
        by_date[day] = {
            "date": day,
            "close": close,
            "high": high,
            "low": low,
            "volume": _num(row.get("volume")),
            "open_interest": _num(row.get("open_interest")),
        }
    return [by_date[key] for key in sorted(by_date)]


def load_local_bars(root: Path, code: str) -> tuple[list[dict], str]:
    """Best local continuous series for charts.

    Drops future-dated / malformed OHLC first so a poisoned sina cache cannot
    jump past the latest closed session. Prefers series that reach that session,
    then last date, then length. Offline only — refresh via daily_update / sync.
    """
    from market_data import filter_bars_asof, latest_expected_session_date

    code = str(code or "").upper()
    expected = latest_expected_session_date().isoformat()
    sina = root / ".cache" / "sina"
    paths: list[Path] = []
    if sina.is_dir():
        paths.extend(sina.glob(f"*/{code}0.json"))
    for folder in (root / "market_data", root / ".cache" / "history", root / ".cache" / "market"):
        candidate = folder / f"{code}0.json"
        if candidate.is_file():
            paths.append(candidate)
    best: list[dict] = []
    source = ""
    best_key = ""
    for path in paths:
        bars = filter_bars_asof(_read_bars(path))
        if not bars:
            continue
        stamp = path.parent.name
        last = str((bars[-1] or {}).get("date") or "")
        reaches = "1" if last >= expected else "0"
        # Prefer expected-session coverage, then newest valid last bar, then length.
        key = f"{reaches}-{last}-{len(bars):08d}-{stamp}"
        if key > best_key:
            best = bars
            best_key = key
            source = f".cache/sina/{stamp}/{path.name}" if "sina" in path.parts else str(path.relative_to(root)).replace("\\", "/")
    return best, source


def _expiry(symbol: str) -> int:
    digits = "".join(ch for ch in symbol if ch.isdigit())
    return int(digits[-4:]) if len(digits) >= 4 else 0


def _bar_alive(bar: dict) -> bool:
    oi = bar.get("open_interest")
    vol = bar.get("volume")
    if oi is not None and vol is not None and oi <= 0 and vol <= 0:
        return False
    return float(bar.get("close") or 0) > 0


def load_carry_gaps(root: Path, code: str) -> list[dict] | None:
    """Front vs next close; Sina delivery months first, akshare basis/roll next."""
    code = str(code or "").upper()
    sina = root / ".cache" / "sina"
    rows: list[dict] = []
    if sina.is_dir():
        pat = re.compile(rf"^{re.escape(code)}\d{{4}}$", re.I)
        best: dict[str, tuple[str, list[dict]]] = {}
        for path in sina.glob(f"*/{code}[0-9][0-9][0-9][0-9].json"):
            if not pat.match(path.stem):
                continue
            bars = _read_bars(path)
            if len(bars) < 5:
                continue
            key = path.stem.upper()
            prev = best.get(key)
            stamp = path.parent.name
            if prev is None or len(bars) > len(prev[1]) or (
                len(bars) == len(prev[1]) and stamp > prev[0]
            ):
                best[key] = (stamp, bars)
        if len(best) >= 2:
            books = {
                sym: {bar["date"]: bar for bar in bars}
                for sym, (_stamp, bars) in best.items()
            }
            dates = sorted({day for book in books.values() for day in book})
            for day in dates:
                alive = []
                for sym, book in books.items():
                    bar = book.get(day)
                    if not bar or not _bar_alive(bar):
                        continue
                    alive.append((_expiry(sym), float(bar["close"])))
                if len(alive) < 2:
                    continue
                alive.sort()
                front, nxt = alive[0][1], alive[1][1]
                if front <= 0:
                    continue
                rows.append({"date": day, "gap": (nxt - front) / front, "source": "sina"})
    if len(rows) >= 10:
        return rows
    ak_rows = carry_gaps_from_akshare(root, code) or []
    if not rows:
        return ak_rows or None
    # Merge: prefer Sina on overlapping days, keep akshare-only days.
    by_day = {r["date"]: r for r in ak_rows}
    by_day.update({r["date"]: r for r in rows})
    merged = [by_day[d] for d in sorted(by_day)]
    return merged or None
