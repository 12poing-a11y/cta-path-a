# -*- coding: utf-8 -*-
"""Remind when Bid/Ask sample is enough for the next options upgrade (F2).

Does not auto-open upgrades. Soft: print / return payload for daily_update & desk.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.options.chain_store import list_snapshot_dates, load_snapshot

# Thresholds — research only; raise only after user confirms F2.
MIN_BIDASK_DAYS_PRIMARY = 10  # CF
MIN_BIDASK_DAYS_EACH = 5  # SR / MA
STAGE1_CODES = ("CF", "SR", "MA")
PRIMARY = "CF"

# Locked next-knife text (remind verbatim when ready or when asked).
NEXT_UPGRADE_ID = "F2"
NEXT_UPGRADE_TITLE = "含 Bid/Ask 的信用价差研究 BT"
NEXT_UPGRADE_BODY = (
    "用已落盘的活链 Bid/Ask 快照跑 credit_vertical 研究回测"
    "（pricing_mode=bid_ask），与 settle_discount 对照；"
    "策略状态仍最高 WARN，待人工评审；不写 Path-A paper_book / 正式 BT / seats。"
)

OUT_REL = Path("data") / "options" / "upgrade_gate_latest.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _is_bidask_snap(snap: dict[str, Any] | None) -> bool:
    if not snap:
        return False
    n = int(snap.get("n_with_bid_ask") or 0)
    if n > 0:
        return True
    q = snap.get("quality") or {}
    if int(q.get("n_with_bid_ask") or 0) > 0:
        return True
    src = str(snap.get("source") or "")
    return "tq_live" in src and (snap.get("quality") or {}).get("status") in {"OK", "WARN"}


def count_bidask_days(root: Path, code: str) -> dict[str, Any]:
    dates = list_snapshot_dates(root, code)
    hit: list[str] = []
    for asof in dates:
        if _is_bidask_snap(load_snapshot(root, code, asof)):
            hit.append(asof)
    return {
        "code": code,
        "n_snapshots": len(dates),
        "n_bidask_days": len(hit),
        "bidask_dates": hit,
        "latest_bidask": hit[-1] if hit else None,
    }


def assess_upgrade_readiness(root: Path) -> dict[str, Any]:
    by_code = {c: count_bidask_days(root, c) for c in STAGE1_CODES}
    cf_n = by_code[PRIMARY]["n_bidask_days"]
    each_ok = all(by_code[c]["n_bidask_days"] >= MIN_BIDASK_DAYS_EACH for c in STAGE1_CODES)
    primary_ok = cf_n >= MIN_BIDASK_DAYS_PRIMARY
    ready = bool(primary_ok or each_ok)

    reasons: list[str] = []
    if not primary_ok:
        reasons.append(
            f"{PRIMARY} bidask_days={cf_n}/{MIN_BIDASK_DAYS_PRIMARY}"
        )
    if not each_ok:
        for c in STAGE1_CODES:
            n = by_code[c]["n_bidask_days"]
            if n < MIN_BIDASK_DAYS_EACH:
                reasons.append(f"{c} bidask_days={n}/{MIN_BIDASK_DAYS_EACH}")

    return {
        "schema": "cta-options-upgrade-gate-v1",
        "built_at": _iso_now(),
        "ready": ready,
        "next_upgrade_id": NEXT_UPGRADE_ID,
        "next_upgrade_title": NEXT_UPGRADE_TITLE,
        "next_upgrade_body": NEXT_UPGRADE_BODY,
        "thresholds": {
            "primary_code": PRIMARY,
            "min_bidask_days_primary": MIN_BIDASK_DAYS_PRIMARY,
            "min_bidask_days_each": MIN_BIDASK_DAYS_EACH,
            "codes": list(STAGE1_CODES),
        },
        "by_code": by_code,
        "gap_reasons": reasons if not ready else [],
        "reminder": (
            f"【升级提醒】样本已够 → 可开 {NEXT_UPGRADE_ID}：{NEXT_UPGRADE_TITLE}。"
            f"内容：{NEXT_UPGRADE_BODY}"
            if ready
            else (
                f"【待升级】下次确定开 {NEXT_UPGRADE_ID}：{NEXT_UPGRADE_TITLE}。"
                f"样本未够：{'; '.join(reasons)}。"
                f"内容预告：{NEXT_UPGRADE_BODY}"
            )
        ),
    }


def write_gate(root: Path, report: dict[str, Any] | None = None) -> dict[str, Any]:
    rep = report or assess_upgrade_readiness(root)
    path = Path(root) / OUT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    rep["path"] = str(path)
    return rep


def remind_line(root: Path, *, write: bool = True) -> str:
    rep = write_gate(root) if write else assess_upgrade_readiness(root)
    return str(rep.get("reminder") or "")
