# -*- coding: utf-8 -*-
"""Seat and sector board for the research desk.

Position series come from local member files in ``.cache/member``:
SHFE/CZCE ``*.txt`` and DCE ``dce-YYYYMMDD.json`` (akshare, soft-fail on WAF).
They are the project's three seat lists (机构 / 外资 / 家人), not Tonghuashun's
机构/私募/产业大户/中户/散户 classes. Sector strength is the mean r20/r60 already
stored on l1_report signals. Strategy PnL is read from each strategy JSON and
is portfolio-level.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.loaders import (  # noqa: E402
    format_variety_label,
    load_json,
    load_strategy_payload,
    load_universe,
    strategy_availability,
    strategy_kpis,
    variety_select_labels,
)
from desk.strategies.registry import all_strategies  # noqa: E402
from member_rank import (  # noqa: E402
    clean_member_name,
    ensure_public_member_day,
    fetch_dce_member_day,
    seat_kind,
)

GREEN = "#14804a"
RED = "#d1242f"
INK = "#222222"
GRID = "#e6e6e6"
PAPER = "#ffffff"

GROUPS = (
    ("inst", "机构席位"),
    ("foreign", "外资席位"),
    ("holder", "家人席位"),
)
KIND_ZH = {"inst": "机构", "foreign": "外资", "holder": "家人"}
EX_ZH = {"CZCE": "郑商所", "SHFE": "上期所", "DCE": "大商所"}
BUCKET_ORDER = ["能化", "黑色", "有色", "农产品"]
WINDOWS = (("6日", 6), ("12日", 12), ("70日", 70), ("全部", 0))
STRATEGY_IDS = (
    "path_a",
    "benchmark",
    "path_a_opt_hedge",
    "param_sweep",
    "proxy_cwft",
    "proxy_frontnext_st",
    "proxy_long_short_cwft",
    # 东证周报 KPI：不能稳定自动获取 → external/archive，不进研究台。
)
_CZCE_RE = re.compile(
    r"(PTA|AP|CF|CJ|CY|FG|MA|OI|PF|PK|PL|PR|PX|RM|RS|SA|SF|SH|SM|SR|UR|TA)"
)
_SEAT_POINTS = {
    "跟随机构": 25.0,
    "跟随外资": 15.0,
    "家人对立": 10.0,
    "机构席位反向": -25.0,
    "外资席位反向": -15.0,
    "与家人同向": -10.0,
}
SCORE_FORMULA = (
    "score = clip(动量 + 席位 + 入选, -100, 100)，正分偏多，负分偏空。"
    "动量 = clip(r20/10, -1, 1)×30 + clip(r60/15, -1, 1)×20 + 同向加成。"
    "同向加成仅在 r20 与 r60 同号且 |r20|≥3 且 |r60|≥5 时取 sign(r20)×10，否则为 0；"
    "缺 r20 或 r60 时对应项按 0。门槛是 universe.json 的 min_r20_pct / min_r60_pct。"
    "席位 = 标签分 × 方向符号（多=+1，空=-1，其他=0）。"
    "标签分：跟随机构 +25，跟随外资 +15，家人对立 +10，机构席位反向 -25，"
    "外资席位反向 -15，与家人同向 -10，其余 0。"
    "家人对立沿用 seat_decision：与家人名单反向视为确认当前方向，与家人同向扣分。"
    "入选：selected 且 lots_l1>0 为 15×方向符号；否则 lots_l1>0 为 8×方向符号；否则 0。"
)
CHOP_DISAGREE = 40.0
CHOP_INSIDE = 40.0
CHOP_ATR = 20.0
ATR_CHOP_RATIO = 0.03
REGIME_FORMULA = (
    "三桶分沿用上面的 signed 评分（-100 到 +100），不另起一套动量公式。"
    "多原料 = max(signed, 0)，空原料 = max(-signed, 0)。"
    "震荡原料只加这三项：r20 与 r60 都有且异号 +40；"
    "两者都落在门槛内（|r20|<min_r20 且 |r60|<min_r60，默认 3% 与 5%）+40；"
    "atr 与 close 都有且 atr/close>=3% +20。缺字段则该项为 0。"
    "三份原料都是 0 时，震荡=100。否则按原料比例分成 100，精确到 0.1，余数补给占比最大的一桶。"
    "字段只用 r20、r60、atr、close、direction、席位标签、selected、lots_l1。不计算盈亏。"
)
MAPPING_NOTE = (
    "左图是本地会员排名里三组席位的净持仓（前20名，多单减空单，单位：手），"
    "不是同花顺的五类账户。机构 = 中信期货、国泰君安、华泰、永安、东证；"
    "外资 = 摩根大通、摩根士丹利、瑞银、高盛；"
    "家人 = 东方财富、平安、方正中期、徽商、中信建投。"
    "私募、产业大户、中户没有本地序列，本页不画这三条。"
    "郑商所用品种汇总表；上期所用持买仓合计最大的合约；"
    "席位统一走东财→新浪补缺（em/dce 缓存）；交易所 txt 仅作辅。"
)


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


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _lots(value: Any) -> int | float | None:
    num = _num(value)
    if num is None:
        return None
    if abs(num - round(num)) < 1e-9:
        return int(round(num))
    return num


def _dir_sign(direction: Any) -> int:
    if direction == "多":
        return 1
    if direction == "空":
        return -1
    return 0


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _round1(value: float) -> float:
    out = round(float(value), 1)
    return 0.0 if out == 0 else out


def exchange_of(ticker: str) -> str:
    up = str(ticker or "").upper()
    if up.endswith(".CZC"):
        return "CZCE"
    if up.endswith(".SHF") or up.endswith(".SHFE"):
        return "SHFE"
    return "DCE"


def universe_rows(root: Path) -> list[dict[str, str]]:
    uni = load_universe(root) or {}
    rows = []
    for sym in uni.get("symbols") or []:
        code = str(sym.get("code") or "").upper()
        if not code:
            continue
        rows.append(
            {
                "code": code,
                "name": str(sym.get("name") or code),
                "bucket": str(sym.get("bucket") or ""),
                "exchange": exchange_of(str(sym.get("ticker") or "")),
            }
        )
    return rows


def member_dates(root: Path, exchange: str) -> list[str]:
    folder = root / ".cache" / "member"
    if not folder.is_dir():
        return []
    if exchange == "DCE":
        paths = list(folder.glob("dce-*.json"))
    else:
        prefix = {"CZCE": "czce", "SHFE": "shfe"}.get(exchange)
        if not prefix:
            return []
        paths = list(folder.glob(f"{prefix}-*.txt"))
    out = []
    for path in paths:
        ymd = path.stem.split("-", 1)[-1]
        if len(ymd) == 8 and ymd.isdigit():
            out.append(ymd)
    return sorted(out)


def ensure_dce_latest(root: Path, *, try_n: int = 5) -> str | None:
    """If DCE cache is empty/stale, pull recent sessions using SHFE/CZCE dates.

    Daily ``load_member_seats`` used to read ``dce-*.json`` only and never
    call akshare; the desk then showed 机构净持仓缺失 for all DCE symbols.
    Tries newest shared calendar days first; returns the ymd that landed.
    """
    have = member_dates(root, "DCE")
    if have:
        return have[-1]
    calendar = sorted(
        set(member_dates(root, "SHFE")) | set(member_dates(root, "CZCE")),
        reverse=True,
    )
    if not calendar:
        return None
    for ymd in calendar[: max(1, int(try_n))]:
        got = fetch_dce_member_day(ymd, force=False)
        if got and got.get("products"):
            try:
                cached_snapshot.clear()
            except Exception:
                pass
            return ymd
    return None


def trading_day_options(root: Path, exchange: str) -> list[str]:
    """YYYYMMDD values for the 交易日 selectbox, newest first.

    ``member_dates`` stays oldest-first. ``load_group_frame`` walks that
    chronological order and takes a tail, so the chart series is unchanged.
    For DCE, calendar days also include SHFE/CZCE cache dates so the desk can
    pick a session and attempt an akshare pull when ``dce-*.json`` is missing.
    """
    if exchange == "DCE":
        raw = (
            set(member_dates(root, "DCE"))
            | set(member_dates(root, "CZCE"))
            | set(member_dates(root, "SHFE"))
        )
    else:
        raw = set(member_dates(root, exchange))
    return sorted(raw, reverse=True)


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for enc in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _empty_groups() -> dict[str, dict[str, float]]:
    return {key: {"long": 0.0, "short": 0.0, "net": 0.0} for key, _label in GROUPS}


def _pack(contract: str, longs: list[tuple[str, float]], shorts: list[tuple[str, float]], n: int) -> dict:
    groups = _empty_groups()
    for name, qty in longs:
        kind = seat_kind(name)
        if kind in groups:
            groups[kind]["long"] += qty
    for name, qty in shorts:
        kind = seat_kind(name)
        if kind in groups:
            groups[kind]["short"] += qty
    for book in groups.values():
        book["net"] = book["long"] - book["short"]

    acc: dict[str, dict[str, float]] = {}
    for name, qty in longs:
        slot = acc.setdefault(name, {"long": 0.0, "short": 0.0})
        slot["long"] += qty
    for name, qty in shorts:
        slot = acc.setdefault(name, {"long": 0.0, "short": 0.0})
        slot["short"] += qty
    nets = []
    for name, slot in acc.items():
        if not name:
            continue
        kind = seat_kind(name) or ""
        nets.append(
            {
                "name": name,
                "net": slot["long"] - slot["short"],
                "kind": kind,
            }
        )
    nets.sort(key=lambda row: row["net"], reverse=True)

    def _side(rows: list[tuple[str, float]]) -> list[dict]:
        out = []
        for name, qty in rows:
            out.append({"name": name, "qty": qty, "kind": seat_kind(name) or ""})
        return out

    snap: dict[str, Any] = {
        "ok": True,
        "contract": contract,
        "n": n,
        "longs": _side(longs),
        "shorts": _side(shorts),
        "nets": nets[:20],
    }
    for key, _label in GROUPS:
        snap[f"{key}_long"] = groups[key]["long"]
        snap[f"{key}_short"] = groups[key]["short"]
        snap[f"{key}_net"] = groups[key]["net"]
    return snap


def _czce_snapshot(text: str, code: str) -> dict | None:
    want = code.upper()
    for part in re.split(r"品种[：:]", text)[1:]:
        part = part.split("合约")[0]
        matched = _CZCE_RE.search(part[:40])
        if not matched:
            continue
        found = "TA" if matched.group(1) == "PTA" else matched.group(1)
        if found != want:
            continue
        longs: list[tuple[str, float]] = []
        shorts: list[tuple[str, float]] = []
        n = 0
        for line in part.splitlines():
            if "|" not in line:
                continue
            cells = [cell.strip() for cell in line.split("|")]
            if not cells or not cells[0].isdigit():
                continue
            rank = int(cells[0])
            if not 1 <= rank <= 20 or len(cells) < 9:
                continue
            long_qty = _num(cells[5]) if len(cells) > 5 else None
            short_qty = _num(cells[8]) if len(cells) > 8 else None
            if long_qty is None or short_qty is None:
                continue
            n += 1
            long_name = clean_member_name(cells[4] if len(cells) > 4 else "")
            short_name = clean_member_name(cells[7] if len(cells) > 7 else "")
            if long_name:
                longs.append((long_name, long_qty))
            if short_name:
                shorts.append((short_name, short_qty))
        if n < 15:
            return None
        return _pack(want, longs, shorts, n)
    return None


def _shfe_snapshot(payload: dict, code: str) -> dict | None:
    want = code.upper()
    by_inst: dict[str, list] = {}
    for row in payload.get("o_cursor") or []:
        iid = str(row.get("INSTRUMENTID") or "")
        if not iid or iid.lower().endswith("all"):
            continue
        prefix = "".join(ch for ch in iid if ch.isalpha()).upper()
        if prefix != want:
            continue
        by_inst.setdefault(iid, []).append(row)
    best = None
    best_oi = -1.0
    best_id = ""
    for iid, rows in by_inst.items():
        ranked = []
        total = 0.0
        for row in rows:
            try:
                rank = int(row.get("RANK") or 0)
            except (TypeError, ValueError):
                continue
            if rank == 999:
                total = float(row.get("CJ2") or 0)
            elif 1 <= rank <= 20:
                ranked.append(row)
        if total <= 0 and ranked:
            total = sum(float(r.get("CJ2") or 0) for r in ranked)
        if len(ranked) >= 15 and total > best_oi:
            best_oi = total
            best = ranked
            best_id = iid
    if not best:
        return None
    longs = []
    shorts = []
    for row in best:
        long_name = clean_member_name(str(row.get("PARTICIPANTABBR2") or ""))
        short_name = clean_member_name(str(row.get("PARTICIPANTABBR3") or ""))
        long_qty = _num(row.get("CJ2"))
        short_qty = _num(row.get("CJ3"))
        if long_name and long_qty is not None:
            longs.append((long_name, long_qty))
        if short_name and short_qty is not None:
            shorts.append((short_name, short_qty))
    return _pack(best_id.upper(), longs, shorts, len(best))


def _dce_snapshot(payload: dict, code: str) -> dict | None:
    want = code.upper()
    row = (payload.get("products") or {}).get(want)
    if not isinstance(row, dict):
        return None
    n = int(row.get("n") or 0)
    if n < 15:
        return None
    longs: list[tuple[str, float]] = []
    shorts: list[tuple[str, float]] = []
    for item in row.get("longs") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        name = clean_member_name(str(item[0]))
        qty = _num(item[1])
        if name and qty is not None:
            longs.append((name, qty))
    for item in row.get("shorts") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        name = clean_member_name(str(item[0]))
        qty = _num(item[1])
        if name and qty is not None:
            shorts.append((name, qty))
    if len(longs) < 10 and len(shorts) < 10:
        return None
    contract = str(row.get("contract") or want).upper()
    return _pack(contract, longs, shorts, n)


def _em_product_snapshot(root: Path, code: str, ymd: str) -> dict | None:
    """Eastmoney/Sina underlay written by member_rank.ensure_universe_member_coverage."""
    path = root / ".cache" / "member" / f"em-{ymd}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _dce_snapshot(payload, code)


def _snapshot_uncached(root: Path, code: str, exchange: str, ymd: str) -> dict:
    snap = None
    if exchange == "DCE":
        path = root / ".cache" / "member" / f"dce-{ymd}.json"
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                payload = None
            if isinstance(payload, dict):
                snap = _dce_snapshot(payload, code)
    else:
        prefix = {"CZCE": "czce", "SHFE": "shfe"}.get(exchange)
        if not prefix:
            return {"ok": False}
        path = root / ".cache" / "member" / f"{prefix}-{ymd}.txt"
        if path.is_file():
            if exchange == "CZCE":
                text = _read_text(path)
                if text:
                    snap = _czce_snapshot(text, code)
            else:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    snap = _shfe_snapshot(payload, code)
    if not snap:
        snap = _em_product_snapshot(root, code, ymd)
    if not snap:
        return {"ok": False}
    snap["date"] = _iso(ymd)
    snap["ymd"] = ymd
    return snap


@st.cache_data(show_spinner=False)
def cached_snapshot(root_s: str, code: str, exchange: str, ymd: str) -> dict:
    return _snapshot_uncached(Path(root_s), code, exchange, ymd)


def _em_dates(root: Path) -> list[str]:
    folder = root / ".cache" / "member"
    if not folder.is_dir():
        return []
    out = []
    for path in folder.glob("em-*.json"):
        ymd = path.stem.split("-", 1)[-1]
        if len(ymd) == 8 and ymd.isdigit():
            out.append(ymd)
    return out


def load_group_frame(root: Path, code: str, exchange: str, end_ymd: str, n_back: int) -> pd.DataFrame:
    """Build net-position series for the chart.

    DCE previously only walked ``dce-*.json`` dates (often 2–3 days). Use the
    denser SHFE/CZCE/EM calendar so Eastmoney underlay fills the gaps.
    """
    if exchange == "DCE":
        dates = sorted(
            set(member_dates(root, "DCE"))
            | set(member_dates(root, "SHFE"))
            | set(member_dates(root, "CZCE"))
            | set(_em_dates(root))
        )
        dates = [d for d in dates if d <= end_ymd]
    else:
        dates = [d for d in member_dates(root, exchange) if d <= end_ymd]
    if n_back > 0:
        dates = dates[-n_back:]
    rows = []
    root_s = str(root)
    for ymd in dates:
        snap = cached_snapshot(root_s, code, exchange, ymd)
        if not snap.get("ok"):
            continue
        rows.append(
            {
                "date": snap["date"],
                "contract": snap.get("contract") or code,
                **{f"{key}_{leg}": snap.get(f"{key}_{leg}") for key, _label in GROUPS for leg in ("long", "short", "net")},
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def session_delta(series: pd.Series, sessions: int) -> float | None:
    if series is None or len(series) <= sessions:
        return None
    latest = _num(series.iloc[-1])
    prev = _num(series.iloc[-1 - sessions])
    if latest is None or prev is None:
        return None
    return latest - prev


def _light(
    fig: go.Figure,
    title: str,
    height: int,
    *,
    cartesian: bool = True,
    time_axis: bool | str = False,
) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK)),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        font=dict(color=INK, size=12, family="Microsoft YaHei, SimHei, sans-serif"),
        height=height,
        margin=dict(l=52, r=18, t=46, b=36),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK)),
        hovermode="x unified",
    )
    if cartesian:
        fig.update_xaxes(gridcolor=GRID, linecolor="#cccccc", zerolinecolor="#cccccc", tickfont=dict(color=INK))
        fig.update_yaxes(gridcolor=GRID, linecolor="#cccccc", zerolinecolor="#cccccc", tickfont=dict(color=INK))
    # Desk charts use chronological x: 左远右近 (old left, recent right).
    # "recent_left" kept as alias but no longer reverses the axis.
    if time_axis in (True, "recent_right", "recent_left"):
        fig.update_xaxes(autorange=True, title_text="日期（左远右近）")
    return fig


def net_position_fig(view: pd.DataFrame, key: str, title: str) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if view is None or view.empty or f"{key}_net" not in view.columns:
        fig.update_layout(annotations=[dict(text="无本地序列", showarrow=False, font=dict(color=INK))])
        return _light(fig, title, 250)
    # 保证横轴从远到近（左远右近）
    view = view.sort_values("date").reset_index(drop=True)
    y = view[f"{key}_net"].astype(float)
    chg = y.diff()
    colors = [GREEN if (v or 0) >= 0 else RED for v in chg.fillna(0)]
    fig.add_trace(
        go.Bar(x=view["date"], y=chg, name="日变动", marker_color=colors, opacity=0.85),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=view["date"],
            y=y,
            name="净持仓",
            mode="lines+markers",
            line=dict(color="#333333", width=2),
            marker=dict(size=5, color="#333333"),
        ),
        secondary_y=True,
    )
    fig.update_yaxes(title_text="日变动(手)", secondary_y=False, showgrid=False, tickfont=dict(color=INK))
    fig.update_yaxes(title_text="净持仓(手)", secondary_y=True, tickfont=dict(color=INK))
    return _light(fig, title, 250, time_axis="recent_right")


def long_short_fig(snap: dict) -> go.Figure:
    labels = [label for _key, label in GROUPS]
    longs = [snap.get(f"{key}_long") or 0 for key, _label in GROUPS]
    shorts = [snap.get(f"{key}_short") or 0 for key, _label in GROUPS]
    fig = go.Figure()
    fig.add_bar(name="多单", x=labels, y=longs, marker_color=GREEN)
    fig.add_bar(name="空单", x=labels, y=shorts, marker_color=RED)
    fig.update_layout(barmode="group", yaxis_title="手")
    return _light(fig, "多空分类账户持仓", 280)


def net_group_fig(snap: dict) -> go.Figure:
    labels = [label for _key, label in GROUPS]
    nets = [snap.get(f"{key}_net") or 0 for key, _label in GROUPS]
    colors = [GREEN if v >= 0 else RED for v in nets]
    fig = go.Figure(go.Bar(x=labels, y=nets, marker_color=colors, name="净持仓"))
    fig.update_layout(yaxis_title="手")
    return _light(fig, "净多空分类账户统计", 260)


def score_bar_fig(scores: pd.DataFrame, selected: str) -> go.Figure:
    fig = go.Figure()
    if scores is None or scores.empty:
        fig.update_layout(annotations=[dict(text="无评分", showarrow=False, font=dict(color=INK))])
        return _light(fig, "多空评分", 320)
    ordered = scores.sort_values("评分", ascending=False)
    colors = [GREEN if v >= 0 else RED for v in ordered["评分"]]
    widths = [1.5 if code == selected else 0 for code in ordered["代码"]]
    fig.add_bar(
        x=ordered["代码"],
        y=ordered["评分"],
        marker_color=colors,
        marker_line_color="#222222",
        marker_line_width=widths,
        name="评分",
    )
    fig.add_hline(y=0, line_color="#bbbbbb", line_width=1)
    fig.update_layout(yaxis_title="评分", yaxis_range=[-100, 100])
    return _light(fig, "多空评分", 340)


def sector_radar_fig(frames: list[tuple[str, list[dict]]]) -> go.Figure:
    fig = go.Figure()
    colors = [GREEN, "#c2410c", "#6d28d9", "#b45309", "#0369a1"]
    buckets = list(BUCKET_ORDER)
    seen = set(buckets)
    for _asof, rows in frames:
        for row in rows:
            name = row["板块"]
            if name not in seen:
                buckets.append(name)
                seen.add(name)
    if not buckets or not frames:
        fig.update_layout(annotations=[dict(text="无板块收益", showarrow=False, font=dict(color=INK))])
        return _light(fig, "板块强弱", 420)
    for i, (asof, rows) in enumerate(frames):
        by_name = {row["板块"]: row.get("r20") for row in rows}
        vals = [by_name.get(name) for name in buckets]
        if not any(v is not None for v in vals):
            continue
        plot_vals = [0 if v is None else v for v in vals]
        fig.add_trace(
            go.Scatterpolar(
                r=plot_vals,
                theta=buckets,
                name=asof,
                fill="toself",
                opacity=0.85,
                line=dict(color=colors[i % len(colors)], width=2),
                marker=dict(size=5),
            )
        )
    fig.update_layout(
        polar=dict(
            bgcolor=PAPER,
            radialaxis=dict(gridcolor=GRID, linecolor="#cccccc", tickfont=dict(color=INK)),
            angularaxis=dict(gridcolor=GRID, linecolor="#cccccc", tickfont=dict(color=INK)),
        )
    )
    return _light(fig, "板块强弱", 460, cartesian=False)


def _bucket_rows(signals: list[dict]) -> list[dict]:
    acc: dict[str, dict[str, list]] = {}
    for sig in signals:
        bucket = str(sig.get("bucket") or "").strip()
        if not bucket:
            continue
        slot = acc.setdefault(bucket, {"r20": [], "r60": [], "n": 0})
        slot["n"] += 1
        r20 = _num(sig.get("r20"))
        r60 = _num(sig.get("r60"))
        if r20 is not None:
            slot["r20"].append(r20)
        if r60 is not None:
            slot["r60"].append(r60)
    rows = []
    for bucket, slot in acc.items():
        rows.append(
            {
                "板块": bucket,
                "r20": (sum(slot["r20"]) / len(slot["r20"])) if slot["r20"] else None,
                "r60": (sum(slot["r60"]) / len(slot["r60"])) if slot["r60"] else None,
                "n": int(slot["n"]),
            }
        )
    rows.sort(key=lambda row: (row["r20"] is None, -(row["r20"] or 0)))
    return rows


def sector_frames(root: Path, current: dict | None) -> list[tuple[str, list[dict]]]:
    found: dict[str, dict] = {}
    archive = root / "archive"
    if archive.is_dir():
        for path in sorted(archive.glob("l1_report_*.json")):
            data = load_json(path)
            if data and data.get("signals"):
                found[str(data.get("asof") or path.stem)] = data
    if current and current.get("signals"):
        found[str(current.get("asof") or "latest")] = current
    frames = []
    for asof in sorted(found, reverse=True):
        rows = _bucket_rows(found[asof].get("signals") or [])
        if rows:
            label = asof if "-" in asof else _iso(asof) if len(asof) == 8 and asof.isdigit() else asof
            frames.append((label, rows))
    return frames


def score_signals(signals: list[dict], *, r20_min: float = 3.0, r60_min: float = 5.0) -> list[dict]:
    """Long/short score in [-100, 100] from fields already on each signal."""
    rows = []
    for sig in signals:
        r20 = _num(sig.get("r20"))
        r60 = _num(sig.get("r60"))
        mom = 0.0
        if r20 is not None:
            mom += _clip(r20 / 10.0, -1.0, 1.0) * 30.0
        if r60 is not None:
            mom += _clip(r60 / 15.0, -1.0, 1.0) * 20.0
        align = 0.0
        align_note = "缺收益"
        if r20 is not None and r60 is not None:
            same = (r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0)
            if same and abs(r20) >= r20_min and abs(r60) >= r60_min:
                align = (1.0 if r20 > 0 else -1.0) * 10.0
                align_note = "同向过门槛"
            elif same:
                align_note = "同向未过门槛"
            else:
                align_note = "20/60不同向"
        mom += align
        sign = _dir_sign(sig.get("direction"))
        seat = str(sig.get("seat") or "").strip()
        seat_pts = _SEAT_POINTS.get(seat, 0.0) * sign
        lots = _num(sig.get("lots_l1")) or 0.0
        selected = bool(sig.get("selected"))
        if selected and lots > 0 and sign:
            sel = 15.0 * sign
            sel_note = f"已选{int(lots) if abs(lots - int(lots)) < 1e-9 else lots}手"
        elif lots > 0 and sign:
            sel = 8.0 * sign
            sel_note = "有手数未入选"
        else:
            sel = 0.0
            sel_note = "未入选"
        score = _round1(_clip(mom + seat_pts + sel, -100.0, 100.0))
        bits = []
        if r20 is not None:
            bits.append(f"r20 {r20:+.2f}")
        if r60 is not None:
            bits.append(f"r60 {r60:+.2f}")
        bits.append(align_note)
        bits.append(seat or "无席位标签")
        bits.append(sel_note)
        rows.append(
            {
                "代码": sig.get("code"),
                "名称": sig.get("name"),
                "板块": sig.get("bucket"),
                "方向": sig.get("direction") or "—",
                "r20": r20,
                "r60": r60,
                "席位": seat or "—",
                "手数": _lots(sig.get("lots_l1")),
                "已选": "是" if selected else "否",
                "动量": _round1(mom),
                "席位分": _round1(seat_pts),
                "入选分": _round1(sel),
                "评分": score,
                "理由": "，".join(bits),
            }
        )
    rows.sort(key=lambda row: row["评分"], reverse=True)
    return rows


def _alloc_tenths(weights: list[float]) -> list[float]:
    """Split 100 into tenths. Largest remainder goes to the biggest weight."""
    clean = [max(0.0, float(w)) for w in weights]
    total = sum(clean)
    if total <= 0:
        out = [0.0] * len(clean)
        if out:
            out[-1] = 100.0
        return out
    raw = [1000.0 * w / total for w in clean]
    floors = [int(math.floor(v + 1e-9)) for v in raw]
    left = 1000 - sum(floors)
    order = sorted(
        range(len(clean)),
        key=lambda i: (raw[i] - floors[i], clean[i]),
        reverse=True,
    )
    step = 0
    while left > 0 and order:
        floors[order[step % len(order)]] += 1
        left -= 1
        step += 1
    vals = [round(v / 10.0, 1) for v in floors]
    drift = round(100.0 - sum(vals), 1)
    if drift and vals:
        pick = max(range(len(vals)), key=lambda i: vals[i])
        vals[pick] = round(vals[pick] + drift, 1)
    return vals


def regime_bucket_scores(
    signals: list[dict],
    *,
    r20_min: float = 3.0,
    r60_min: float = 5.0,
) -> list[dict]:
    """Split the signed score into 多 / 空 / 震荡 that sum to 100.

    The signed piece is ``score_signals``. Chop points use only r20, r60,
    atr and close. See ``REGIME_FORMULA``.
    """
    scored = score_signals(signals, r20_min=r20_min, r60_min=r60_min)
    by_code: dict[str, list[dict]] = defaultdict(list)
    for sig in signals:
        by_code[str(sig.get("code") or "")].append(sig)
    used: dict[str, int] = defaultdict(int)
    rows = []
    for row in scored:
        code = str(row.get("代码") or "")
        idx = used[code]
        used[code] += 1
        group = by_code.get(code) or []
        sig = group[idx] if idx < len(group) else {}
        r20 = row.get("r20")
        r60 = row.get("r60")
        chop = 0.0
        notes = []
        if r20 is not None and r60 is not None:
            disagree = (r20 > 0 > r60) or (r20 < 0 < r60)
            if disagree:
                chop += CHOP_DISAGREE
                notes.append("r20与r60异号")
            if abs(r20) < r20_min and abs(r60) < r60_min:
                chop += CHOP_INSIDE
                notes.append("r20与r60都在门槛内")
        atr = _num(sig.get("atr"))
        close = _num(sig.get("close"))
        if atr is not None and close is not None and close > 0 and atr / close >= ATR_CHOP_RATIO:
            chop += CHOP_ATR
            notes.append(f"atr/close {atr / close * 100:.1f}%")
        signed = float(row["评分"])
        long_raw = max(signed, 0.0)
        short_raw = max(-signed, 0.0)
        long_s, short_s, chop_s = _alloc_tenths([long_raw, short_raw, chop])
        out = dict(row)
        out["多"] = long_s
        out["空"] = short_s
        out["震荡"] = chop_s
        out["原评分"] = signed
        out["震荡依据"] = "，".join(notes) if notes else "无震荡加分"
        rows.append(out)
    return rows


def _signal_map(report: dict | None) -> dict[str, dict]:
    out = {}
    for sig in (report or {}).get("signals") or []:
        code = str(sig.get("code") or "").upper()
        if code:
            out[code] = sig
    return out


def strategy_board_rows(root: Path, code: str, report: dict | None) -> list[dict]:
    """Portfolio KPIs plus a symbol stance when that JSON actually has the code."""
    specs = {spec.id: spec for spec in all_strategies(root)}
    signals = _signal_map(report)
    rows = []
    for sid in STRATEGY_IDS:
        spec = specs.get(sid)
        if spec is None:
            continue
        avail = strategy_availability(spec, root)
        if sid == "wyckoff":
            if avail != "ready":
                continue
        elif avail not in ("ready", "kpi_only"):
            continue
        payload = load_strategy_payload(spec, root) or {}
        if payload.get("_desk_missing"):
            continue
        kpis = strategy_kpis(spec, root)
        ret = _num(kpis.get("ret_pct"))
        dd = _num(kpis.get("max_dd_pct"))
        source = str(kpis.get("source") or "")
        positions = payload.get("final_positions") if isinstance(payload.get("final_positions"), dict) else {}
        if sid == "path_a" and code in signals:
            sig = signals[code]
            rows.append(
                {
                    "策略": spec.name,
                    "口径": "日信号",
                    "方向": sig.get("direction") or "—",
                    "席位": sig.get("seat") or "—",
                    "手数": _lots(sig.get("lots_l1")),
                    "r20": _num(sig.get("r20")),
                    "r60": _num(sig.get("r60")),
                    "组合收益%": ret,
                    "组合回撤%": dd,
                    "来源": "l1_report.json / " + source,
                }
            )
        pos = positions.get(code) if isinstance(positions, dict) else None
        if isinstance(pos, dict):
            rows.append(
                {
                    "策略": spec.name,
                    "口径": "回测期末",
                    "方向": pos.get("direction") or "—",
                    "席位": "—",
                    "手数": _lots(pos.get("lots")),
                    "r20": _num(pos.get("r20")),
                    "r60": _num(pos.get("r60")),
                    "组合收益%": ret,
                    "组合回撤%": dd,
                    "来源": source or "—",
                }
            )
        elif sid != "path_a" or code not in signals:
            stance = "未记录期末持仓" if sid == "benchmark" else "无该品种期末持仓"
            if sid == "path_a" and not positions:
                stance = "无期末持仓记录"
            rows.append(
                {
                    "策略": spec.name,
                    "口径": "组合" if sid == "benchmark" else "回测期末",
                    "方向": stance,
                    "席位": "—",
                    "手数": None,
                    "r20": None,
                    "r60": None,
                    "组合收益%": ret,
                    "组合回撤%": dd,
                    "来源": source or "—",
                }
            )
        elif sid == "path_a" and code not in (positions or {}):
            rows.append(
                {
                    "策略": spec.name,
                    "口径": "回测期末",
                    "方向": "无该品种期末持仓",
                    "席位": "—",
                    "手数": None,
                    "r20": None,
                    "r60": None,
                    "组合收益%": ret,
                    "组合回撤%": dd,
                    "来源": source or "—",
                }
            )
    return rows


def _fmt_lots(value: Any) -> str:
    num = _num(value)
    if num is None:
        return "—"
    return f"{num:,.0f}"


def _fmt_chg(value: Any) -> str:
    num = _num(value)
    if num is None:
        return "—"
    return f"{num:+,.0f}"


def _change_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, label in GROUPS:
        col = f"{key}_net"
        row: dict[str, Any] = {"分类": label}
        series = frame[col] if col in frame.columns else pd.Series(dtype=float)
        for sessions in (1, 3, 5, 10):
            row[f"{sessions}日"] = session_delta(series, sessions)
        rows.append(row)
    return pd.DataFrame(rows)


def _rank_table(snap: dict) -> pd.DataFrame:
    longs = snap.get("longs") or []
    shorts = snap.get("shorts") or []
    nets = snap.get("nets") or []
    n = max(len(longs), len(shorts), len(nets), 0)
    rows = []
    for i in range(min(n, 20)):
        long_row = longs[i] if i < len(longs) else {}
        short_row = shorts[i] if i < len(shorts) else {}
        net_row = nets[i] if i < len(nets) else {}
        rows.append(
            {
                "名次": i + 1,
                "买入/多单": long_row.get("name") or "—",
                "多单(手)": long_row.get("qty"),
                "多单分组": KIND_ZH.get(long_row.get("kind") or "", "—"),
                "卖出/空单": short_row.get("name") or "—",
                "空单(手)": short_row.get("qty"),
                "空单分组": KIND_ZH.get(short_row.get("kind") or "", "—"),
                "净持仓席位": net_row.get("name") or "—",
                "净持仓(手)": net_row.get("net"),
                "净持仓分组": KIND_ZH.get(net_row.get("kind") or "", "—"),
            }
        )
    return pd.DataFrame(rows)


def _highlight_code(row: pd.Series, code: str) -> list[str]:
    if str(row.get("代码") or "") == code:
        return ["background-color: #eef6ee"] * len(row)
    return [""] * len(row)


def render_seat_sector(root: Path) -> None:
    st.subheader("席位与板块")
    st.caption("浅色底。只读本地排名、日报和回测 JSON，不下单。")
    st.caption(MAPPING_NOTE)

    symbols = universe_rows(root)
    if not symbols:
        st.error("universe.json 没有品种")
        return
    labels = variety_select_labels(root, symbols, ex_zh=EX_ZH)
    report = load_json(root / "l1_report.json")
    selected_codes = [
        str(sig.get("code") or "").upper()
        for sig in (report or {}).get("signals") or []
        if sig.get("selected")
    ]
    default_code = selected_codes[0] if selected_codes else symbols[0]["code"]
    default_label = next((lab for lab, row in zip(labels, symbols) if row["code"] == default_code), labels[0])
    if "seat_sym" not in st.session_state:
        st.session_state["seat_sym"] = default_label
    if st.session_state["seat_sym"] not in labels:
        st.session_state["seat_sym"] = default_label

    def _push_chart_sym() -> None:
        st.session_state["chart_sym"] = st.session_state.get("seat_sym")

    c_day, c_sym, c_win, c_btn = st.columns([1.15, 1.7, 0.9, 0.55])
    with c_sym:
        choice = st.selectbox("品种", labels, key="seat_sym", on_change=_push_chart_sym)
    meta = symbols[labels.index(choice)]
    code = meta["code"]
    exchange = meta["exchange"]
    # This object is the selectbox options. Newest day is index 0.
    day_options = trading_day_options(root, exchange)
    with c_day:
        if not day_options:
            st.selectbox("交易日", ["无本地排名"], disabled=True)
            end_ymd = ""
        else:
            if st.session_state.get("seat_day") not in day_options:
                st.session_state["seat_day"] = day_options[0]
            end_ymd = st.selectbox(
                "交易日",
                day_options,
                key="seat_day",
                format_func=_iso,
            )
    with c_win:
        if "seat_win" not in st.session_state:
            st.session_state["seat_win"] = "70日"
        win_label = st.selectbox("窗口", [name for name, _n in WINDOWS], key="seat_win")
    win_n = dict(WINDOWS)[win_label]
    with c_btn:
        st.caption("")
        if st.button("刷新", key="seat_refresh"):
            if end_ymd:
                with st.spinner("东财→新浪补席位…"):
                    ensure_public_member_day(end_ymd, force_em=True)
            cached_snapshot.clear()
            st.rerun()

    st.caption(
        f"当前 {format_variety_label(code, meta.get('name') or '', root=root, exchange_zh=EX_ZH.get(exchange, exchange))} · "
        f"交易日 {_iso(end_ymd) if end_ymd else '—'} · 窗口 {win_label}"
    )

    if not end_ymd:
        st.info("没有找到 .cache/member 下的会员排名文件。")
        frame = pd.DataFrame()
        snap = {"ok": False}
    else:
        em_path = root / ".cache" / "member" / f"em-{end_ymd}.json"
        dce_path = root / ".cache" / "member" / f"dce-{end_ymd}.json"
        if exchange == "DCE" and not dce_path.is_file() and not em_path.is_file():
            with st.spinner("东财→新浪补大商所席位…"):
                got = ensure_public_member_day(end_ymd, force_em=False)
            if not got.get("ok") and not dce_path.is_file() and not em_path.is_file():
                st.info(
                    "东财/新浪暂无该日席位。点「刷新」重试；"
                    "或等 GitHub 日报/周跑落库后 git pull。"
                    "板块与多空评分仍可用日报 JSON。"
                )
            else:
                st.caption("大商所持仓：东财→新浪统一缓存（em/dce）。")
        elif exchange == "DCE":
            st.caption("大商所持仓：东财→新浪统一缓存（em/dce）。")
        lookback = win_n if win_n == 0 else max(win_n, 11)
        with st.spinner("读取本地会员排名…"):
            frame = load_group_frame(root, code, exchange, end_ymd, lookback)
            snap = cached_snapshot(str(root), code, exchange, end_ymd)
        if frame.empty or not snap.get("ok"):
            st.info(
                f"{_iso(end_ymd)} 的{EX_ZH.get(exchange, exchange)}排名里没有 {code}，"
                "或排名不足 15 名。"
            )

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("**分类持仓**")
        if frame.empty:
            st.caption("没有可画的席位时间序列。")
        else:
            view_n = win_n if win_n else len(frame)
            view = frame.tail(view_n).reset_index(drop=True)
            span = f"{view['date'].iloc[0]} → {view['date'].iloc[-1]}" if len(view) else ""
            if len(view) < 2:
                st.caption(f"席位序列只有 {len(view)} 个交易日，按单日快照理解。{span}")
            else:
                st.caption(
                    f"本地排名 {len(view)} 个交易日（{span}）。"
                    "柱是相邻排名日的净持仓差，线是净持仓。没有这三组的 OHLC，所以不用 K 线。"
                )
            for key, label in GROUPS:
                chg = session_delta(frame[f"{key}_net"], 1) if f"{key}_net" in frame.columns else None
                last = frame[f"{key}_net"].iloc[-1] if f"{key}_net" in frame.columns and len(frame) else None
                st.plotly_chart(net_position_fig(view, key, label), width="stretch")
                contract = str(frame["contract"].iloc[-1]) if "contract" in frame.columns and len(frame) else code
                st.caption(f"{label} · {contract} · 持仓 {_fmt_lots(last)} 手 · 变动 {_fmt_chg(chg)} 手")
    with right:
        if snap.get("ok"):
            st.caption(f"当日合约/品种：{snap.get('contract')} · 排名行数 {snap.get('n')} · 单位：手")
            st.plotly_chart(long_short_fig(snap), width="stretch")
            st.plotly_chart(net_group_fig(snap), width="stretch")
            st.markdown("**席位龙虎榜**")
            st.caption("多单、空单、净持仓各自排序。同一行不是同一个会员。分组只标出项目名单内的席位。")
            rank_df = _rank_table(snap)
            if rank_df.empty:
                st.info("这一天没有前 20 名明细。")
            else:
                show = rank_df.copy()
                sty = show.style.map(
                    lambda v: (
                        f"color: {GREEN}; font-weight: 600"
                        if (_num(v) or 0) > 0
                        else f"color: {RED}; font-weight: 600"
                        if (_num(v) or 0) < 0
                        else ""
                    ),
                    subset=["净持仓(手)"],
                ).format({"多单(手)": "{:,.0f}", "空单(手)": "{:,.0f}", "净持仓(手)": "{:+,.0f}"}, na_rep="—")
                st.dataframe(sty, width="stretch", hide_index=True)
        else:
            st.caption("这一侧需要当日会员排名。")

    st.markdown("**持仓变化**")
    st.caption("1/3/5/10 日是向前数这么多个有排名文件的交易日，不是自然日。正数绿色，负数红色。单位：手。")
    if frame.empty:
        st.caption("没有历史净持仓，变化表留空。")
    else:
        changes = _change_table(frame)
        sty = changes.style.map(
            lambda v: (
                f"color: {GREEN}; font-weight: 600"
                if (_num(v) or 0) > 0
                else f"color: {RED}; font-weight: 600"
                if (_num(v) or 0) < 0
                else f"color: {INK}"
            ),
            subset=["1日", "3日", "5日", "10日"],
        ).format({col: "{:+,.0f}" for col in ("1日", "3日", "5日", "10日")}, na_rep="—")
        st.dataframe(sty, width="stretch", hide_index=True)
        if len(frame) <= 10:
            st.caption(f"当前读入 {len(frame)} 个交易日，不够 10 日的格子为空。")

    if code == "CF":
        from desk.cf_option_pressure import (  # noqa: WPS433
            attach_marker_premiums,
            hedge_pressure_blurb,
            load_cf_premium_series,
            load_cf_trade_markers,
            premium_trade_fig,
        )

        st.markdown("**CF 期权套保压力 · 权利金与建平仓**")
        st.caption(
            "棉花期权权利金为套保/保险需求旁证，与席位交叉验证；非独立交易信号。"
            "曲线默认合成 ATR 权利金（1 手观察）；有链缓存时在旁注对照。标注来自纸面回测/日报进出。"
        )
        lookback = win_n if win_n else 70
        with st.spinner("读取 CF 权利金与建平仓标注…"):
            prem_full = load_cf_premium_series(root, end_ymd=end_ymd or "", n_back=0)
            markers = attach_marker_premiums(prem_full, load_cf_trade_markers(root))
            if lookback and lookback > 0 and len(prem_full) > lookback:
                prem_df = prem_full.tail(lookback).reset_index(drop=True)
            else:
                prem_df = prem_full
            start_d = str(prem_df["date"].iloc[0]) if len(prem_df) else ""
            chart_markers = [
                m
                for m in markers
                if (not start_d or str(m.get("date") or "") >= start_d)
                and (not end_ymd or str(m.get("date") or "") <= _iso(end_ymd))
            ]
        seat_chg = None
        if not frame.empty and "inst_net" in frame.columns and len(frame) >= 2:
            seat_chg = session_delta(frame["inst_net"], 5 if len(frame) > 5 else 1)
        st.info(hedge_pressure_blurb(prem_df, seat_chg, lookback=min(5, max(2, len(prem_df)))))
        if prem_df.empty and not markers:
            st.caption("样本不足：本地无 CF0 日线或纸面 CF 事件。")
        else:
            st.plotly_chart(
                premium_trade_fig(prem_df, chart_markers, title="CF 权利金（合成）· 建平仓标注"),
                width="stretch",
            )
            if markers:
                show_m = pd.DataFrame(
                    [
                        {
                            "日期": m.get("date"),
                            "品种": m.get("label")
                            or format_variety_label(
                                str(m.get("code") or "CF"),
                                meta.get("name") or "棉花",
                                contract=m.get("contract"),
                                root=root,
                            ),
                            "事件": m.get("event"),
                            "方向": m.get("direction"),
                            "条件": m.get("condition"),
                            "权利金": m.get("premium"),
                            "来源": m.get("premium_source") or "—",
                            "R": m.get("R"),
                        }
                        for m in markers
                        if not end_ymd or str(m.get("date") or "") <= _iso(end_ymd)
                    ]
                )
                if not show_m.empty:
                    st.dataframe(show_m, width="stretch", hide_index=True)
            cmp_ = prem_df.attrs.get("listed_compare") if not prem_df.empty else None
            if isinstance(cmp_, dict) and cmp_.get("ok"):
                st.caption(
                    f"链对照：{cmp_.get('product')} {cmp_.get('month')} · "
                    f"{cmp_.get('option_symbol')} · 链权利金约 {cmp_.get('listed_premium')} · "
                    f"合成/链≈{cmp_.get('synth_over_listed')}"
                )
            elif isinstance(cmp_, dict) and cmp_.get("note"):
                st.caption(f"链对照软失败：{cmp_.get('note')}")

    st.markdown("**板块强弱**")
    st.caption(
        "板块是 universe.json 的 bucket。数字是 l1_report 信号 r20 / r60 的板块均值（%），"
        "不是同花顺全市场板块。雷达上每一条线是一个日报 asof；archive 里有几天就画几条。"
    )
    frames = sector_frames(root, report)
    if not frames:
        st.info("l1_report 里没有带 r20 的信号。")
    else:
        latest_label, latest_rows = frames[0]
        sec = pd.DataFrame(
            [
                {
                    "排名": i + 1,
                    "板块": row["板块"],
                    "r20均值%": None if row["r20"] is None else round(row["r20"], 2),
                    "r60均值%": None if row["r60"] is None else round(row["r60"], 2),
                    "品种数": row["n"],
                }
                for i, row in enumerate(latest_rows)
            ]
        )
        list_col, radar_col = st.columns([1, 1.15])
        with list_col:
            st.caption(f"列表用最新日报 {latest_label}")
            sec_sty = sec.style.map(
                lambda v: (
                    f"color: {GREEN}; font-weight: 600"
                    if (_num(v) or 0) > 0
                    else f"color: {RED}; font-weight: 600"
                    if (_num(v) or 0) < 0
                    else ""
                ),
                subset=["r20均值%", "r60均值%"],
            ).format({"r20均值%": "{:+.2f}", "r60均值%": "{:+.2f}"}, na_rep="—")
            st.dataframe(sec_sty, width="stretch", hide_index=True)
            if len(frames) == 1:
                st.caption("板块雷达目前只有一个日报截面。")
        with radar_col:
            st.plotly_chart(sector_radar_fig(frames), width="stretch")
        with st.expander("品种收益明细（最新日报）"):
            detail_rows = []
            for sig in (report or {}).get("signals") or []:
                detail_rows.append(
                    {
                        "代码": sig.get("code"),
                        "名称": sig.get("name"),
                        "板块": sig.get("bucket"),
                        "方向": sig.get("direction"),
                        "r20": _num(sig.get("r20")),
                        "r60": _num(sig.get("r60")),
                    }
                )
            detail = pd.DataFrame(detail_rows)
            if detail.empty:
                st.caption("无信号行")
            else:
                st.dataframe(
                    detail.style.format({"r20": "{:+.2f}", "r60": "{:+.2f}"}, na_rep="—"),
                    width="stretch",
                    hide_index=True,
                )

    st.markdown("**量化策略**")
    st.caption(
        "只列出已有产物的路径A、对照组合、路径A+保护期权；威科夫要有净值曲线才出现。"
        "组合收益%和组合回撤%来自各策略 JSON，是整个组合，不是这个品种单独的盈亏。"
        "品种方向：路径A日信号来自 l1_report；回测期末来自该文件的 final_positions。"
        "对照组合的 JSON 没有期末持仓明细。没有的字段留空，不估算品种收益。"
    )
    srows = strategy_board_rows(root, code, report)
    if not srows:
        st.info("这几个策略都没有可读的 JSON 产物。")
    else:
        sdf = pd.DataFrame(srows)
        num_cols = [col for col in ("r20", "r60", "组合收益%") if col in sdf.columns]
        sty = sdf.style.map(
            lambda v: (
                f"color: {GREEN}; font-weight: 600"
                if (_num(v) or 0) > 0
                else f"color: {RED}; font-weight: 600"
                if (_num(v) or 0) < 0
                else ""
            ),
            subset=num_cols,
        ).format({col: "{:+.3f}" if col != "组合收益%" else "{:+.3f}" for col in num_cols}, na_rep="—")
        st.dataframe(sty, width="stretch", hide_index=True)
        st.caption(f"上表对着品种 {code}。期末持仓里没有它时，方向写成无该品种期末持仓，收益仍是组合数。")

    st.markdown("**多空评分**")
    st.caption(SCORE_FORMULA)
    st.caption("同一套评分拆成多 / 空 / 震荡（三项和为 100）在「状态评分」页。")
    uni = load_universe(root) or {}
    r20_min = _num(uni.get("min_r20_pct")) or 3.0
    r60_min = _num(uni.get("min_r60_pct")) or 5.0
    signals = (report or {}).get("signals") or []
    if not signals:
        st.info("没有 l1_report 信号，评分为空。")
    else:
        scored = pd.DataFrame(score_signals(signals, r20_min=r20_min, r60_min=r60_min))
        if code in set(scored["代码"]):
            picked = scored.loc[scored["代码"] == code].iloc[0]
            m1, m2, m3 = st.columns(3)
            m1.metric(f"{code} 评分", f"{picked['评分']:+.1f}")
            m2.metric("方向", str(picked["方向"]))
            m3.metric("席位", str(picked["席位"]))
        st.plotly_chart(score_bar_fig(scored, code), width="stretch")
        sty = scored.style.apply(lambda row: _highlight_code(row, code), axis=1).map(
            lambda v: (
                f"color: {GREEN}; font-weight: 600"
                if (_num(v) or 0) > 0
                else f"color: {RED}; font-weight: 600"
                if (_num(v) or 0) < 0
                else ""
            ),
            subset=["评分", "动量", "席位分", "入选分", "r20", "r60"],
        ).format(
            {
                "r20": "{:+.2f}",
                "r60": "{:+.2f}",
                "动量": "{:+.1f}",
                "席位分": "{:+.1f}",
                "入选分": "{:+.1f}",
                "评分": "{:+.1f}",
            },
            na_rep="—",
        )
        st.dataframe(sty, width="stretch", hide_index=True)
        st.caption(f"{code} 行用浅绿底标出。大商所品种的席位标签是缺席位时，席位分按公式为 0。")

    st.caption("研究观察，不构成交易建议。")
