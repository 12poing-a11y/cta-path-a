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
TRADES_DB = IDS.get("trades_db_id") or "845ee89c-668a-40f1-adbe-e1a220136d5b"
HUB_PAGE = IDS.get("hub_page_id") or "3feca62a-b5a7-81ea-8dbb-d11f41642f19"
RULES_PAGE = (IDS.get("rules_page_id") or "").strip()

# Variety display = dominant contract + Chinese name (e.g. CF2701 棉花).
# Signals SELECT「品种」stays short root codes for stable filters.
_VARIETY_NAME_CACHE: dict[str, str] | None = None


# Fallback Chinese names for codes that may appear in older Notion rows
# but are not in the current universe.json pool.
_FALLBACK_NAMES = {
    "JM": "焦煤",
    "Y": "豆油",
    "OI": "菜油",
    "I": "铁矿石",
    "HC": "热卷",
    "CU": "铜",
    "AL": "铝",
    "AG": "沪银",
    "AU": "沪金",
    "ZN": "锌",
    "NI": "镍",
    "SN": "锡",
    "PB": "铅",
    "SC": "原油",
    "AP": "苹果",
    "CJ": "红枣",
    "RM": "菜粕",
    "CS": "玉米淀粉",
    "C": "玉米",
    "A": "豆一",
    "B": "豆二",
}


def _variety_name_map() -> dict[str, str]:
    global _VARIETY_NAME_CACHE
    if _VARIETY_NAME_CACHE is not None:
        return _VARIETY_NAME_CACHE
    out: dict[str, str] = dict(_FALLBACK_NAMES)
    try:
        uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
        for row in uni.get("symbols") or []:
            code = str(row.get("code") or "").upper()
            name = str(row.get("name") or "").strip()
            if code and name:
                out[code] = name
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    _VARIETY_NAME_CACHE = out
    return out


def _variety_label(code: str) -> str:
    """Full desk-style label: ``CF2701 棉花`` (falls back to root code)."""
    code = str(code or "").upper().strip()
    if not code or code in ("?", "ALL"):
        return code or "?"
    name = _variety_name_map().get(code, "")
    try:
        from desk.loaders import format_variety_label

        return format_variety_label(code, name, root=ROOT)
    except Exception:
        # Duplicate desk/loaders.format_variety_label logic if import fails.
        contract = ""
        try:
            from minute_data import resolve_dominant_contract

            dom = resolve_dominant_contract(ROOT, code)
            if isinstance(dom, dict):
                sym = str(dom.get("symbol") or "").upper()
                if sym and sym != f"{code}0":
                    contract = sym
        except Exception:
            pass
        head = contract or code
        return f"{head} {name}".strip() if name else head


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


def _prop_select_name(props: dict, key: str) -> str:
    sel = (props.get(key) or {}).get("select") or {}
    return str(sel.get("name") or "")


def _prop_date_start(props: dict, key: str) -> str:
    raw = (props.get(key) or {}).get("date") or {}
    return str(raw.get("start") or "")[:10]


def _signal_pages_for_date(date: str) -> dict[str, list[dict]]:
    """Map root code → Notion pages on that calendar day."""
    pages = _query_db(
        SIGNALS_DB,
        {"property": "日期", "date": {"equals": date}},
    )
    by_code: dict[str, list[dict]] = {}
    for page in pages:
        props = page.get("properties") or {}
        code = _prop_select_name(props, "品种").upper()
        if not code:
            continue
        by_code.setdefault(code, []).append(page)
    return by_code


def dedupe_signal_pages(*, on_or_after: str | None = None) -> dict[str, int]:
    """Archive extra rows sharing the same 日期+品种; keep the newest edit."""
    filt = None
    if on_or_after:
        filt = {"property": "日期", "date": {"on_or_after": on_or_after}}
    pages = _query_db(SIGNALS_DB, filt)
    groups: dict[tuple[str, str], list[dict]] = {}
    for page in pages:
        props = page.get("properties") or {}
        day = _prop_date_start(props, "日期")
        code = _prop_select_name(props, "品种").upper()
        if not day or not code:
            continue
        groups.setdefault((day, code), []).append(page)
    archived = 0
    kept = 0
    for (_day, _code), plist in groups.items():
        if len(plist) <= 1:
            kept += len(plist)
            continue
        plist.sort(
            key=lambda p: p.get("last_edited_time") or p.get("created_time") or "",
            reverse=True,
        )
        kept += 1
        for extra in plist[1:]:
            _archive_page(extra["id"])
            archived += 1
    print(f"[notion] signals dedupe kept={kept} archived={archived}")
    return {"kept": kept, "archived": archived}


def sync_signals(report_path: Path | None = None):
    """Upsert one row per 日期+品种; archive duplicates instead of stacking."""
    path = report_path or (ROOT / "l1_report_risk15.json")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("skipped"):
        print("[notion] skipped:", report.get("skipped"))
        return 0
    asof = str(report.get("asof") or "")
    date = f"{asof[:4]}-{asof[4:6]}-{asof[6:8]}" if len(asof) == 8 else asof
    key_slot = (os.environ.get("IFIND_ACTIVE_SLOT") or "primary").strip() or "primary"
    by_code = _signal_pages_for_date(date)
    created = updated = archived = 0
    for s in report.get("signals") or []:
        code = str(s.get("code") or "?").upper()
        label = _variety_label(code)
        props = {
            "Name": _title(f"{date} {label}"),
            "日期": _date(date),
            # SELECT stays short root codes (CF/SR/...) for stable filtering.
            "品种": _select(code if code != "?" else None),
            "方向": _select(s.get("direction") or "空仓"),
            "手数": _num(s.get("lots_l1") or 0),
            "收盘": _num(s.get("close")),
            "R20": _num(s.get("r20")),
            "R60": _num(s.get("r60")),
            "ATR14": _num(s.get("atr")),
            "每手风险": _num(s.get("risk_per_lot")),
            "对齐": _select(s.get("align") or "冲突/不足"),
            "动作": _rich(_safe_action(s.get("action") or s.get("error") or "")),
            "备注": _rich(label),
            "Key槽": _select(key_slot if key_slot in ("primary", "backup") else "primary"),
        }
        pages = by_code.pop(code, []) if code != "?" else []
        pages.sort(
            key=lambda p: p.get("last_edited_time") or p.get("created_time") or "",
            reverse=True,
        )
        if not pages:
            _create_page(SIGNALS_DB, props)
            created += 1
            print(f"[notion] signal create {label}")
        else:
            _update_page(pages[0]["id"], props)
            updated += 1
            print(f"[notion] signal update {label}")
            for extra in pages[1:]:
                _archive_page(extra["id"])
                archived += 1
    print(
        f"[notion] signals date={date} created={created} updated={updated} "
        f"archived_dupes={archived}"
    )
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


def _exit_label(reason: str | None) -> str:
    r = str(reason or "")
    if r in ("target", "stop", "signal"):
        return r
    return "其他" if r else "其他"


def _execution_ssot() -> dict:
    """Single source of truth for live paper params (universe + execution_rules)."""
    out: dict = {}
    try:
        uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
        sel = uni.get("selection") if isinstance(uni.get("selection"), dict) else {}
        out.update(
            {
                "reward_rr": sel.get("reward_rr", uni.get("reward_rr")),
                "stop_atr_mult": sel.get("stop_atr_mult", uni.get("stop_atr_mult")),
                "min_r20": uni.get("min_r20_pct"),
                "min_r60": uni.get("min_r60_pct"),
                "max_positions": uni.get("max_positions"),
                "mode": uni.get("entry_filter"),
                "max_portfolio_risk_pct": uni.get("max_portfolio_risk_pct"),
                "carry_bypass": uni.get("carry_bypass"),
                "vol_bypass": uni.get("vol_bypass"),
            }
        )
    except Exception:
        pass
    try:
        er = json.loads((ROOT / "execution_rules.json").read_text(encoding="utf-8"))
        if isinstance(er, dict) and er.get("ok"):
            out.setdefault("reward_rr", er.get("reward_rr"))
            out.setdefault("stop_atr_mult", er.get("stop_atr_mult"))
            if er.get("carry_bypass") is not None:
                out["carry_bypass"] = er.get("carry_bypass")
            if er.get("vol_bypass") is not None:
                out["vol_bypass"] = er.get("vol_bypass")
            out["summary_zh"] = er.get("summary_zh")
            out["ssot"] = "execution_rules.json + universe.selection"
    except Exception:
        pass
    return out


def _rules_text(b: dict) -> str:
    rules = b.get("entry_exit_rules") or {}
    exits = b.get("exits") or {}
    ssot = _execution_ssot()
    params = (rules.get("params") if isinstance(rules, dict) else None) or {
        "reward_rr": b.get("reward_rr"),
        "stop_atr_mult": b.get("stop_atr_mult"),
        "min_r20": b.get("min_r20_pct"),
        "min_r60": b.get("min_r60_pct"),
        "max_positions": b.get("max_positions"),
        "mode": b.get("mode"),
    }
    # Prefer live execution SSOT over stale backtest blob when present.
    for key in ("reward_rr", "stop_atr_mult", "min_r20", "min_r60", "max_positions", "mode"):
        if ssot.get(key) is not None:
            params[key] = ssot[key]
    open_txt = (rules.get("open") if isinstance(rules, dict) else None) or (
        "r20/r60同向且幅度达标；席位/过滤；组合帽；ATR止损止盈。"
    )
    close_txt = (rules.get("close") if isinstance(rules, dict) else None) or (
        "止损(stop) / 止盈(target) / 趋势失效(signal)。"
    )
    open_pos, open_asof = _open_positions_for_sync(b)
    lines = [
        f"批次: {b.get('batch')}",
        f"区间: {b.get('start')}→{b.get('end')}  模式: {params.get('mode') or b.get('mode')}",
        f"执行SSOT: stop={params.get('stop_atr_mult')}×ATR / RR={params.get('reward_rr')} "
        f"（{ssot.get('ssot') or 'backtest JSON'}）",
        f"参数: RR={params.get('reward_rr')} stopATR={params.get('stop_atr_mult')} "
        f"min_r20={params.get('min_r20')} min_r60={params.get('min_r60')} "
        f"max_pos={params.get('max_positions')}",
    ]
    if ssot.get("summary_zh"):
        lines.append(str(ssot["summary_zh"]))
    lines.extend(
        [
            "",
            "【建仓条件】",
            str(open_txt),
            "",
            "【平仓条件】",
            str(close_txt),
            "",
            "【回测统计】",
            f"净收益%={b.get('ret_pct')} MaxDD%={b.get('max_dd_pct')} "
            f"日胜率%={b.get('win_rate')} 笔胜率%={b.get('trade_win_rate')}",
            f"闭环笔数={b.get('closed_trades')} 期望R={b.get('expectancy_r')} "
            f"均赢R={b.get('avg_win_r')} 均亏R={b.get('avg_loss_r')} 实现RR={b.get('realized_rr')}",
            f"平仓构成 target={exits.get('target')} stop={exits.get('stop')} signal={exits.get('signal')}",
            f"模拟仓持仓(asof {open_asof})={[ _variety_label(c) for c in open_pos.keys() ]}",
            f"回测期末持仓={[ _variety_label(c) for c in (b.get('final_positions') or {}).keys() ]}",
            f"结论={b.get('conclusion')}",
        ]
    )
    return "\n".join(lines)


def _query_db(db_id: str, filter_obj: dict | None = None, *, page_size: int = 100) -> list[dict]:
    """Paginated Notion database query."""
    results: list[dict] = []
    cursor = None
    while True:
        body: dict = {"page_size": page_size}
        if filter_obj:
            body["filter"] = filter_obj
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=_headers(),
            json=body,
            timeout=60,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Notion query {r.status_code}: {r.text[:400]}")
        payload = r.json()
        results.extend(payload.get("results") or [])
        if not payload.get("has_more"):
            break
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return results


def _plain_rich(prop: dict | None) -> str:
    if not prop:
        return ""
    chunks = prop.get("rich_text") or prop.get("title") or []
    return "".join(str(c.get("plain_text") or "") for c in chunks)


def _archive_page(page_id: str) -> None:
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=_headers(),
        json={"archived": True},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Notion archive {r.status_code}: {r.text[:300]}")


def _update_page(page_id: str, props: dict) -> None:
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=_headers(),
        json={"properties": props},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Notion update {r.status_code}: {r.text[:400]}")


def _closed_dedupe_key(d: str, code: str, reason: str, r_mult) -> str:
    return f"{d}|{str(code).upper()}|{reason}|{r_mult}"


def _open_positions_for_sync(b: dict) -> tuple[dict[str, dict], str]:
    """Prefer paper_book_latest positions; else backtest final_positions."""
    try:
        from paper_book import load_paper_positions

        paper = load_paper_positions(ROOT)
        if paper.get("ok") and paper.get("positions"):
            return dict(paper["positions"]), str(paper.get("end") or b.get("end") or "")
    except Exception:
        pass
    raw = b.get("final_positions") if isinstance(b.get("final_positions"), dict) else {}
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[str(k).upper()] = v
    return out, str(b.get("end") or "")


def sync_trades(path: Path | None = None, *, limit: int = 80):
    """Sync closed/open paper trades + rules; upsert open book, dedupe closes."""
    if not TRADES_DB:
        print("[notion] trades_db_id missing — skip")
        return 1
    p = path or (ROOT / "historical_backtest_latest.json")
    b = json.loads(p.read_text(encoding="utf-8"))
    if not b.get("ok"):
        print("[notion] trades skip — backtest not ok:", b.get("error"))
        return 1

    batch = str(b.get("batch") or "pathA")
    rules_blob = _rules_text(b)
    rules_name = f"规则+统计 {b.get('start')}→{b.get('end')}"
    # Upsert single rules summary row by Name
    existing_rules = _query_db(
        TRADES_DB,
        {
            "and": [
                {"property": "品种", "rich_text": {"equals": "ALL"}},
                {"property": "批次", "rich_text": {"equals": batch}},
            ]
        },
    )
    rules_props = {
        "Name": _title(rules_name),
        "日期": _date(str(b.get("end") or b.get("start") or "1970-01-01")),
        "品种": _rich("ALL"),
        "方向": _select("未知"),
        "事件": _select("平仓"),
        "建仓原因": _rich("见备注·建仓条件"),
        "平仓原因": _select("其他"),
        "R倍数": _num(b.get("expectancy_r")),
        "批次": _rich(batch),
        "备注": _rich(rules_blob),
    }
    if existing_rules:
        _update_page(existing_rules[0]["id"], rules_props)
        print("[notion] trades rules+stats row updated")
    else:
        _create_page(TRADES_DB, rules_props)
        print("[notion] trades rules+stats row ok")

    # Existing closed keys for this batch (dedupe)
    closed_pages = _query_db(
        TRADES_DB,
        {
            "and": [
                {"property": "事件", "select": {"equals": "平仓"}},
                {"property": "批次", "rich_text": {"equals": batch}},
            ]
        },
    )
    existing_closed: set[str] = set()
    for page in closed_pages:
        props = page.get("properties") or {}
        if _plain_rich(props.get("品种")) == "ALL":
            continue
        note = _plain_rich(props.get("备注"))
        name = _plain_rich(props.get("Name"))
        # Prefer explicit root= in note; else parse Name "YYYY-MM-DD LABEL 平仓·reason"
        root_code = ""
        if "root=" in note:
            root_code = note.split("root=", 1)[1].split(";", 1)[0].strip().upper()
        d = ""
        date_prop = props.get("日期") or {}
        if date_prop.get("date"):
            d = str((date_prop["date"] or {}).get("start") or "")[:10]
        reason_sel = ((props.get("平仓原因") or {}).get("select") or {}).get("name") or ""
        r_mult = (props.get("R倍数") or {}).get("number")
        if root_code and d:
            existing_closed.add(_closed_dedupe_key(d, root_code, reason_sel, r_mult))
        elif name:
            existing_closed.add(f"name|{name}")

    n = 0
    skipped = 0
    closed = list(b.get("closed_pnls_tail") or [])[-limit:]
    # Also append paper_book closed_today if present
    try:
        from paper_book import load_paper_positions

        paper = load_paper_positions(ROOT)
        for t in paper.get("closed_today") or []:
            closed.append(t)
    except Exception:
        pass

    for t in closed:
        code = str(t.get("code") or "?").upper()
        label = _variety_label(code)
        d = str(t.get("date") or b.get("end") or "")
        reason = str(t.get("reason") or "")
        entry_reason = str(t.get("entry_reason") or "path_a / composite_trend")
        direction = t.get("direction") or "未知"
        if direction not in ("多", "空"):
            direction = "未知"
        r_mult = t.get("R")
        key = _closed_dedupe_key(d, code, _exit_label(reason), r_mult)
        name = f"{d} {label} 平仓·{reason}"
        if key in existing_closed or f"name|{name}" in existing_closed:
            skipped += 1
            continue
        note = (
            f"root={code};品种={label}；建仓日={t.get('entry_date') or '?'} 建仓因={entry_reason}；"
            f"平仓因={reason}（target止盈/stop止损/signal趋势失效）；"
            f"R={r_mult}"
        )
        props = {
            "Name": _title(name),
            "日期": _date(d),
            "品种": _rich(label),
            "方向": _select(direction),
            "事件": _select("平仓"),
            "建仓原因": _rich(entry_reason),
            "平仓原因": _select(_exit_label(reason)),
            "R倍数": _num(r_mult),
            "入场价": _num(t.get("entry")),
            "出场价": _num(t.get("exit")),
            "手数": _num(t.get("lots")),
            "批次": _rich(batch),
            "备注": _rich(note),
        }
        _create_page(TRADES_DB, props)
        existing_closed.add(key)
        existing_closed.add(f"name|{name}")
        n += 1

    # Open book: archive old 持仓中 for batch, write current set (idempotent snapshot)
    open_pages = _query_db(
        TRADES_DB,
        {"property": "事件", "select": {"equals": "持仓中"}},
    )
    archived = 0
    for page in open_pages:
        props = page.get("properties") or {}
        page_batch = _plain_rich(props.get("批次"))
        if page_batch and page_batch != batch:
            continue
        _archive_page(page["id"])
        archived += 1
    print(f"[notion] archived old 持仓中={archived}")

    positions, asof = _open_positions_for_sync(b)
    for code, ppos in positions.items():
        if not isinstance(ppos, dict):
            continue
        code = str(code or "?").upper()
        label = _variety_label(code)
        direction = ppos.get("direction") or "未知"
        if direction not in ("多", "空"):
            direction = "未知"
        entry_reason = str(ppos.get("reason") or "path_a")
        d = str(ppos.get("entry_date") or asof or b.get("end") or "")
        note = (
            f"root={code};品种={label}；持仓中：建仓因={entry_reason}；"
            f"止损={ppos.get('stop')} 止盈={ppos.get('target')}；"
            f"r20={ppos.get('r20')} r60={ppos.get('r60')}；asof={asof}"
        )
        props = {
            "Name": _title(f"{asof or d} {label} 持仓中"),
            "日期": _date(asof or d if (asof or d) else str(b.get("end"))),
            "品种": _rich(label),
            "方向": _select(direction),
            "事件": _select("持仓中"),
            "建仓原因": _rich(entry_reason),
            "平仓原因": _select("其他"),
            "入场价": _num(ppos.get("entry")),
            "手数": _num(ppos.get("lots")),
            "批次": _rich(batch),
            "备注": _rich(note),
        }
        _create_page(TRADES_DB, props)
        n += 1

    print(f"[notion] trades rows={n} skipped_dup_closed={skipped} (+1 rules)")
    _sync_rules_page(b)
    return 0


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": str(text)[:1900]}}]
        },
    }


def _sync_rules_page(b: dict):
    """Create or refresh a hub child page with entry/exit rules + backtest stats."""
    global RULES_PAGE
    body = _rules_text(b)
    title = f"【已落地】建平仓规则与回测统计（{b.get('end') or ''}）"
    children = [
        _paragraph(
            "纸面记账，不下单。开仓账面优先 paper_book_latest.json；"
            "KPI/平仓尾来自 historical_backtest_latest.json；执行参数以 execution_rules.json + universe.selection 为准。"
        ),
        _paragraph(body),
    ]
    page_id = RULES_PAGE
    if not page_id:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=_headers(),
            json={
                "parent": {"page_id": HUB_PAGE},
                "properties": {"title": [{"text": {"content": title[:2000]}}]},
                "children": children,
            },
            timeout=60,
        )
        if r.status_code >= 400:
            print("[notion] rules page create failed:", r.status_code, r.text[:300])
            return
        page_id = r.json().get("id") or ""
        if page_id:
            IDS["rules_page_id"] = page_id
            IDS["rules_page_url"] = f"https://app.notion.com/{page_id.replace('-', '')}"
            (ROOT / "notion_ids.json").write_text(
                json.dumps(IDS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            RULES_PAGE = page_id
            print("[notion] rules page created", page_id)
        return
    # Refresh: append a new snapshot block (keeps history)
    try:
        r = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=_headers(),
            json={"children": [_paragraph(f"—— 更新 {b.get('end')} ——"), _paragraph(body)]},
            timeout=60,
        )
        if r.status_code >= 400:
            # Notion API uses PATCH .../children with "children" in some clients;
            # official is PATCH https://api.notion.com/v1/blocks/{block_id}/children
            print("[notion] rules page append failed:", r.status_code, r.text[:300])
        else:
            print("[notion] rules page updated", page_id)
    except Exception as e:
        print("[notion] rules page update error:", e)


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
    exits = b.get("exits") or {}
    stats_detail = {
        "exits": exits,
        "closed_trades": b.get("closed_trades"),
        "trade_win_rate": b.get("trade_win_rate"),
        "expectancy_r": b.get("expectancy_r"),
        "avg_win_r": b.get("avg_win_r"),
        "avg_loss_r": b.get("avg_loss_r"),
        "realized_rr": b.get("realized_rr"),
        "final": b.get("final_positions"),
        "rules": b.get("entry_exit_rules") or {
            "open": "r20/r60同向+过滤+组合帽；ATR止损止盈",
            "close": "stop / target / signal",
        },
    }
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
        "摘要": _rich(
            (b.get("summary") or "")
            + f" | 平仓 target={exits.get('target')} stop={exits.get('stop')} "
            f"signal={exits.get('signal')} 笔胜率={b.get('trade_win_rate')}% "
            f"期望R={b.get('expectancy_r')}"
        ),
        "品种池": _rich(
            "、".join(_variety_label(c) for c in (b.get("universe") or []))
            if isinstance(b.get("universe"), list)
            else str(b.get("universe") or "")
        ),
        "明细": _rich(json.dumps(stats_detail, ensure_ascii=False)[:1800]),
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

    # Always push trade ledger + rules with annual sync
    sync_trades(p)
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
    if mode in ("trades", "trade", "ledger"):
        raise SystemExit(sync_trades())
    if mode in ("dedupe", "dedupe_signals"):
        since = sys.argv[2] if len(sys.argv) > 2 else "2026-10-01"
        dedupe_signal_pages(on_or_after=since)
        raise SystemExit(0)
    raise SystemExit(sync_signals())


