# -*- coding: utf-8 -*-
"""Sync CTA reports into Notion via official API (for GitHub Actions)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
IDS = json.loads((ROOT / "notion_ids.json").read_text(encoding="utf-8"))

NOTION_VERSION = "2022-06-28"
SIGNALS_DB = IDS.get("signals_db_id") or "8ee24dca-b4e0-4df9-985c-2451ee4004c4"
BACKTEST_DB = IDS.get("backtest_db_id") or "7c3494b2-7936-4fc5-86dd-a3071ef83dd5"
ANNUAL_REPORT_DB = IDS.get("annual_report_db_id") or "0a0961c3-badd-46ef-b9af-cd2578838c30"
ANNUAL_CURVE_DB = IDS.get("annual_curve_db_id") or "29b3f011-d871-4727-9a09-b66f2d96f1d3"


def _token():
    return (os.environ.get("NOTION_TOKEN") or "").strip()


def _headers():
    tok = _token()
    if not tok:
        raise RuntimeError("缺少 NOTION_TOKEN")
    return {
        "Authorization": f"Bearer {tok}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _create_page(parent_db: str, props: dict):
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_headers(),
        json={"parent": {"database_id": parent_db}, "properties": props},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:500]}")
    return r.json()


def _title(text: str):
    return {"title": [{"text": {"content": str(text)[:2000]}}]}


def _rich(text: str):
    return {"rich_text": [{"text": {"content": str(text or "")[:1900]}}]}


def _num(v):
    if v is None:
        return {"number": None}
    return {"number": float(v)}


def _safe_action(text: str) -> str:
    """Never write secrets / MCP JSON blobs into Notion action notes."""
    s = str(text or "")
    low = s.lower()
    if "authorization" in low or "mcpservers" in low or "eyjrawqi" in low:
        if s.startswith("拉取失败"):
            return "拉取失败: iFinD 鉴权/配置异常（详情已省略）"
        return "（敏感错误详情已省略）"
    return s[:500]


def _select(name: str | None):
    if not name:
        return {"select": None}
    return {"select": {"name": str(name)}}


def _date(iso: str):
    return {"date": {"start": iso}}


def sync_signals(report_path: Path | None = None):
    path = report_path or (ROOT / "l1_report_risk15.json")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("skipped"):
        print("[notion] skipped:", report.get("skipped"))
        return 0
    asof = str(report.get("asof") or "")
    date = f"{asof[:4]}-{asof[4:6]}-{asof[6:8]}" if len(asof) == 8 else asof
    key_slot = (os.environ.get("IFIND_ACTIVE_SLOT") or "primary").strip() or "primary"
    n = 0
    for s in report.get("signals") or []:
        code = s.get("code") or "?"
        props = {
            "Name": _title(f"{date} {code}"),
            "日期": _date(date),
            "品种": _select(code),
            "方向": _select(s.get("direction") or "空仓"),
            "手数": _num(s.get("lots_l1") or 0),
            "收盘": _num(s.get("close")),
            "R20": _num(s.get("r20")),
            "R60": _num(s.get("r60")),
            "ATR14": _num(s.get("atr")),
            "每手风险": _num(s.get("risk_per_lot")),
            "对齐": _select(s.get("align") or "冲突/不足"),
            "动作": _rich(_safe_action(s.get("action") or s.get("error") or "")),
            "Key槽": _select(key_slot if key_slot in ("primary", "backup") else "primary"),
        }
        _create_page(SIGNALS_DB, props)
        n += 1
        print(f"[notion] signal {code}")
    print(f"[notion] wrote {n} signals")
    return 0


def sync_backtest(path: Path | None = None):
    p = path or (ROOT / "weekly_backtest_latest.json")
    b = json.loads(p.read_text(encoding="utf-8"))
    start = b.get("start") or b.get("asof") or ""
    end = b.get("end") or b.get("asof") or ""
    if len(str(start)) == 8:
        start = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
    if len(str(end)) == 8:
        end = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
    name = f"周报 {start}→{end}" if start and end else f"回测 {b.get('asof')}"
    props = {
        "Name": _title(name),
        "交易日数": _num(b.get("trade_days")),
        "期末权益": _num(b.get("equity_end")),
        "期间收益%": _num(b.get("ret_pct")),
        "最大回撤%": _num(b.get("max_dd_pct")),
        "胜率%": _num(b.get("win_rate")),
        "持仓品种数均值": _num(b.get("avg_held")),
        "规则违约次数": _num(b.get("violations")),
        "结论": _select(b.get("conclusion") or "继续L1"),
        "摘要": _rich(b.get("summary") or ""),
        "明细": _rich(b.get("detail") or ""),
    }
    if start:
        props["周期起点"] = _date(start)
    if end:
        props["周期终点"] = _date(end)
    _create_page(BACKTEST_DB, props)
    print("[notion] backtest row ok")
    return 0


def sync_annual(path: Path | None = None):
    """Write 1y backtest summary + weekly equity curve into dedicated Notion DBs."""
    p = path or (ROOT / "historical_backtest_latest.json")
    b = json.loads(p.read_text(encoding="utf-8"))
    if not b.get("ok"):
        print("[notion] annual skip — backtest not ok:", b.get("error"))
        return 1
    start = b.get("start") or ""
    end = b.get("end") or ""
    name = f"一年回测 {start}→{end}"
    props = {
        "Name": _title(name),
        "交易日数": _num(b.get("trade_days")),
        "期末权益": _num(b.get("equity_end")),
        "期间收益%": _num(b.get("ret_pct")),
        "最大回撤%": _num(b.get("max_dd_pct")),
        "胜率%": _num(b.get("win_rate")),
        "持仓品种数均值": _num(b.get("avg_held")),
        "品种数": _num(b.get("universe_n")),
        "结论": _select(b.get("conclusion") or "继续L1"),
        "摘要": _rich(b.get("summary") or ""),
        "品种池": _rich(b.get("universe") or ""),
        "明细": _rich(
            json.dumps(
                {"bars": b.get("bars"), "errors": b.get("errors"), "final": b.get("final_positions")},
                ensure_ascii=False,
            )[:1800]
        ),
    }
    if start:
        props["周期起点"] = _date(start)
    if end:
        props["周期终点"] = _date(end)
    _create_page(ANNUAL_REPORT_DB, props)
    print("[notion] annual report row ok")

    batch = b.get("batch") or "2026一年"
    full = b.get("equity_curve") or []
    curve = b.get("equity_curve_weekly") or full
    if len(curve) > 80:
        step = max(1, len(curve) // 72)
        curve = list(curve[::step])
        if full and (not curve or curve[-1].get("date") != full[-1].get("date")):
            curve.append(full[-1])
    n = 0
    for row in curve:
        d = row.get("date") or ""
        props_c = {
            "Name": _title(d),
            "日期": _date(d) if d else _date(end or start),
            "权益": _num(row.get("equity")),
            "持仓数": _num(row.get("held")),
            "日盈亏": _num(row.get("pnl")),
            "回撤%": _num(row.get("dd_pct")),
            "批次": _select(batch if batch in ("2026一年", "其他") else "2026一年"),
        }
        _create_page(ANNUAL_CURVE_DB, props_c)
        n += 1
    print(f"[notion] annual curve rows={n}")
    return 0


if __name__ == "__main__":
    if not _token():
        print("[notion] NOTION_TOKEN empty — skip sync")
        raise SystemExit(0)
    mode = (sys.argv[1] if len(sys.argv) > 1 else "signals").lower()
    if mode == "backtest":
        raise SystemExit(sync_backtest())
    if mode in ("annual", "annual_backtest", "1y"):
        raise SystemExit(sync_annual())
    raise SystemExit(sync_signals())

