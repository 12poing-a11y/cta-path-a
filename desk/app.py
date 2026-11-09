# -*- coding: utf-8 -*-
"""CTA Path-A local Streamlit research desk."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.charts import drawdown_overlay_fig, equity_overlay_fig, sleeve_bar_fig  # noqa: E402
from desk.loaders import (  # noqa: E402
    align_curves,
    equity_curve_df,
    load_l1_report,
    load_strategy_payload,
    option_hedge_defaults,
    registry_status_table,
    sleeve_pnl_series,
    strategy_availability,
    strategy_kpis,
)
from desk.chart_board import render_chart_tab  # noqa: E402
from desk.curve_lag import curve_end_date, curve_lag  # noqa: E402
from desk.freshness import render_freshness_header  # noqa: E402
from desk.options_panel import DISCLAIMER, build_opportunities, opt_hedge_backtest_kpis  # noqa: E402
from desk.gamma_panel import render_gamma_panel  # noqa: E402
from desk.decision import render_decision_tab  # noqa: E402
from desk.final_signal import DETAIL_CAPTION, render_final_signal_tab  # noqa: E402
from desk.proxy_positions import render_proxy_positions  # noqa: E402
from desk.regime_board import render_regime_tab  # noqa: E402
from desk.scoreboard import scoreboard_rows  # noqa: E402
from desk.seat_board import render_seat_sector  # noqa: E402
from desk.strategies.registry import all_strategies  # noqa: E402
from desk.tech_score_panel import render_tech_score_panel  # noqa: E402
from market_data import latest_expected_session_date  # noqa: E402
from desk.sync_desk import (  # noqa: E402
    book_freshness,
    clear_streamlit_caches,
    git_repo_status,
    report_mtime_note,
    sync_desk,
)
from desk.vol_engine_panel import vol_fields_by_code  # noqa: E402

# Default overlay: Path-A + three local proxies.
DEFAULT_COMPARE_IDS = (
    "path_a",
    "proxy_cwft",
    "proxy_frontnext_st",
    "proxy_long_short_cwft",
)
# Suggested cut/park: hide from sidebar compare (files stay on disk for research).
PARKED_COMPARE_IDS = frozenset(
    {
        "sleeve_mr",
        "sleeve_donchian",
        "sleeve_xs_mom",
        "path_a_opt_hedge",
        "param_sweep",
        "benchmark",
    }
)
# Nav order: P&L / drawdown reference first, then structure / sentiment / options.
DESK_PAGES = (
    "最终信号",
    "概览对比",
    "技术分析",
    "决策",
    "图表",
    "日信号",
    "状态评分",
    "席位板块",
    "情绪",
    "E1·情绪影子·不计分",
    "期权机会",
    "套利观察",
    "Gamma 结构",
)

st.set_page_config(page_title="CTA Path-A Desk", layout="wide", initial_sidebar_state="expanded")


@st.cache_data(show_spinner=False)
def _cached_status():
    return registry_status_table(ROOT)


@st.cache_data(show_spinner=False)
def _cached_scoreboard():
    return scoreboard_rows(ROOT)


@st.cache_data(show_spinner=False)
def _cached_payload(strategy_id: str):
    specs = {s.id: s for s in all_strategies(ROOT)}
    spec = specs.get(strategy_id)
    if spec is None:
        return None
    return load_strategy_payload(spec, ROOT)


def _render_sync_panel() -> None:
    """Pull 15:30 Actions reports (and optional local cache refresh) into the desk."""
    st.subheader("同步日报")
    fresh = book_freshness(ROOT)
    mtime = fresh.get("l1") or report_mtime_note(ROOT)
    git = git_repo_status(ROOT)
    st.markdown("**新鲜度**")
    for line in fresh.get("lines") or []:
        st.caption(line)
    try:
        er = (ROOT / "execution_rules.json")
        if er.is_file():
            import json as _json

            _er = _json.loads(er.read_text(encoding="utf-8"))
            if _er.get("ok"):
                _cb = _er.get("carry_bypass") or {}
                _vb = _er.get("vol_bypass") or {}
                _extra = ""
                if isinstance(_cb, dict) and _cb.get("enabled"):
                    _extra += (
                        f" · 升贴水旁路|{_cb.get('extreme_gap_pct')}%/"
                        f"{_cb.get('action')}"
                    )
                if isinstance(_vb, dict) and _vb.get("enabled"):
                    _extra += (
                        f" · 波动旁路|{_vb.get('expand_ratio')}×/"
                        f"{_vb.get('action')}"
                    )
                st.caption(
                    f"执行SSOT：止损 {_er.get('stop_atr_mult')}×ATR / "
                    f"止盈 {_er.get('reward_rr')}R{_extra} · "
                    f"{_er.get('summary_zh') or ''}"
                )
    except Exception:
        pass
    if fresh.get("stale") or mtime.get("stale"):
        st.warning(fresh.get("note") or mtime["note"])
    elif fresh.get("aligned"):
        st.success("日信号与模拟仓 asof 对齐。")
    else:
        st.caption(fresh.get("note") or mtime["note"])
    st.caption(git["message"])
    if not git.get("has_remote"):
        st.caption(
            "git pull 不可用时，勾选「刷新本地缓存」可跑 daily_update.py，"
            "从免费源重建日报与 member/sina 缓存。"
        )
    pull_git = st.checkbox(
        "同步 main 日报 + 图表行情缓存（日线 CODE0 / history / 15m / 60m）",
        value=True,
        key="desk_sync_git",
    )
    refresh_cache = st.checkbox(
        "刷新本地缓存（daily_update.py，较慢/需网络）",
        value=False,
        key="desk_sync_cache",
    )
    if st.button("同步日报", key="desk_sync_btn"):
        with st.spinner("同步中…"):
            result = sync_desk(
                ROOT,
                pull_git=bool(pull_git),
                refresh_cache=bool(refresh_cache),
            )
        for msg in result.get("messages") or []:
            if result.get("ok"):
                st.info(msg)
            else:
                st.warning(msg)
        if result.get("ok"):
            clear_streamlit_caches()
            st.success("已清除缓存，正在刷新图表。")
            st.rerun()
        else:
            st.error("同步未完全成功；可改勾「刷新本地缓存」或检查 remote。")
    if st.button("仅刷新模拟仓", key="desk_paper_btn"):
        with st.spinner("刷新 paper_book…"):
            try:
                from paper_book import refresh_paper_book

                paper = refresh_paper_book(ROOT)
            except Exception as exc:
                paper = {"ok": False, "error": str(exc)}
        if paper.get("ok"):
            clear_streamlit_caches()
            st.success(
                f"模拟仓 asof={paper.get('asof')} 持仓={paper.get('held_n')} "
                f"（开{paper.get('opened_n')} / 平{paper.get('closed_n')}）"
            )
            st.rerun()
        else:
            st.error(f"模拟仓刷新失败：{paper.get('error')}")


def _status_label(avail: str) -> str:
    return {
        "ready": "有曲线",
        "kpi_only": "KPI跟踪",
        "missing": "缺文件",
        "placeholder": "占位待填",
    }.get(avail, avail)


def main() -> None:
    st.title("CTA Path-A 研究台")
    st.caption("只读引擎产物 · 纸面观察 · 不下单")

    specs = all_strategies(ROOT)
    avail_map = {s.id: strategy_availability(s, ROOT) for s in specs}
    scored_ids = {row["id"] for row in _cached_scoreboard()}
    specs = [s for s in specs if s.id in scored_ids]
    show_parked = False

    # --- sidebar ---
    with st.sidebar:
        st.header("策略选择")
        show_parked = st.checkbox(
            "显示已下架对照（mr/唐奇安/截面动量/期权叠加/扫参/benchmark）",
            value=False,
            key="desk_show_parked",
        )
        labels = []
        id_by_label = {}
        default_sel = []
        for s in specs:
            if s.id in PARKED_COMPARE_IDS and not show_parked:
                continue
            avail = avail_map[s.id]
            mark = " ·曲线" if avail == "ready" else " ·KPI"
            label = f"{s.name}{mark}"
            labels.append(label)
            id_by_label[label] = s.id
            if avail == "ready" and s.id in DEFAULT_COMPARE_IDS:
                default_sel.append(label)

        chosen_labels = st.multiselect("叠加对比", labels, default=default_sel)
        chosen_ids = [id_by_label[x] for x in chosen_labels]
        st.caption(
            "默认：Path-A + 三个本地 proxy。"
            + ("已显示下架项。" if show_parked else "弱/负效用对照已下架，勾选上方可临时查看。")
        )

        st.divider()
        normalize = st.checkbox("归一化到 100", value=True)
        use_gross = st.checkbox("毛权益（有字段时）", value=False)
        st.caption("曲线点含 equity_gross / gross_equity 时才生效")

        # date range from available curves
        min_d, max_d = None, None
        for sid in chosen_ids:
            df = equity_curve_df(_cached_payload(sid))
            if df.empty:
                continue
            d0, d1 = df["date"].min(), df["date"].max()
            min_d = d0 if min_d is None else min(min_d, d0)
            max_d = d1 if max_d is None else max(max_d, d1)
        if min_d is not None and max_d is not None:
            dr = st.date_input("日期范围", value=(min_d.date(), max_d.date()))
            if isinstance(dr, tuple) and len(dr) == 2:
                start_ts = pd.Timestamp(dr[0])
                end_ts = pd.Timestamp(dr[1])
            else:
                start_ts, end_ts = pd.Timestamp(min_d), pd.Timestamp(max_d)
        else:
            start_ts = end_ts = None
            st.info("所选策略暂无曲线，日期范围不可用")

        st.divider()
        defaults = option_hedge_defaults(ROOT)
        st.subheader("期权参数")
        prem_m = st.slider(
            "premium_atr_mult",
            min_value=0.1,
            max_value=3.0,
            value=float(defaults["premium_atr_mult"]),
            step=0.1,
        )
        strike_m = st.slider(
            "strike_atr_mult",
            min_value=0.0,
            max_value=2.0,
            value=float(defaults["strike_atr_mult"]),
            step=0.1,
        )
        st.caption("默认来自 universe.json → observe.option_hedge")

        st.divider()
        _render_sync_panel()

    # Radio nav: only the active page runs (st.tabs would execute every panel).
    page = st.radio(
        "页面",
        list(DESK_PAGES),
        horizontal=True,
        key="desk_active_page",
        label_visibility="collapsed",
    )
    st.caption(
        "导航优先：最终信号 → 概览(盈亏/回撤) → 技术打分 → 决策/图表；"
        "情绪与期权结构靠后。仅渲染当前页。"
    )

    if page == "最终信号":
        render_freshness_header(ROOT, "最终信号")
        render_final_signal_tab(ROOT)

    if page == "技术分析":
        render_freshness_header(ROOT, "技术分析")
        render_tech_score_panel(ROOT)

    # --- Tab 1: compare ---
    if page == "概览对比":
        render_freshness_header(ROOT, "概览对比")
        curves = {}
        kpi_rows = []
        grey_notes = []
        health_rows = []
        expected = latest_expected_session_date().isoformat()
        for sid in chosen_ids:
            spec = next(s for s in specs if s.id == sid)
            avail = avail_map[sid]
            payload = _cached_payload(sid)
            kpis = strategy_kpis(spec, ROOT)
            curve_end = None
            lag = None
            if payload:
                curve_end = str(kpis.get("end") or payload.get("end") or "")[:10] or None
                if not curve_end:
                    df0 = equity_curve_df(payload)
                    if not df0.empty:
                        curve_end = str(df0["date"].max().date())
                if curve_end:
                    try:
                        lag = (
                            pd.Timestamp(expected) - pd.Timestamp(curve_end)
                        ).days
                    except (TypeError, ValueError):
                        lag = None
            stale = bool(lag is not None and lag > 5)
            health_rows.append(
                {
                    "策略": spec.name,
                    "曲线截止": curve_end or "—",
                    "期望会话": expected,
                    "滞后日": lag if lag is not None else "—",
                    "健康": "过期" if stale else ("就绪" if avail == "ready" else _status_label(avail)),
                }
            )
            row = {
                "策略": spec.name,
                "状态": _status_label(avail),
                "曲线截止": curve_end or "—",
                "年化%": kpis.get("ret_ann_pct"),
                "区间收益%": kpis.get("ret_pct"),
                "最大回撤%": kpis.get("max_dd_pct"),
                "毛收益%": kpis.get("gross_ret_pct"),
                "毛回撤%": kpis.get("gross_max_dd_pct"),
                "夏普": kpis.get("sharpe"),
                "Calmar": kpis.get("calmar"),
                "近一周%": kpis.get("week_ret_pct"),
                "期末权益": kpis.get("equity_end"),
                "成本(元)": kpis.get("cost_yuan"),
                "来源": kpis.get("source") or str(spec.curve_path or "—"),
            }
            kpi_rows.append(row)

            if avail == "ready" and payload:
                df = equity_curve_df(payload)
                eq_col = "equity"
                if use_gross:
                    for c in ("equity_gross", "gross_equity"):
                        if c in df.columns:
                            eq_col = c
                            break
                if not df.empty and eq_col in df.columns:
                    one = df.rename(columns={eq_col: "equity"}) if eq_col != "equity" else df
                    label = f"{spec.name}·滞后" if stale else (spec.name or sid)
                    curves[label] = one.copy()
                    if stale:
                        grey_notes.append(
                            f"{spec.name}：曲线滞后 {lag} 日（截止 {curve_end}），"
                            "请跑 python proxy_cta.py 或同步日报"
                        )
            elif avail == "kpi_only":
                grey_notes.append(f"{spec.name}：KPI 跟踪（无曲线属正常，看上表数字）")
            elif avail == "placeholder":
                grey_notes.append(f"{spec.name}：占位待填")
            elif avail == "missing":
                grey_notes.append(f"{spec.name}：缺少 `{spec.curve_path}`")

        if health_rows:
            st.subheader("策略健康（盈亏/回撤参考）")
            st.caption("滞后>5 个交易日视为过期；叠加图仍可画但会标注「·滞后」。")
            st.dataframe(pd.DataFrame(health_rows), width="stretch", hide_index=True)

        if kpi_rows:
            st.subheader("窗口 KPI / 跟踪数字")
            st.caption("优先看区间收益%与最大回撤%；毛收益有字段才填。")
            st.dataframe(pd.DataFrame(kpi_rows), width="stretch", hide_index=True)

        if grey_notes:
            with st.expander("无曲线说明（可折叠）", expanded=False):
                for n in grey_notes:
                    st.caption(n)

        try:
            render_proxy_positions(st, ROOT)
        except Exception as exc:  # soft-fail: never break overview
            st.caption(f"本地代理模拟持仓暂不可用：{exc}")

        if curves:
            aligned = align_curves(
                curves,
                start=start_ts,
                end=end_ts,
                normalize=normalize,
                equity_col="equity",
            )
            y_title = "归一化=100" if normalize else "权益"
            st.plotly_chart(
                equity_overlay_fig(aligned, title="多策略净值叠加（仅有曲线者）", y_title=y_title),
                width="stretch",
            )
            st.plotly_chart(
                drawdown_overlay_fig(aligned, title="回撤叠加"),
                width="stretch",
            )
        else:
            st.info("当前勾选里没有带 `equity_curve` 的策略；KPI 数字见上表。可选侧栏带「·曲线」的 Path-A / 本地代理。")

        # sleeve panel for benchmark if selected
        if "benchmark" in chosen_ids:
            bench_payload = _cached_payload("benchmark")
            sleeve_df = sleeve_pnl_series(bench_payload)
            st.subheader("对照 sleeve")
            if sleeve_df is not None and not sleeve_df.empty:
                st.plotly_chart(sleeve_bar_fig(sleeve_df), width="stretch")
                st.dataframe(
                    sleeve_df.sort_values("date", ascending=False),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("benchmark 暂无 sleeve 序列；窗口 KPI 中的 pnl_by_sleeve 见上表。")
                k = strategy_kpis(next(s for s in specs if s.id == "benchmark"), ROOT)
                if k.get("pnl_by_sleeve"):
                    st.json(k["pnl_by_sleeve"])

    # --- Tab 2: daily signals ---
    if page == "日信号":
        render_freshness_header(ROOT, "日信号")
        st.caption(DETAIL_CAPTION)
        report = load_l1_report(ROOT)
        if not report:
            st.error("缺少 l1_report.json，请先运行 daily_update.py")
        else:
            from desk.equity_book import load_book_equity
            from desk.premarket_compare import render_premarket_card

            book_eq = load_book_equity(ROOT, report)
            render_premarket_card(ROOT)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("asof", report.get("asof"))
            if book_eq.get("ok") and book_eq.get("equity_mark") is not None:
                c2.metric(
                    "盯市权益",
                    f"{book_eq['equity_mark']:,.0f}",
                    delta=(
                        f"浮动 {book_eq['equity_floating']:+,.0f}"
                        if book_eq.get("equity_floating") is not None
                        else None
                    ),
                )
            else:
                c2.metric(
                    "权益",
                    f"{report.get('equity'):,.0f}" if report.get("equity") is not None else "—",
                )
            c3.metric("入场过滤", report.get("entry_filter"))
            c4.metric("数据源", str(report.get("data_source") or "")[:24])
            if book_eq.get("ok") and book_eq.get("equity") is not None:
                st.caption(
                    f"记账对齐 paper_book（{book_eq.get('source')} asof {book_eq.get('asof') or '—'}）："
                    f"已实现 {book_eq['equity']:,.0f} · 浮动 {book_eq.get('equity_floating') or 0:+,.0f} · "
                    f"盯市 {book_eq['equity_mark']:,.0f}；手数按已实现权益计风险，浮动仅展示。"
                )
            q = report.get("quality") or {}
            if report.get("quality_ok") is False:
                st.error(
                    f"质量门禁未通过：{q.get('failures') or q.get('bad_codes') or '见 quality'}；"
                    "正式报告已扣留，不下单。"
                )
            elif report.get("quality_ok"):
                st.caption(f"质量门禁通过（checked={q.get('checked')}）· live_trading=否")
            st.info("情绪多空结论、把握%与中文品种表已挪到顶部「情绪」页（不再嵌在本页）。")

            port = report.get("portfolio") or {}
            st.subheader("组合帽摘要")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("已选", ", ".join(port.get("selected") or []) or "—")
            m2.metric("名义敞口%", port.get("gross_pct"))
            m3.metric("ATR风险%", port.get("atr_risk_pct"))
            m4.metric("scale", port.get("scale"))
            with st.expander("组合细节"):
                st.json(
                    {
                        k: port.get(k)
                        for k in (
                            "candidates_n",
                            "weak_filtered",
                            "bucket_skipped",
                            "dropped",
                            "scale_gross",
                            "scale_risk",
                            "gross_before",
                            "gross_after",
                            "atr_risk_before",
                            "atr_risk_after",
                            "max_positions",
                            "max_gross_exposure_pct",
                            "max_portfolio_risk_pct",
                        )
                    }
                )

            st.subheader("L1 信号板（Path-A）")
            sigs = pd.DataFrame(report.get("signals") or [])
            if sigs.empty:
                st.info("无信号行")
            else:
                from desk.loaders import format_variety_label

                # Snapshot-only join (no nested final_signal / full vol rebuild).
                vol_map = vol_fields_by_code(ROOT)
                display_rows = []
                for _, row in sigs.iterrows():
                    code = str(row.get("code") or "").upper()
                    vf = vol_map.get(code) or {}
                    display_rows.append(
                        {
                            "品种": format_variety_label(
                                code, str(row.get("name") or ""), root=ROOT
                            ),
                            "板块": row.get("bucket"),
                            "对齐": row.get("align"),
                            "方向": row.get("direction"),
                            "手数": row.get("lots_l1"),
                            "日选": row.get("selected"),
                            "收盘": row.get("close"),
                            "ATR": row.get("atr"),
                            "R20": row.get("r20"),
                            "R60": row.get("r60"),
                            "席位": row.get("seat"),
                            "情绪分档": vf.get("情绪分档") or "—",
                            "波动状态": vf.get("波动状态") or "—",
                            "定价": vf.get("定价") or "—",
                            "引擎标签": vf.get("引擎标签") or "—",
                            "盘面结论": vf.get("盘面结论") or "—",
                            "动作": row.get("action"),
                        }
                    )
                st.dataframe(
                    pd.DataFrame(display_rows), width="stretch", hide_index=True
                )
                st.caption(
                    "波动列读 data/vol_engine_latest.json 快照；"
                    "重算请到「情绪」页点刷新引擎。品种列=期号+中文。"
                )

    # --- Tab: sentiment sleeve ---
    if page == "情绪":
        render_freshness_header(ROOT, "情绪")
        st.caption(DETAIL_CAPTION)
        from desk.sentiment_panel import render_sentiment_panel
        from desk.behav_finance_panel import render_behav_finance_panel

        render_sentiment_panel(ROOT)
        st.divider()
        render_behav_finance_panel(ROOT)

    if page == "E1·情绪影子·不计分":
        render_freshness_header(ROOT, "E1·情绪影子·不计分")
        from desk.sentiment_history import render_sentiment_history_tab

        render_sentiment_history_tab(ROOT)

    # 预测归因：后台 daily_update 仍写 lab/research/predictions/；UI 已搁置。

    # --- Tab: TV-style chart ---
    if page == "图表":
        render_freshness_header(ROOT, "图表")
        render_chart_tab(ROOT)

    if page == "套利观察":
        render_freshness_header(ROOT, "套利观察")
        from desk.arb_panel import render_arb_panel

        render_arb_panel(ROOT)

    # --- Tab: options ---
    if page == "期权机会":
        render_freshness_header(ROOT, "期权机会")
        st.subheader("保护期权纸面机会")
        st.caption(DISCLAIMER)
        opp = build_opportunities(
            premium_atr_mult=prem_m,
            strike_atr_mult=strike_m,
            root=ROOT,
        )
        if opp.empty:
            st.info(
                "当前模拟仓无持仓候选（paper_book / final_positions 为空，"
                "且 l1_report 也无 lots_l1>0）。可先侧栏「仅刷新模拟仓」。"
            )
        else:
            show = opp.drop(columns=["premium_atr_mult", "strike_atr_mult"], errors="ignore")
            st.dataframe(show, width="stretch", hide_index=True)
            st.caption(
                f"asof={opp.attrs.get('asof')} · premium_atr_mult={prem_m} · strike_atr_mult={strike_m}"
            )

        from desk.hv_panel import render_hv_panel

        render_hv_panel(ROOT, prem_m)

        st.subheader("叠加后回测")
        hedge_curves = {}
        lag_rows = []
        expected_s = latest_expected_session_date().isoformat()
        for label, sid in (("路径A", "path_a"), ("路径A+保护期权", "path_a_opt_hedge")):
            payload_h = _cached_payload(sid)
            curve = equity_curve_df(payload_h)
            info = curve_lag(curve_end_date(payload_h), expected_s)
            lag_rows.append(
                {
                    "曲线": label,
                    "曲线截止": info["curve_end"] or "—",
                    "期望会话": expected_s,
                    "滞后(日历日)": info["lag_days"] if info["lag_days"] is not None else "—",
                    "滞后(工作日)": info["lag_busdays"] if info["lag_busdays"] is not None else "—",
                    "来源": (payload_h or {}).get("_desk_source") or "—",
                    "状态": "滞后" if info["stale"] else ("最新" if info["curve_end"] else "无曲线"),
                }
            )
            if not curve.empty:
                hedge_curves[label] = curve
        st.dataframe(pd.DataFrame(lag_rows), width="stretch", hide_index=True)
        if any(r["状态"] == "滞后" for r in lag_rows):
            st.warning(
                "叠加曲线截止日早于期望会话日：图上只画已有真实回测日，不会补造未来/缺失日线。"
                "可下方刷新模拟仓或重跑历史回测（需本机数据源/iFinD；也可用 Actions 日更后「同步日报」）。"
            )
        with st.expander("刷新叠加曲线（模拟仓 / 历史回测）", expanded=False):
            bcol1, bcol2 = st.columns(2)
            if bcol1.button("刷新模拟仓 paper_book", key="opt_refresh_paper"):
                with st.spinner("刷新 paper_book…"):
                    try:
                        from paper_book import refresh_paper_book

                        paper_r = refresh_paper_book(ROOT)
                    except Exception as exc:
                        paper_r = {"ok": False, "error": str(exc)}
                if paper_r.get("ok"):
                    clear_streamlit_caches()
                    st.success(f"模拟仓 asof={paper_r.get('asof')}（仅更新持仓，不改回测曲线）")
                    st.rerun()
                else:
                    st.error(f"模拟仓刷新失败：{paper_r.get('error')}")
            if bcol2.button("重跑历史回测（耗时）", key="opt_refresh_bt"):
                import subprocess

                with st.spinner("python historical_backtest.py（最长约 15 分钟）…"):
                    try:
                        proc = subprocess.run(
                            [sys.executable, "historical_backtest.py"],
                            cwd=str(ROOT),
                            capture_output=True,
                            text=True,
                            timeout=900,
                        )
                        ok_bt = proc.returncode == 0
                        tail = (proc.stdout or proc.stderr or "")[-1200:]
                    except Exception as exc:
                        ok_bt, tail = False, str(exc)
                if ok_bt:
                    clear_streamlit_caches()
                    st.success("历史回测已重跑，刷新曲线。")
                    st.rerun()
                else:
                    st.error("历史回测失败或超时，曲线未更新。")
                    st.code(tail or "(无输出)")
            st.caption(
                "命令行：`python paper_book.py`、`python historical_backtest.py`。"
                "保护期权曲线优先读 `_art_opt/historical_backtest_latest.json`；"
                "缺则回退主回测且 option_hedge=true。"
            )
        if hedge_curves:
            aligned_h = align_curves(hedge_curves, normalize=True)
            st.plotly_chart(
                equity_overlay_fig(
                    aligned_h,
                    title="保护期权叠加权益（归一化=100，左远右近）",
                    y_title="归一化=100",
                ),
                width="stretch",
            )
            st.plotly_chart(
                drawdown_overlay_fig(aligned_h, title="叠加回撤"),
                width="stretch",
            )
        oh_kpis = opt_hedge_backtest_kpis(ROOT)
        if oh_kpis:
            cols = st.columns(4)
            cols[0].metric("净收益%", oh_kpis.get("ret_pct"))
            cols[1].metric("最大回撤%", oh_kpis.get("max_dd_pct"))
            cols[2].metric("权利金(元)", oh_kpis.get("premium_yuan"))
            cols[3].metric("对冲赔付(元)", oh_kpis.get("hedge_payoff_yuan"))
        elif not hedge_curves:
            st.info("未找到 path_a_opt_hedge 回测产物。")

        st.markdown(f"> **免责声明**：{DISCLAIMER}")

    if page == "Gamma 结构":
        render_freshness_header(ROOT, "Gamma 结构")
        render_gamma_panel(ROOT)

    if page == "席位板块":
        render_freshness_header(ROOT, "席位板块")
        render_seat_sector(ROOT)

    if page == "状态评分":
        render_freshness_header(ROOT, "状态评分")
        st.caption(DETAIL_CAPTION)
        render_regime_tab(ROOT)

    if page == "决策":
        render_freshness_header(ROOT, "决策")
        st.caption(DETAIL_CAPTION)
        render_decision_tab(ROOT)


if __name__ == "__main__":
    main()
