# -*- coding: utf-8 -*-
"""Judgement state for the shadow start gate (design §9).

A trading day is "normal" only if every check passed (see run.judge_day). The streak is recomputed from the judged days
in date order: it is the number of consecutive normal judged trading days at the end of the sequence. Closed (non-trading)
weekdays are listed in `closed` and never break or extend the streak. Re-judging an abnormal day is allowed (e.g. a later
DCE recovery); a normal day is final and is not re-judged. Nothing is silently overwritten: each judgement is kept in history.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C
from .store import utc_now


def empty() -> dict:
    return {"streak": 0, "days": {}, "closed": [], "history": []}


def load(path: Path | None = None) -> dict:
    p = Path(path or C.STATE)
    if p.exists():
        st = json.loads(p.read_text(encoding="utf-8"))
        st.setdefault("closed", [])
        return st
    return empty()


def save(st: dict, path: Path | None = None) -> None:
    p = Path(path or C.STATE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def recompute_streak(st: dict) -> int:
    streak = 0
    for day in sorted(st["days"]):
        streak = streak + 1 if st["days"][day]["normal"] else 0
    return streak


def is_final_normal(st: dict, day: str) -> bool:
    return bool(st["days"].get(day, {}).get("normal"))


def judge(st: dict, day: str, normal: bool, reasons: list[str]) -> dict:
    if is_final_normal(st, day):
        return st  # normal judgement is final
    st["days"][day] = {"normal": normal, "reasons": reasons, "judged_utc": utc_now()}
    st["streak"] = recompute_streak(st)
    st["history"] = (st.get("history") or [])[-300:] + [{"day": day, "normal": normal, "streak_after": st["streak"], "utc": utc_now()}]
    return st


def mark_closed(st: dict, day: str) -> dict:
    if day not in st["closed"]:
        st["closed"] = sorted(st["closed"] + [day])
    return st


def gate_ready(st: dict) -> bool:
    return st["streak"] >= C.NORMAL_STREAK_REQUIRED
