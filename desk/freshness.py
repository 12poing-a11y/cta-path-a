# -*- coding: utf-8 -*-
"""Per-page data cutoff (data_asof) banner + night-session coverage flag.

Desk data comes from the 15:30 GitHub Actions day-session report (l1_report.json).
It never contains the night session. This module states that explicitly and marks
the data 待核 when data_asof is older than the latest closed session.
Weekday calendar only (exchange holidays not modelled -> holiday mornings may show 待核).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

# Product codes with a night session (SHFE/INE/DCE/CZCE/GFEX), uppercase.
NIGHT_CODES = {
    "AU", "AG", "CU", "AL", "ZN", "PB", "NI", "SN", "SS", "AO", "BC", "RB", "HC", "BU",
    "RU", "NR", "FU", "LU", "SP", "SC", "BR", "A", "B", "M", "Y", "P", "C", "CS", "I",
    "J", "JM", "L", "PP", "V", "EG", "EB", "PG", "RR", "MA", "TA", "CF", "SR", "OI",
    "RM", "FG", "SA", "CY", "ZC", "PF", "PX", "SH", "PR",
}


def _prev_weekday(d: datetime) -> datetime:
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def expected_cutoffs(now: datetime) -> dict:
    """Latest closed day session date and latest closed night session start date."""
    now = now.astimezone(TZ)
    wk = now.weekday() < 5
    day = now if (wk and now.hour >= 15) else _prev_weekday(now)
    # last closed night session (opened 21:00; most products close 23:00)
    night = now if (wk and now.hour >= 23) else _prev_weekday(now)
    return {"day_ymd": day.strftime("%Y%m%d"), "night_ymd": night.strftime("%Y%m%d")}


def _l1(root: Path) -> dict:
    try:
        return json.loads((Path(root) / "l1_report.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def desk_freshness(root: Path, now: datetime | None = None) -> dict:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    rep = _l1(root)
    asof = str(rep.get("asof") or "").replace("-", "")[:8]
    sigs = rep.get("signals") or []
    codes = {str(s.get("code") or "").upper() for s in sigs}
    night_n = len(codes & NIGHT_CODES)
    cut = expected_cutoffs(now)
    stale = (not asof) or asof < cut["day_ymd"]
    if not asof:
        reason = "缺 l1_report.json 或无 asof"
    elif stale:
        reason = (
            f"data_asof {asof} 早于最近已收日盘 {cut['day_ymd']}；"
            "Actions 预定 15:30，实际可能延迟（10/30 至 22:28 才完成），先标待核"
        )
    else:
        reason = ""
    night_after = asof and asof <= cut["night_ymd"] and night_n > 0
    night_note = (
        f"不含夜盘：{night_n} 个夜盘品种仍以 {asof or '—'} 15:00 日盘为准"
        + ("，其后夜盘已收，未反映" if night_after else "")
        if night_n
        else "不含夜盘"
    )
    return {
        "data_asof": asof or None,
        "includes_night": False,
        "night_codes_n": night_n,
        "expected_day_ymd": cut["day_ymd"],
        "expected_night_ymd": cut["night_ymd"],
        "stale": bool(stale),
        "status": "待核" if stale else "已到",
        "reason": reason,
        "night_note": night_note,
        "checked_at": now.strftime("%Y-%m-%d %H:%M (UTC+8)"),
    }


def render_freshness_header(root: Path, page: str) -> dict:
    import streamlit as st

    f = desk_freshness(root)
    line = (
        f"**{page}** · 数据截止 data_asof **{f['data_asof'] or '—'}** 15:00 日盘 · "
        f"含夜盘：**否** · {f['night_note']} · 校验于 {f['checked_at']}"
    )
    if f["stale"]:
        st.warning(f"【待核】{line}\n\n{f['reason']}")
    else:
        st.caption(f"{line} · 状态：已到")
    return f
