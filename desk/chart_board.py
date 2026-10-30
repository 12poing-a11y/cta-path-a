# -*- coding: utf-8 -*-
"""TradingView-style daily chart tab for the research desk.

Candlesticks + volume + MA/ATR from local sina continuous bars.
Path-A direction and regime/seat/basis events as markers. Read-only, no orders.
X-axis: distant left → recent right (TradingView default).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from desk.loaders import format_variety_label, load_json, variety_select_labels
from desk.regime_board import events_for_codes, load_local_bars
from desk.seat_board import EX_ZH, GREEN, INK, PAPER, RED, GRID, universe_rows

WINDOW_CHOICES = (("120 根", 120), ("250 根", 250), ("全部", 0))
PERIOD_CHOICES = (
    ("日线", "D"),
    ("周线", "W"),
    ("月线", "M"),
    # 60m first among intraday: more reactive than daily, smoother than 15m.
    ("60分钟", "60"),
    ("15分钟", "15"),
)
PERIOD_LABEL = {code: name for name, code in PERIOD_CHOICES}

EVENT_STYLE = {
    "动量跨越": {"symbol": "diamond", "color": "#2563eb", "size": 10},
    "席位翻向": {"symbol": "square", "color": "#7c3aed", "size": 9},
    "机构翻向": {"symbol": "square", "color": "#7c3aed", "size": 9},
    "动量机构同向": {"symbol": "star", "color": "#d97706", "size": 12},
    "基差极端": {"symbol": "x", "color": "#0891b2", "size": 10},
    "方向翻转": {"symbol": "triangle-up", "color": "#64748b", "size": 9},
    "席位切换": {"symbol": "hexagon", "color": "#a855f7", "size": 9},
    "入选变化": {"symbol": "circle-open", "color": "#0f766e", "size": 9},
}
_DEFAULT_EVENT = {"symbol": "circle", "color": "#94a3b8", "size": 8}


def _iso_ymd(ymd: str) -> str:
    text = str(ymd or "").replace("-", "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return str(ymd or "")[:10]


def _bars_frame(bars: list[dict]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    rows = []
    for bar in bars:
        close = bar.get("close")
        if close is None:
            continue
        high = bar.get("high")
        low = bar.get("low")
        if high is None:
            high = close
        if low is None:
            low = close
        open_ = bar.get("open")
        rows.append(
            {
                "date": str(bar.get("date") or "")[:10],
                "open": float(open_) if open_ is not None else None,
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(bar.get("volume") or 0),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    # Sina continuous bars often omit open; use prior close for the candle body.
    prev_close = df["close"].shift(1)
    opens = pd.to_numeric(df["open"], errors="coerce")
    df["open"] = opens.where(opens.notna() & (opens > 0), prev_close).fillna(df["close"]).astype(float)
    return df


def _resample_ohlcv(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Aggregate daily OHLCV to weekly (Fri) or month-end bars. ``D`` returns a copy."""
    if df.empty or period == "D":
        return df.copy()
    work = df.copy()
    work["dt"] = pd.to_datetime(work["date"])
    work = work.set_index("dt").sort_index()
    rule = "W-FRI" if period == "W" else "ME"
    agg = (
        work.resample(rule)
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["close"])
    )
    if agg.empty:
        return pd.DataFrame(columns=df.columns)
    out = agg.reset_index()
    out["date"] = out["dt"].dt.strftime("%Y-%m-%d")
    return out[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def _snap_to_period_date(day: str, period_dates: list[str], period: str) -> str | None:
    """Map a calendar day onto the period bar that contains it."""
    if not period_dates:
        return None
    day = _iso_ymd(day)
    if period == "D":
        return day if day in set(period_dates) else None
    target = pd.Timestamp(day)
    for bar_day in period_dates:
        if pd.Timestamp(bar_day) >= target:
            return bar_day
    return period_dates[-1]


def _indicator_frames(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        out["ma20"] = []
        out["ma60"] = []
        out["atr14"] = []
        return out
    out["ma20"] = out["close"].rolling(20, min_periods=20).mean()
    out["ma60"] = out["close"].rolling(60, min_periods=60).mean()
    prev = out["close"].shift(1)
    tr = pd.concat(
        [
            (out["high"] - out["low"]).abs(),
            (out["high"] - prev).abs(),
            (out["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.rolling(14, min_periods=14).mean()
    return out


def _path_a_markers(
    report: dict | None,
    code: str,
    df: pd.DataFrame,
    *,
    period: str = "D",
) -> dict[str, Any] | None:
    if report is None or df.empty:
        return None
    code = str(code or "").upper()
    sig = None
    for row in report.get("signals") or []:
        if str(row.get("code") or "").upper() == code:
            sig = row
            break
    if sig is None:
        return None
    asof = _iso_ymd(str(report.get("asof") or ""))
    bar_date = _iso_ymd(str(sig.get("bar_date") or asof))
    period_dates = [str(d) for d in df["date"].tolist()]
    mark_date = _snap_to_period_date(bar_date, period_dates, period)
    if mark_date is None:
        mark_date = _snap_to_period_date(asof, period_dates, period) or period_dates[-1]
    price = float(df.loc[df["date"] == mark_date, "close"].iloc[0])
    direction = str(sig.get("direction") or "空仓")
    lots = sig.get("lots_l1") or 0
    if direction == "多":
        symbol, color, label = "triangle-up", GREEN, f"PathA 多 · {lots}手"
    elif direction == "空":
        symbol, color, label = "triangle-down", RED, f"PathA 空 · {lots}手"
    else:
        symbol, color, label = "circle", "#94a3b8", f"PathA {direction}"
    r20 = sig.get("r20")
    r60 = sig.get("r60")
    hover = f"{label}<br>r20={r20} r60={r60}<br>asof={asof}"
    return {
        "date": mark_date,
        "price": price,
        "symbol": symbol,
        "color": color,
        "hover": hover,
        "name": "PathA",
    }


def _event_marker_rows(events: list[dict], df: pd.DataFrame) -> list[dict]:
    if df.empty or not events:
        return []
    closes = {str(d): float(p) for d, p in zip(df["date"].astype(str), df["close"])}
    rows = []
    for ev in events:
        day = _iso_ymd(str(ev.get("日期") or ""))
        if day not in closes:
            continue
        kind = str(ev.get("类型") or "事件")
        style = EVENT_STYLE.get(kind, _DEFAULT_EVENT)
        detail = str(ev.get("细节") or "")
        badge = str(ev.get("标记") or "")
        hover = f"{kind}"
        if badge:
            hover += f" · {badge}"
        if detail:
            hover += f"<br>{detail}"
        rows.append(
            {
                "date": day,
                "price": closes[day],
                "symbol": style["symbol"],
                "color": style["color"],
                "size": style["size"],
                "hover": hover,
                "kind": kind,
            }
        )
    return rows


def _candlestick_fig(
    df: pd.DataFrame,
    *,
    title: str,
    show_ma20: bool,
    show_ma60: bool,
    show_atr: bool,
    path_a: dict[str, Any] | None,
    event_rows: list[dict],
    x_col: str = "date",
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.68, 0.32],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )
    if df.empty:
        fig.update_layout(
            title=title,
            annotations=[dict(text="本地无连续合约", showarrow=False, font=dict(color=INK))],
            paper_bgcolor=PAPER,
            plot_bgcolor=PAPER,
            height=520,
        )
        return fig

    x = df[x_col] if x_col in df.columns else df["date"]
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K线",
            increasing_line_color=GREEN,
            decreasing_line_color=RED,
            increasing_fillcolor=GREEN,
            decreasing_fillcolor=RED,
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    if show_ma20 and "ma20" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=df["ma20"],
                name="MA20",
                mode="lines",
                line=dict(color="#2563eb", width=1.4),
            ),
            row=1,
            col=1,
            secondary_y=False,
        )
    if show_ma60 and "ma60" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=df["ma60"],
                name="MA60",
                mode="lines",
                line=dict(color="#d97706", width=1.4),
            ),
            row=1,
            col=1,
            secondary_y=False,
        )
    if show_atr and "atr14" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=df["atr14"],
                name="ATR14",
                mode="lines",
                line=dict(color="#64748b", width=1.2, dash="dot"),
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

    if event_rows:
        by_kind: dict[str, list[dict]] = {}
        for row in event_rows:
            by_kind.setdefault(row["kind"], []).append(row)
        for kind, items in by_kind.items():
            fig.add_trace(
                go.Scatter(
                    x=[r["date"] for r in items],
                    y=[r["price"] for r in items],
                    mode="markers",
                    name=kind,
                    marker=dict(
                        symbol=items[0]["symbol"],
                        size=items[0]["size"],
                        color=items[0]["color"],
                        line=dict(width=1, color="#ffffff"),
                    ),
                    text=[r["hover"] for r in items],
                    hovertemplate="%{text}<extra></extra>",
                ),
                row=1,
                col=1,
                secondary_y=False,
            )

    if path_a:
        fig.add_trace(
            go.Scatter(
                x=[path_a["date"]],
                y=[path_a["price"]],
                mode="markers",
                name=path_a["name"],
                marker=dict(
                    symbol=path_a["symbol"],
                    size=14,
                    color=path_a["color"],
                    line=dict(width=1.5, color="#111111"),
                ),
                text=[path_a["hover"]],
                hovertemplate="%{text}<extra></extra>",
            ),
            row=1,
            col=1,
            secondary_y=False,
        )

    vol_colors = [
        GREEN if c >= o else RED for o, c in zip(df["open"].tolist(), df["close"].tolist())
    ]
    fig.add_trace(
        go.Bar(
            x=x,
            y=df["volume"],
            name="成交量",
            marker_color=vol_colors,
            opacity=0.75,
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK)),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        font=dict(color=INK, size=12, family="Microsoft YaHei, SimHei, sans-serif"),
        height=680,
        margin=dict(l=52, r=24, t=56, b=48),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK)),
        hovermode="x unified",
        dragmode="zoom",
        # Bottom rangeslider for time-axis zoom (TradingView-like scrubber).
        xaxis=dict(
            rangeslider=dict(visible=True, thickness=0.08),
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1日", step="day", stepmode="backward"),
                    dict(count=5, label="5日", step="day", stepmode="backward"),
                    dict(count=1, label="1月", step="month", stepmode="backward"),
                    dict(count=3, label="3月", step="month", stepmode="backward"),
                    dict(step="all", label="全部"),
                ],
                bgcolor="#f5f5f5",
                activecolor="#dbeafe",
            ),
            type="date",
        ),
        xaxis2_rangeslider_visible=False,
    )
    fig.update_xaxes(
        gridcolor=GRID,
        linecolor="#cccccc",
        title_text="时间（左远右近 · 框选拉近 · 滚轮/底部滑条拉远时间轴）",
        row=2,
        col=1,
    )
    fig.update_xaxes(gridcolor=GRID, linecolor="#cccccc", row=1, col=1)
    fig.update_yaxes(gridcolor=GRID, linecolor="#cccccc", title_text="价格", row=1, col=1, secondary_y=False)
    fig.update_yaxes(
        gridcolor=GRID,
        linecolor="#cccccc",
        title_text="ATR",
        showgrid=False,
        row=1,
        col=1,
        secondary_y=True,
    )
    fig.update_yaxes(gridcolor=GRID, linecolor="#cccccc", title_text="量", row=2, col=1)
    fig.update_xaxes(autorange=True)
    return fig


def render_chart_tab(root: Path) -> None:
    st.subheader("图表")
    st.caption(
        "日/周/月本地连续 · 小周期默认 60m 量价（比日线敏感、比 15m 更平滑）· "
        "15m 可下钻 · 框选拉近时间轴、滚轮/滑条拉远 · 新浪主力分钟（东财备选）· 纸面观察 · 不下单"
    )

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
    default_label = next(
        (lab for lab, row in zip(labels, symbols) if row["code"] == default_code),
        labels[0],
    )
    if st.session_state.get("seat_sym") not in labels:
        st.session_state["seat_sym"] = default_label
    if st.session_state.get("chart_sym") not in labels:
        st.session_state["chart_sym"] = st.session_state["seat_sym"]

    def _push_seat_sym() -> None:
        st.session_state["seat_sym"] = st.session_state.get("chart_sym")

    c_sym, c_period, c_win, c_ma, c_atr = st.columns([1.8, 1.0, 0.9, 1.2, 0.7])
    with c_sym:
        choice = st.selectbox("品种", labels, key="chart_sym", on_change=_push_seat_sym)
    meta = symbols[labels.index(choice)]
    code = meta["code"]
    with c_period:
        period_label = st.selectbox(
            "周期",
            [p[0] for p in PERIOD_CHOICES],
            index=0,
            key="chart_period",
        )
    period = next(code for name, code in PERIOD_CHOICES if name == period_label)
    with c_win:
        win_label = st.selectbox("窗口", [w[0] for w in WINDOW_CHOICES], index=1, key="chart_win")
    win_n = next(n for lab, n in WINDOW_CHOICES if lab == win_label)
    with c_ma:
        show_ma20 = st.checkbox("MA20", value=True, key="chart_ma20")
        show_ma60 = st.checkbox("MA60", value=True, key="chart_ma60")
    with c_atr:
        show_atr = st.checkbox("ATR14", value=False, key="chart_atr")

    force_min = False
    if period in ("15", "60"):
        force_min = st.button("刷新分钟线", key="chart_min_refresh")

    asof = (report or {}).get("asof")
    path_a_dir = None
    for sig in (report or {}).get("signals") or []:
        if str(sig.get("code") or "").upper() == code:
            path_a_dir = str(sig.get("direction") or "")
            break

    x_col = "date"
    event_rows: list[dict] = []
    path_a = None
    vp = None
    minute_meta: dict[str, Any] = {}

    if period in ("15", "60"):
        from minute_data import ensure_minute_for_code
        from volume_price import analyze_volume_price

        # verify_em=False: 东财常被代理打断；主源用新浪缓存即可画图。
        minute_meta = ensure_minute_for_code(
            root, code, period, force=force_min, verify_em=False
        )
        bars = minute_meta.get("bars") or []
        st.caption(
            f"当前 {format_variety_label(code, meta.get('name') or '', contract=minute_meta.get('symbol'), root=root)} · "
            f"源 {minute_meta.get('source') or '—'} · asof {asof or '—'} · {minute_meta.get('note') or ''}"
        )
        if not bars:
            st.info("暂无 15m/60m 数据。点「刷新分钟线」；新浪失败时自动改东财备选。")
            return
        # Minute bars carry both `datetime` (bar ts) and `date` (calendar day).
        # Build a fresh single-column frame — never rename/assign across duplicates.
        raw = pd.DataFrame(bars)
        ts = raw["datetime"] if "datetime" in raw.columns else raw["date"]
        if isinstance(ts, pd.DataFrame):
            ts = ts.iloc[:, 0]
        ohlc = pd.DataFrame(
            {
                "date": pd.to_datetime(ts, errors="coerce"),
                "open": pd.to_numeric(raw["open"], errors="coerce"),
                "high": pd.to_numeric(raw["high"], errors="coerce"),
                "low": pd.to_numeric(raw["low"], errors="coerce"),
                "close": pd.to_numeric(raw["close"], errors="coerce"),
                "volume": pd.to_numeric(raw["volume"], errors="coerce"),
            }
        )
        ohlc = (
            ohlc.dropna(subset=["date"])
            .sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )
        df = _indicator_frames(ohlc)
        df = df.copy()
        df["datetime"] = df["date"]  # Series→Series; x-axis needs full timestamp
        x_col = "datetime"
        if win_n and len(df) > win_n:
            df = df.tail(win_n).reset_index(drop=True)
        vp = analyze_volume_price(bars, period=period, path_a_direction=path_a_dir)
        cal = df["datetime"].astype(str).str[:10]
        daily_like = df.assign(date=cal)
        day_ends = daily_like.drop_duplicates("date", keep="last")
        path_a = _path_a_markers(report, code, day_ends, period="D")
        if path_a:
            day = str(path_a["date"])[:10]
            hit = df[df["datetime"].astype(str).str.startswith(day)]
            if not hit.empty:
                path_a = {
                    **path_a,
                    "date": str(hit["datetime"].iloc[-1]),
                    "price": float(hit["close"].iloc[-1]),
                }
        events = events_for_codes(root, report, [code])
        mapped = []
        for ev in _event_marker_rows(events, day_ends):
            day = str(ev["date"])[:10]
            hit = df[df["datetime"].astype(str).str.startswith(day)]
            if hit.empty:
                continue
            mapped.append(
                {
                    **ev,
                    "date": str(hit["datetime"].iloc[-1]),
                    "price": float(hit["close"].iloc[-1]),
                }
            )
        event_rows = mapped
    else:
        bars, source = load_local_bars(root, code)
        st.caption(
            f"当前 {format_variety_label(code, meta.get('name') or '', root=root, exchange_zh=EX_ZH.get(meta['exchange'], meta['exchange']))} · "
            f"asof {asof or '—'} · 源 {source or '无'} · 周期 {period_label}"
        )
        if not bars:
            st.info("本地无连续合约日线（.cache/sina 下 CODE0.json）。先同步或刷新本地缓存。")
            return
        daily = _bars_frame(bars)
        daily = _resample_ohlcv(daily, period)
        df = _indicator_frames(daily)
        if win_n and len(df) > win_n:
            df = df.tail(win_n).reset_index(drop=True)
        events = events_for_codes(root, report, [code])
        event_rows = _event_marker_rows(events, df)
        path_a = _path_a_markers(report, code, df, period=period)
        # Prefer 60m VP beside daily/weekly: sensitive vs D, smoother equity path vs 15m.
        try:
            from minute_data import ensure_minute_for_code
            from volume_price import analyze_volume_price

            minute_meta = ensure_minute_for_code(root, code, "60", force=False, verify_em=False)
            if minute_meta.get("bars"):
                vp = analyze_volume_price(
                    minute_meta["bars"], period="60", path_a_direction=path_a_dir
                )
            else:
                minute_meta = ensure_minute_for_code(
                    root, code, "15", force=False, verify_em=False
                )
                if minute_meta.get("bars"):
                    vp = analyze_volume_price(
                        minute_meta["bars"], period="15", path_a_direction=path_a_dir
                    )
        except Exception as exc:  # noqa: BLE001
            st.caption(f"小周期量价暂不可用：{exc}")

    fig = _candlestick_fig(
        df,
        title=f"{format_variety_label(code, meta.get('name') or '', root=root)} {PERIOD_LABEL.get(period, period)}",
        show_ma20=show_ma20,
        show_ma60=show_ma60,
        show_atr=show_atr,
        path_a=path_a,
        event_rows=event_rows,
        x_col=x_col if x_col in df.columns else "date",
    )
    from desk.charts import PLOTLY_TIME_CONFIG

    st.plotly_chart(fig, width="stretch", config=PLOTLY_TIME_CONFIG)

    if vp and vp.get("ok"):
        vp_p = vp.get("period") or "?"
        st.markdown(f"**小周期量价判断（{vp_p}m）**")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("结构", vp.get("label"))
        m2.metric("倾向", vp.get("stance"))
        m3.metric("量比", vp.get("vol_ratio"))
        m4.metric("本根涨跌%", vp.get("px_pct"))
        st.caption(vp.get("judgment") or "")
        if vp.get("note"):
            st.caption(vp["note"])
        verify = (minute_meta or {}).get("verify") if minute_meta else None
        if verify:
            st.caption(
                f"东财交叉验证：overlap={verify.get('overlap')} · "
                f"价偏差中位={verify.get('median_close_rel')} · "
                f"量偏差中位={verify.get('median_volume_rel')} · {verify.get('note')}"
            )
    elif period in ("15", "60"):
        st.caption("量价判断：样本不足或分钟线为空。")

    if path_a:
        st.caption(f"PathA 标记：{path_a['hover'].replace('<br>', ' · ')}")
    if event_rows:
        st.caption(f"窗口内事件标记 {len(event_rows)} 条（动量/席位/基差等，悬停看细节）。")
    else:
        st.caption("窗口内暂无事件标记。")
