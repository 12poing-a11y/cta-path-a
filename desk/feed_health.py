# -*- coding: utf-8 -*-
"""Cross-feed lag / gap audit for the desk (display + daily soft warnings).

Does not fabricate data. Flags IV / vol-engine / warehouse / gamma cutoffs vs
the latest expected day session so stale research snapshots are visible.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

# Soft lag thresholds (calendar weekdays approximated as calendar days).
IV_STALE_DAYS = 3
VOL_STALE_DAYS = 3
WAREHOUSE_STALE_DAYS = 2
GAMMA_STALE_DAYS = 3


def _ymd(text: str | None) -> str:
    return str(text or "").replace("-", "")[:8]


def _parse_ymd(text: str | None) -> date | None:
    ymd = _ymd(text)
    if len(ymd) != 8 or not ymd.isdigit():
        return None
    try:
        return date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
    except ValueError:
        return None


def _lag_weekdays(asof: date | None, expected: date) -> int | None:
    if asof is None:
        return None
    if asof >= expected:
        return 0
    n = 0
    d = expected
    while d > asof:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _expected_day(now: datetime | None = None) -> date:
    try:
        from market_data import latest_expected_session_date

        return latest_expected_session_date(now)
    except Exception:  # noqa: BLE001
        now = (now or datetime.now(TZ)).astimezone(TZ)
        d = now.date()
        if now.hour < 15 or d.weekday() >= 5:
            d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d


def _read_json(path: Path) -> Any | None:
    if not path.is_file() or path.stat().st_size < 2:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _iv_feed(root: Path, expected: date) -> dict[str, Any]:
    try:
        from iv_breakout import iv_cache_status

        st = iv_cache_status(root)
    except Exception as exc:  # noqa: BLE001
        return {
            "id": "option_iv",
            "name": "期权IV缓存",
            "asof": None,
            "lag_busdays": None,
            "stale": True,
            "status": "错误",
            "note": str(exc)[:160],
        }
    newest = _parse_ymd(st.get("newest_ok"))
    lag = _lag_weekdays(newest, expected)
    stale = newest is None or (lag is not None and lag > IV_STALE_DAYS)
    by = st.get("by_code") or {}
    thin = [c for c, row in by.items() if not (row or {}).get("last_ok")]
    note = ""
    if thin:
        note = f"无缓存: {','.join(thin[:6])}"
    elif lag and lag > 0:
        note = f"最新 {st.get('newest_ok')}，落后约 {lag} 个交易日"
    return {
        "id": "option_iv",
        "name": "期权IV缓存",
        "asof": st.get("newest_ok"),
        "lag_busdays": lag,
        "stale": bool(stale),
        "status": "滞后" if stale else "已到",
        "note": note,
        "detail": st,
    }


def _vol_feed(root: Path, expected: date) -> dict[str, Any]:
    raw = _read_json(Path(root) / "data" / "vol_engine_latest.json") or {}
    reports = raw.get("reports") if isinstance(raw, dict) else None
    iv_dates: list[str] = []
    if isinstance(reports, list):
        for row in reports:
            d = ((row or {}).get("iv") or {}).get("date") or (row or {}).get("asof")
            y = _ymd(d)
            if len(y) == 8:
                iv_dates.append(y)
    newest = _parse_ymd(max(iv_dates) if iv_dates else None)
    lag = _lag_weekdays(newest, expected)
    stale = newest is None or (lag is not None and lag > VOL_STALE_DAYS)
    note = ""
    if not raw:
        note = "缺 data/vol_engine_latest.json"
    elif lag and lag > 0:
        note = f"IV asof {newest.strftime('%Y%m%d') if newest else '—'}，落后约 {lag} 日"
    return {
        "id": "vol_engine",
        "name": "波动率引擎快照",
        "asof": newest.strftime("%Y%m%d") if newest else None,
        "lag_busdays": lag,
        "stale": bool(stale),
        "status": "滞后" if stale else "已到",
        "note": note or f"generated_at={raw.get('generated_at') or '—'}",
    }


def _warehouse_feed(root: Path, expected: date) -> dict[str, Any]:
    raw = _read_json(Path(root) / ".cache" / "warehouse" / "latest.json") or {}
    asof = _parse_ymd(raw.get("asof") or raw.get("exchange_ymd"))
    lag = _lag_weekdays(asof, expected)
    ex = raw.get("exchange_status") or {}
    down = [
        name
        for name in ("SHFE", "DCE", "CZCE")
        if isinstance(ex.get(name), dict) and not ex[name].get("ok")
    ]
    # DCE exchange API often HTTP 412 (瑞数); EM bypass is the designed fallback.
    dce_only = down == ["DCE"]
    hard_down = [n for n in down if n != "DCE"]
    missing_n = int(raw.get("missing_n") or 0)
    stale = asof is None or (lag is not None and lag > WAREHOUSE_STALE_DAYS)
    notes = []
    if hard_down:
        notes.append(f"交易所主源失败: {','.join(hard_down)}（东财旁路）")
    elif dce_only:
        notes.append("大商所主源反爬(412)，铁矿/焦煤等用东财旁路")
    if lag and lag > 0:
        notes.append(f"落后约 {lag} 日")
    if hard_down or missing_n > 0 or stale:
        status = "主源异常" if hard_down else ("滞后" if stale else "缺品种")
        is_stale = True
    elif dce_only:
        status = "已到(DCE旁路)"
        is_stale = False
    else:
        status = "已到"
        is_stale = False
    return {
        "id": "warehouse",
        "name": "仓单/库存",
        "asof": asof.strftime("%Y%m%d") if asof else None,
        "lag_busdays": lag,
        "stale": bool(is_stale),
        "status": status,
        "note": "；".join(notes),
        "primary_n": raw.get("primary_n"),
        "bypass_n": raw.get("bypass_n"),
    }


def _gamma_feed(root: Path, expected: date) -> dict[str, Any]:
    base = Path(root) / "data" / "gamma_wall"
    newest: date | None = None
    if base.is_dir():
        for path in base.rglob("*.json"):
            d = _parse_ymd(path.stem)
            if d and (newest is None or d > newest):
                newest = d
    lag = _lag_weekdays(newest, expected)
    stale = newest is None or (lag is not None and lag > GAMMA_STALE_DAYS)
    note = "独立 workflow 16:35 采集" + (
        f"；最新 {newest.isoformat()}" if newest else "；无快照"
    )
    return {
        "id": "gamma_wall",
        "name": "Gamma 墙快照",
        "asof": newest.strftime("%Y%m%d") if newest else None,
        "lag_busdays": lag,
        "stale": bool(stale),
        "status": "滞后" if stale else "已到",
        "note": note,
    }


def feed_health(root: Path, now: datetime | None = None) -> dict[str, Any]:
    """Aggregate research/market feed freshness for desk banners."""
    now = (now or datetime.now(TZ)).astimezone(TZ)
    expected = _expected_day(now)
    feeds = [
        _iv_feed(root, expected),
        _vol_feed(root, expected),
        _warehouse_feed(root, expected),
        _gamma_feed(root, expected),
    ]
    stale_n = sum(1 for f in feeds if f.get("stale"))
    return {
        "ok": stale_n == 0,
        "expected_day_ymd": expected.strftime("%Y%m%d"),
        "checked_at": now.strftime("%Y-%m-%d %H:%M (UTC+8)"),
        "stale_n": stale_n,
        "feeds": feeds,
    }


def render_feed_health(root: Path) -> dict[str, Any]:
    """Streamlit: compact feed lag table under page freshness caption."""
    import streamlit as st

    pack = feed_health(root)
    feeds = pack.get("feeds") or []
    if not feeds:
        return pack
    rows = [
        {
            "数据源": f.get("name"),
            "截止": f.get("asof") or "—",
            "期望日盘": pack.get("expected_day_ymd"),
            "滞后(交易日)": f.get("lag_busdays") if f.get("lag_busdays") is not None else "—",
            "状态": f.get("status"),
            "说明": f.get("note") or "",
        }
        for f in feeds
    ]
    stale = [f for f in feeds if f.get("stale")]
    with st.expander(
        f"数据源健康 · 滞后/缺失 {len(stale)}/{len(feeds)}",
        expanded=bool(stale),
    ):
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "IV/波动率引擎随 15:30 日更回填；Gamma 为 16:35 独立任务；"
            "仓单上期所/大商所主源若失败则用东财库存旁路，不编造。"
            "已实现波动率面板只含 HV，不含 IV。"
        )
        if stale:
            st.warning(
                "待核："
                + "；".join(
                    f"{f.get('name')}({f.get('asof') or '无'})" for f in stale
                )
            )
    return pack
