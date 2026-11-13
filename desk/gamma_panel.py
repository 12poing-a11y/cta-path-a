# -*- coding: utf-8 -*-
"""Gamma Wall desk panel — zero-centered Call/Put GEX + Flip / Net + migration."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import gamma_wall as _gamma_wall

# Streamlit often reloads this panel without reloading gamma_wall — force refresh
# when the engine gained new public helpers after the process started.
_need_reload = (
    not hasattr(_gamma_wall, "resolve_snapshot_asof")
    or not hasattr(_gamma_wall, "build_gamma_structure")
    or not hasattr(_gamma_wall, "supported_contracts")
    or len(getattr(_gamma_wall, "PRODUCTS", {})) < 8
)
if _need_reload:
    _gamma_wall = importlib.reload(_gamma_wall)

build_gamma_structure = _gamma_wall.build_gamma_structure
demo_gamma_snapshot = _gamma_wall.demo_gamma_snapshot
fetch_snapshot = _gamma_wall.fetch_snapshot
load_history = _gamma_wall.load_history
migration_rows = _gamma_wall.migration_rows
resolve_snapshot_asof = _gamma_wall.resolve_snapshot_asof
supported_contracts = _gamma_wall.supported_contracts
PRODUCTS = _gamma_wall.PRODUCTS


def _enrich(snap: dict[str, Any]) -> dict[str, Any]:
    """Ensure Flip / Net / cum curve exist on legacy schema_version=2 snaps."""
    out = dict(snap)
    rows = out.get("rows") or []
    need = out.get("gamma_flip") is None or out.get("net_gex") is None or not out.get("cum_net_gex")
    if rows and need:
        try:
            structure = build_gamma_structure(rows, futures_price=out.get("futures_price"))
            out.setdefault("call_wall", structure["call_wall"]["strike"])
            out.setdefault("put_wall", structure["put_wall"]["strike"])
            out["gamma_flip"] = structure["gamma_flip"]
            out["net_gex"] = structure["net_gex"]
            out["cum_net_gex"] = structure["cum_net_gex"]
            out["gex_model"] = structure["gex_model"]
        except ValueError:
            pass
    return out


def _fmt_strike(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_gex(v: Any) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    ax = abs(x)
    if ax >= 1e6:
        return f"{x/1e6:,.2f}M"
    if ax >= 1e3:
        return f"{x/1e3:,.1f}k"
    return f"{x:,.1f}"


def _structure_figure(snap: dict[str, Any]) -> go.Figure:
    df = pd.DataFrame(snap["rows"]).sort_values("strike")
    cum = snap.get("cum_net_gex") or []
    cdf = pd.DataFrame(cum) if cum else pd.DataFrame(columns=["strike", "cum_net_gex"])

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.62, 0.38],
        vertical_spacing=0.08,
        subplot_titles=(
            "Call / Put GEX（零轴对称 · 分类展示）",
            "累计情景 Net GEX（低→高行权价）",
        ),
    )
    fig.add_bar(
        x=df["strike"],
        y=df["call_gex"],
        name="Call 侧",
        marker_color="#16a36a",
        row=1,
        col=1,
    )
    fig.add_bar(
        x=df["strike"],
        y=df["put_gex"],
        name="Put 侧",
        marker_color="#d84b5b",
        row=1,
        col=1,
    )
    fig.add_hline(y=0, line_color="#777", line_width=1, row=1, col=1)

    fp = snap.get("futures_price")
    if fp is not None:
        fig.add_vline(
            x=fp,
            line_dash="dash",
            line_color="#3980d8",
            annotation_text="F",
            annotation_position="top",
            row=1,
            col=1,
        )
    for key, color, label in (
        ("put_wall", "#d84b5b", "Put Wall"),
        ("call_wall", "#16a36a", "Call Wall"),
        ("gamma_flip", "#c27a00", "Flip"),
    ):
        v = snap.get(key)
        if v is None:
            continue
        fig.add_vline(
            x=v,
            line_dash="dot",
            line_color=color,
            annotation_text=f"{label} {float(v):g}",
            annotation_position="bottom",
            row=1,
            col=1,
        )

    if not cdf.empty:
        fig.add_trace(
            go.Scatter(
                x=cdf["strike"],
                y=cdf["cum_net_gex"],
                mode="lines",
                name="累计 Net",
                line=dict(color="#5b5b5b", width=2),
            ),
            row=2,
            col=1,
        )
        fig.add_hline(y=0, line_color="#999", line_width=1, row=2, col=1)
        if snap.get("gamma_flip") is not None:
            fig.add_vline(
                x=snap["gamma_flip"],
                line_dash="dot",
                line_color="#c27a00",
                row=2,
                col=1,
            )

    fig.update_layout(
        barmode="relative",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=48, b=24, l=48, r=16),
        height=560,
    )
    fig.update_xaxes(title_text="行权价", row=2, col=1)
    fig.update_yaxes(title_text="≈1% 变动 Gamma 暴露", row=1, col=1)
    fig.update_yaxes(title_text="累计 Net", row=2, col=1)
    return fig


def _render_snapshot(snap: dict[str, Any], *, title: str) -> None:
    snap = _enrich(snap)
    st.markdown(f"**{title}**")
    demo = bool(snap.get("demo"))
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Call Wall", _fmt_strike(snap.get("call_wall")))
    m2.metric("Put Wall", _fmt_strike(snap.get("put_wall")))
    m3.metric("Gamma Flip", _fmt_strike(snap.get("gamma_flip")))
    m4.metric("Net GEX（情景）", _fmt_gex(snap.get("net_gex")))
    m5.metric("标的 F", _fmt_strike(snap.get("futures_price")))

    quality = snap.get("data_quality") or {}
    bits = [
        f"asof {snap.get('asof', '—')}",
        f"系列 {snap.get('option_month', '—')}",
        f"到期 {snap.get('expiry', '—')}",
        f"质量 {quality.get('status', '—')}",
        f"有效行权价 {quality.get('valid_strikes', len(snap.get('rows') or []))}",
    ]
    if quality.get("valid_contract_coverage") is not None and not demo:
        bits.append(f"覆盖率 {quality['valid_contract_coverage']}")
    if snap.get("source"):
        bits.append(str(snap["source"]))
    st.caption(" · ".join(bits))

    if snap.get("rows"):
        st.plotly_chart(_structure_figure(snap), use_container_width=True)
    if snap.get("disclaimer"):
        st.warning(snap["disclaimer"])
    else:
        st.warning(
            "Call/Put 为分类展示；OI 无法识别持仓方。Flip / Net 为情景累计假设，非 dealer 真实净头寸。"
        )


def render_gamma_panel(root: Path) -> None:
    st.subheader("期权 Gamma Wall")
    st.caption(
        "框架：零轴对称 Call(+)/Put(−) · Call Wall / Put Wall / Gamma Flip / Net GEX · 累计曲线 · 墙位迁移。"
        "免费源：郑商所期权日行情 + 新浪目标期货合约；只读研究。"
    )

    default_asof = resolve_snapshot_asof()
    contracts = list(supported_contracts(root=root))
    uni_codes: set[str] = set()
    try:
        import json as _json

        uni = _json.loads((root / "universe.json").read_text(encoding="utf-8"))
        uni_codes = {
            str(s.get("code") or "").upper()
            for s in (uni.get("symbols") or [])
            if isinstance(s, dict)
        }
    except Exception:
        uni_codes = set()
    contract_labels = []
    for c in contracts:
        prod = c[:-4]
        meta = PRODUCTS.get(prod) or {}
        name = meta.get("label") or prod
        tag = "" if (not uni_codes or prod in uni_codes) else " ·宇宙外"
        contract_labels.append(f"{c} · {name}{tag}")
    st.caption("仅列出有期权链的品种；无期权品种不出 Gamma 图。IV/OI 仍用交易所日表，不用扶摇期权 OHLC 冒充。")
    c1, c2, c3 = st.columns([1.1, 1, 1.2])
    pick = c1.selectbox("目标合约", contract_labels, index=0)
    contract = pick.split(" · ", 1)[0].strip()
    window = c2.selectbox("墙位迁移窗口", [5, 10, 20, 30, 60], index=2)
    asof = c3.text_input(
        "快照交易日",
        value=default_asof,
        help="默认=已收盘日盘交易日（15:00 前不用日历今天）。须与单合约日线、期权表同一天。",
    )
    c4, c5 = st.columns([1.4, 1])
    expiry = c4.text_input("期权到期/最后交易日", value="", placeholder="YYYY-MM-DD")
    show_demo = c5.toggle("样式示意", value=False, help="虚构结构图，不含行情")

    st.caption(
        f"默认快照日 {default_asof}（已收盘会话，非日历今天）。"
        "到期日须按郑商所规则核实；禁止用主连或前一日结算价顶替所选交易日。"
    )

    if st.button("拉取并计算 Gamma 快照", type="primary"):
        if len(expiry) != 10:
            st.error("请先填写经核实的到期/最后交易日 YYYY-MM-DD。")
        elif len(asof) != 10:
            st.error("快照交易日须为 YYYY-MM-DD。")
        else:
            try:
                with st.spinner("调用免费期权日行情与目标期货单合约日线…"):
                    snap = fetch_snapshot(
                        contract, expiry=expiry, trade_date=asof, root=root
                    )
                st.success(
                    f"快照完成：{snap['asof']} · {snap['data_quality']['valid_strikes']} 个有效行权价"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"计算失败：{exc}")

    if show_demo:
        with st.expander("样式示意（合成数据 · 非行情）", expanded=True):
            _render_snapshot(demo_gamma_snapshot(contract=contract), title="示意结构")

    history = load_history(contract, root=root)
    _n_valid = len(history or [])
    st.caption(
        f"累积有效快照 {_n_valid} 个交易日 / 所选窗口 {window} 日"
        + ("（已满足）" if _n_valid >= window else f"（还差 {window - _n_valid} 日；每日需配置 GAMMA_*_EXPIRY Variables 才会自动累积）")
    )
    if not history:
        st.info(
            "尚无历史快照。首次拉取后开始累积墙位迁移；不使用虚构数据回填。"
            "可先打开「样式示意」查看正负对称 + Flip + 累计 Net 布局。"
        )
        return

    latest = _enrich(history[-1])
    _render_snapshot(latest, title=f"最新快照 · {contract}")

    hist = migration_rows(contract, window=window, root=root)
    if not hist:
        return

    hdf = pd.DataFrame(hist)
    st.subheader(f"墙位迁移 · 最近 {window} 个交易日")
    mf = go.Figure()
    mf.add_trace(go.Scatter(x=hdf["date"], y=hdf["call_wall"], mode="lines+markers", name="Call Wall"))
    mf.add_trace(go.Scatter(x=hdf["date"], y=hdf["put_wall"], mode="lines+markers", name="Put Wall"))
    if "gamma_flip" in hdf.columns and hdf["gamma_flip"].notna().any():
        mf.add_trace(
            go.Scatter(x=hdf["date"], y=hdf["gamma_flip"], mode="lines+markers", name="Gamma Flip")
        )
    mf.add_trace(
        go.Scatter(x=hdf["date"], y=hdf["futures_price"], mode="lines+markers", name="期货价格")
    )
    mf.update_layout(
        xaxis_title="交易日",
        yaxis_title="价格 / 行权价",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=360,
    )
    st.plotly_chart(mf, use_container_width=True)

    show_cols = [
        c
        for c in (
            "date",
            "futures_price",
            "put_wall",
            "gamma_flip",
            "call_wall",
            "put_dist_pct",
            "call_dist_pct",
            "net_gex",
            "put_wall_move",
            "call_wall_move",
        )
        if c in hdf.columns
    ]
    st.dataframe(
        hdf[show_cols].sort_values("date", ascending=False),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        f"可用历史 {len(history)} 个交易日 · 窗口 {window}。"
        " call/put_dist_pct = (墙 − F)/F；历史不足不补造。"
    )

    research = root / "lab" / "research" / "gamma" / f"gamma_{contract}_latest.json"
    if research.is_file():
        import json

        with st.expander("研究层：迁移标签 / 触碰事件 / IV×OI", expanded=False):
            try:
                payload = json.loads(research.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                st.caption(f"无法读取研究产物：{exc}")
                return
            st.caption(payload.get("disclaimer") or "Research only.")
            mig = payload.get("migration") or {}
            touch = payload.get("touch") or {}
            ivoi = payload.get("iv_oi") or {}
            c1, c2, c3 = st.columns(3)
            c1.metric("迁移事件", mig.get("n_events"))
            c2.metric("触碰事件", touch.get("n_events"))
            c3.metric("IV×OI 天数", ivoi.get("n_days"))
            st.write("迁移标签", mig.get("label_counts") or {})
            st.write("触碰结果", touch.get("outcome_probs") or {})
            st.write("IV×OI 状态", ivoi.get("regime_counts") or {})
            st.caption("生成：`python lab/scripts/run_gamma_research.py --contract CF2701`")

