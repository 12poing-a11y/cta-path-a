# -*- coding: utf-8 -*-
"""CF / CF2701 option hedge-pressure helpers for the seat board.

Premium series defaults to ATR-synthetic protective premium (1 lot) from local
continuous bars. Listed sina chain is used only as a soft end-point check.
Trade markers come from Path-A paper JSON (backtest + daily reports). Soft-fail;
never invent premiums or fills.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from desk.loaders import (
    dominant_contract_symbol,
    format_variety_label,
    load_json,
    load_universe,
    option_hedge_defaults,
)
from option_hedge import option_premium, option_strike
from option_compare import CODE_TO_SINA, compare_protective

CODE = "CF"
EXIT_ZH = {"target": "止盈", "stop": "止损", "signal": "趋势失效"}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso(ymd: str) -> str:
    s = str(ymd or "").replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(ymd or "")


def _read_bars(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    rows = raw if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or [])
    if not isinstance(rows, list):
        return []
    by_date: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _iso(str(row.get("date") or row.get("day") or row.get("时间") or ""))
        c = _num(row.get("close") or row.get("收盘价"))
        if not d or c is None:
            continue
        by_date[d] = {
            "date": d,
            "close": c,
            "high": _num(row.get("high") or row.get("最高价")),
            "low": _num(row.get("low") or row.get("最低价")),
            "open": _num(row.get("open") or row.get("开盘价")),
        }
    return [by_date[k] for k in sorted(by_date)]


def load_local_bars(root: Path, code: str) -> tuple[list[dict], str]:
    """Best local continuous series; prefers newest last bar. Offline only."""
    code = str(code or "").upper()
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
        bars = _read_bars(path)
        if not bars:
            continue
        stamp = path.parent.name
        last = str((bars[-1] or {}).get("date") or "")
        key = f"{last}-{len(bars):08d}-{stamp}"
        if key > best_key:
            best = bars
            best_key = key
            source = f".cache/sina/{stamp}/{path.name}" if "sina" in path.parts else str(path.name)
    return best, source



def _atr14(closes: list[float], highs: list[float | None], lows: list[float | None]) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    trs: list[float] = []
    for i in range(n):
        h = highs[i] if highs[i] is not None else closes[i]
        l = lows[i] if lows[i] is not None else closes[i]
        if i == 0:
            tr = float(h) - float(l)
        else:
            prev = closes[i - 1]
            tr = max(float(h) - float(l), abs(float(h) - prev), abs(float(l) - prev))
        trs.append(tr)
        if i >= 13:
            out[i] = sum(trs[i - 13 : i + 1]) / 14.0
    return out


def _cf_meta(root: Path) -> dict[str, Any]:
    uni = load_universe(root) or {}
    for row in uni.get("symbols") or []:
        if str(row.get("code") or "").upper() == CODE:
            return row
    return {"code": CODE, "name": "棉花", "mult": 5}


def _cf_display(root: Path, *, contract: str | None = None) -> str:
    meta = _cf_meta(root)
    return format_variety_label(
        CODE,
        str(meta.get("name") or "棉花"),
        contract=contract or dominant_contract_symbol(root, CODE),
        root=root,
    )


def load_cf_premium_series(root: Path, *, end_ymd: str = "", n_back: int = 70) -> pd.DataFrame:
    """Synthetic protective premium (1 lot) vs date from local CF0 bars."""
    bars, source = load_local_bars(root, CODE)
    if not bars:
        return pd.DataFrame()
    meta = _cf_meta(root)
    mult = float(meta.get("mult") or 5)
    oh = option_hedge_defaults(root)
    prem_m = float(oh["premium_atr_mult"])
    strike_m = float(oh["strike_atr_mult"])

    closes = [_num(b.get("close")) or 0.0 for b in bars]
    highs = [_num(b.get("high")) for b in bars]
    lows = [_num(b.get("low")) for b in bars]
    dates = [_iso(str(b.get("date") or "")) for b in bars]
    atrs = _atr14(closes, highs, lows)

    end = _iso(end_ymd) if end_ymd else (dates[-1] if dates else "")
    rows: list[dict[str, Any]] = []
    for i, d in enumerate(dates):
        if end and d > end:
            continue
        a = atrs[i]
        if a is None or a <= 0 or closes[i] <= 0:
            continue
        # Direction-agnostic observe premium: 1 lot ATM-ish protective cost proxy
        prem = option_premium(lots=1, atr=float(a), mult=mult, premium_atr_mult=prem_m)
        rows.append(
            {
                "date": d,
                "close": closes[i],
                "atr": round(float(a), 4),
                "premium": round(prem, 2),
                "premium_source": "合成ATR",
                "premium_atr_mult": prem_m,
                "strike_atr_mult": strike_m,
                "mult": mult,
                "bars_source": source,
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if n_back and n_back > 0 and len(df) > n_back:
        df = df.tail(n_back).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    # Soft end-point listed check (no network required if cache warm; else may soft-fail)
    if len(df):
        last = df.iloc[-1]
        strike = option_strike("多", float(last["close"]), float(last["atr"]), float(strike_m))
        cmp_ = compare_protective(
            CODE,
            direction="多",
            strike=strike,
            lots=1,
            mult=mult,
            synth_premium=float(last["premium"]),
        )
        df.attrs["listed_compare"] = cmp_
        df.attrs["product"] = CODE_TO_SINA.get(CODE, "棉花期权")
    return df


def _asof_iso(report: dict[str, Any] | None) -> str:
    if not report:
        return ""
    asof = str(report.get("asof") or "")
    return _iso(asof)


def _cf_signal(report: dict[str, Any] | None) -> dict[str, Any] | None:
    for sig in (report or {}).get("signals") or []:
        if str(sig.get("code") or "").upper() == CODE:
            return sig
    return None


def load_cf_trade_markers(root: Path) -> list[dict[str, Any]]:
    """Paper open/close markers for CF from backtest + daily archive diffs."""
    markers: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    bt = load_json(root / "historical_backtest_latest.json") or {}

    # Enter/exit from equity_curve held codes (covers trades outside closed_pnls_tail)
    curve = bt.get("equity_curve") or []
    prev_held = False
    for row in curve:
        if not isinstance(row, dict):
            continue
        d = _iso(str(row.get("date") or ""))
        held = CODE in {str(c).upper() for c in (row.get("codes") or [])}
        if held and not prev_held:
            key = (d, "建仓", "curve")
            if key not in seen:
                seen.add(key)
                markers.append(
                    {
                        "date": d,
                        "code": CODE,
                        "event": "建仓",
                        "condition": "回测权益曲线当日 codes 新含 CF（组合帽后入选）",
                        "direction": "未知",
                        "premium": None,
                        "premium_source": "",
                        "R": None,
                        "entry": None,
                        "exit": None,
                    }
                )
        if prev_held and not held:
            key = (d, "平仓", "curve")
            if key not in seen:
                seen.add(key)
                markers.append(
                    {
                        "date": d,
                        "code": CODE,
                        "event": "平仓",
                        "condition": "回测权益曲线当日 codes 不再含 CF（止损/止盈/信号或换仓）",
                        "direction": "未知",
                        "premium": None,
                        "premium_source": "",
                        "R": None,
                        "entry": None,
                        "exit": None,
                    }
                )
        prev_held = held

    for t in bt.get("closed_pnls_tail") or []:
        if str(t.get("code") or "").upper() != CODE:
            continue
        d = _iso(str(t.get("date") or ""))
        reason = str(t.get("reason") or "")
        key = (d, "平仓", reason)
        if key in seen:
            continue
        seen.add(key)
        entry_reason = str(t.get("entry_reason") or "path_a / composite_trend")
        cond = f"建仓因={entry_reason}；平仓={reason}（{EXIT_ZH.get(reason, reason)}）"
        markers.append(
            {
                "date": d,
                "code": CODE,
                "event": "平仓",
                "condition": cond,
                "direction": t.get("direction") or "未知",
                "premium": _num(t.get("opt_premium")),
                "premium_source": "回测opt_premium" if t.get("opt_premium") is not None else "",
                "R": _num(t.get("R")),
                "entry": _num(t.get("entry")),
                "exit": _num(t.get("exit")),
            }
        )

    for code, pos in (bt.get("final_positions") or {}).items():
        if str(code).upper() != CODE or not isinstance(pos, dict):
            continue
        d = _iso(str(pos.get("entry_date") or bt.get("end") or ""))
        reason = str(pos.get("reason") or "path_a")
        key = (d, "持仓中", reason)
        if key not in seen:
            seen.add(key)
            markers.append(
                {
                    "date": d,
                    "code": CODE,
                    "event": "持仓中",
                    "condition": f"建仓因={reason}；止损={pos.get('stop')} 止盈={pos.get('target')}",
                    "direction": pos.get("direction") or "未知",
                    "premium": _num(pos.get("opt_premium")),
                    "premium_source": "回测opt_premium" if pos.get("opt_premium") is not None else "",
                    "R": None,
                    "entry": _num(pos.get("entry")),
                    "exit": None,
                }
            )

    # Daily report enter/exit via archive adjacent selected flags
    archive = root / "archive"
    reports: list[tuple[str, dict[str, Any]]] = []
    latest = load_json(root / "l1_report.json")
    if latest and not latest.get("skipped"):
        reports.append((_asof_iso(latest), latest))
    if archive.is_dir():
        for path in sorted(archive.glob("l1_report_*.json")):
            m = re.search(r"l1_report_(\d{8})\.json$", path.name)
            if not m:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                continue
            if not isinstance(payload, dict) or payload.get("skipped"):
                continue
            reports.append((_iso(m.group(1)), payload))
    # unique by date, prefer latest file content
    by_date: dict[str, dict[str, Any]] = {}
    for d, payload in reports:
        if d:
            by_date[d] = payload
    ordered = sorted(by_date.items())
    prev_sel = False
    prev_dir = ""
    for d, payload in ordered:
        sig = _cf_signal(payload)
        selected = bool(sig and sig.get("selected"))
        direction = str((sig or {}).get("direction") or "")
        lots = int((sig or {}).get("lots_l1") or 0)
        if selected and not prev_sel:
            key = (d, "建仓", direction)
            if key not in seen:
                seen.add(key)
                markers.append(
                    {
                        "date": d,
                        "code": CODE,
                        "event": "建仓",
                        "condition": f"日报入选 selected=true；方向={direction}；手数={lots}；席位过滤后记账",
                        "direction": direction or "未知",
                        "premium": None,
                        "premium_source": "",
                        "R": None,
                        "entry": _num((sig or {}).get("close")),
                        "exit": None,
                    }
                )
        if prev_sel and not selected:
            key = (d, "平仓", "日报出选")
            if key not in seen:
                seen.add(key)
                markers.append(
                    {
                        "date": d,
                        "code": CODE,
                        "event": "平仓",
                        "condition": f"日报出选（昨{prev_dir}→今未入选）；非回测止损止盈笔",
                        "direction": prev_dir or "未知",
                        "premium": None,
                        "premium_source": "",
                        "R": None,
                        "entry": None,
                        "exit": _num((sig or {}).get("close")),
                    }
                )
        prev_sel = selected
        prev_dir = direction if selected else ""

    markers.sort(key=lambda m: (m.get("date") or "", m.get("event") or ""))
    contract = dominant_contract_symbol(root, CODE)
    label = _cf_display(root, contract=contract)
    for m in markers:
        m.setdefault("contract", contract)
        m["label"] = label
    return markers


def attach_marker_premiums(series: pd.DataFrame, markers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing marker premiums from the synthetic series on that date."""
    if series is None or series.empty:
        return markers
    by_date = {str(r["date"]): float(r["premium"]) for _, r in series.iterrows()}
    out = []
    for m in markers:
        row = dict(m)
        if row.get("premium") is None:
            px = by_date.get(str(row.get("date") or ""))
            if px is not None:
                row["premium"] = px
                row["premium_source"] = row.get("premium_source") or "合成ATR(当日)"
        out.append(row)
    return out


def hedge_pressure_blurb(
    series: pd.DataFrame,
    seat_net_change: float | None,
    *,
    lookback: int = 5,
) -> str:
    """One-line observe note; not a trade signal."""
    if series is None or series.empty or len(series) < 2:
        return "样本不足：本地无足够 CF 权利金序列。"
    tail = series.tail(max(2, lookback))
    first = float(tail["premium"].iloc[0])
    last = float(tail["premium"].iloc[-1])
    if first <= 0:
        return "样本不足：权利金基期无效。"
    chg_pct = (last / first - 1.0) * 100.0
    prem_dir = "抬升" if chg_pct > 1 else ("回落" if chg_pct < -1 else "大致持平")
    seat_txt = "席位净仓变化暂无"
    align = "—"
    if seat_net_change is not None:
        if seat_net_change > 0:
            seat_txt = f"机构净仓+{seat_net_change:,.0f}手"
        elif seat_net_change < 0:
            seat_txt = f"机构净仓{seat_net_change:,.0f}手"
        else:
            seat_txt = "机构净仓持平"
        # Crude alignment: premium up + net short shrink (net up) ≈ 符合保险需求；else 分歧
        if chg_pct > 1 and seat_net_change > 0:
            align = "符合（权利金抬升且净仓增加）"
        elif chg_pct > 1 and seat_net_change < 0:
            align = "分歧（权利金抬升但净仓下降）"
        elif chg_pct < -1 and seat_net_change < 0:
            align = "符合（权利金回落且净仓下降）"
        else:
            align = "中性/弱关联"
    listed = series.attrs.get("listed_compare") or {}
    listed_note = ""
    if listed.get("ok"):
        listed_note = (
            f"；链报价对照 {listed.get('option_symbol')} 权利金约 {listed.get('listed_premium'):.0f}元"
            if listed.get("listed_premium") is not None
            else f"；链腿 {listed.get('option_symbol')}"
        )
    elif listed.get("note"):
        listed_note = f"；链对照：{listed.get('note')}"
    return (
        f"近{len(tail)}日合成权利金{prem_dir} {chg_pct:+.1f}%（{first:.0f}→{last:.0f}元/手观察）· "
        f"{seat_txt} · 交叉：{align}{listed_note}。待验证旁证，非交易信号。"
    )


def premium_trade_fig(
    series: pd.DataFrame,
    markers: list[dict[str, Any]],
    *,
    title: str = "CF 权利金（合成）与建平仓标注",
) -> go.Figure:
    fig = go.Figure()
    if series is not None and not series.empty:
        fig.add_trace(
            go.Scatter(
                x=series["date"],
                y=series["premium"],
                mode="lines",
                name="合成权利金",
                line=dict(color="#1f6feb", width=2),
                hovertemplate="日期=%{x}<br>权利金=%{y:.2f}元<br>来源=合成ATR<extra></extra>",
            )
        )
    event_colors = {"建仓": "#14804a", "平仓": "#d1242f", "持仓中": "#9a6700"}
    for event, color in event_colors.items():
        pts = [m for m in markers if m.get("event") == event and m.get("date")]
        if not pts:
            continue
        fig.add_trace(
            go.Scatter(
                x=[m["date"] for m in pts],
                y=[m.get("premium") if m.get("premium") is not None else None for m in pts],
                mode="markers",
                name=event,
                marker=dict(size=11, color=color, symbol="diamond"),
                text=[
                    f"{m['date']} | {m.get('label') or m.get('code','CF')} | {m['event']}<br>"
                    f"条件：{m.get('condition')}<br>"
                    f"权利金：{m.get('premium')}（{m.get('premium_source') or '—'}）"
                    for m in pts
                ],
                hovertemplate="%{text}<extra></extra>",
            )
        )
    fig.update_layout(
        title=title,
        height=360,
        margin=dict(l=40, r=20, t=48, b=40),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(title="日期", gridcolor="#e6e6e6"),
        yaxis=dict(title="权利金（元，1手观察）", gridcolor="#e6e6e6"),
    )
    if series is None or series.empty:
        fig.add_annotation(text="样本不足：无本地 CF 连续合约或 ATR", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
    return fig
