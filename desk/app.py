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
from desk.freshness import render_freshness_header  # noqa: E402
from desk.options_panel import DISCLAIMER, build_opportunities, opt_hedge_backtest_kpis  # noqa: E402
from desk.decision import render_decision_tab  # noqa: E402
from desk.regime_board import render_regime_tab  # noqa: E402
from desk.scoreboard import scoreboard_rows  # noqa: E402
from desk.seat_board import render_seat_sector  # noqa: E402
from desk.strategies.registry import all_strategies  # noqa: E402
import importlib  # noqa: E402

import desk.sync_desk as _sync_desk_mod  # noqa: E402

# Streamlit may keep a pre-edit sync_desk in sys.modules; reload so new helpers appear.
_sync_desk_mod = importlib.reload(_sync_desk_mod)
clear_streamlit_caches = _sync_desk_mod.clear_streamlit_caches
git_repo_status = _sync_desk_mod.git_repo_status
report_mtime_note = _sync_desk_mod.report_mtime_note
sync_desk = _sync_desk_mod.sync_desk
book_freshness = getattr(_sync_desk_mod, "book_freshness", None)
if book_freshness is None:
    # Extremely stale module: degrade to l1-only freshness.
    def book_freshness(root, now=None):  # type: ignore[misc]
        l1 = report_mtime_note(root, now=now)
        lines = [f"日信号 asof={l1.get('asof') or '—'}（请重启 Streamlit 以加载完整新鲜度）"]
        return {
            "stale": bool(l1.get("stale")),
            "aligned": False,
            "book_behind": False,
            "book_missing": True,
            "l1_asof": l1.get("asof"),
            "paper_asof": None,
            "backtest_end": None,
            "equity_asof": None,
            "equity_mtime": None,
            "paper_held": None,
            "backtest_held": None,
            "l1": l1,
            "note": l1.get("note") or lines[0],
            "lines": lines,
        }

st.set_page_config(page_title="CTA Path-A Desk", layout="wide", initial_sidebar_state="expanded")


@st.cache_data(show_spinner=False)
def _cached_status():
    return registry_status_table(ROOT)


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
    pull_git = st.checkbox("同步 main 日报（fetch + 取出报告文件）", value=True, key="desk_sync_git")
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
    scored_ids = {row["id"] for row in scoreboard_rows(ROOT)}
    specs = [s for s in specs if s.id in scored_ids]

    # --- sidebar ---
    with st.sidebar:
        st.header("策略选择")
        labels = []
        id_by_label = {}
        default_sel = []
        for s in specs:
            avail = avail_map[s.id]
            mark = " ·曲线" if avail == "ready" else " ·KPI"
            label = f"{s.name}{mark}"
            labels.append(label)
            id_by_label[label] = s.id
            if avail == "ready" and s.id in ("path_a", "proxy_cwft", "benchmark"):
                default_sel.append(label)
            elif avail == "ready" and s.id.startswith("proxy_") and len(default_sel) < 4:
                default_sel.append(label)

        chosen_labels = st.multiselect("叠加对比", labels, default=default_sel)
        chosen_ids = [id_by_label[x] for x in chosen_labels]

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

    tab_compare, tab_signals, tab_chart, tab_opts, tab_seats, tab_regime, tab_decision, tab_shadow = st.tabs(
        ["概览对比", "日信号", "图表", "期权机会", "席位板块", "状态评分", "决策", "E1·情绪影子·不计分"]
    )

    # --- Tab 1: compare ---
    with tab_compare:
        render_freshness_header(ROOT, "概览对比")
        curves = {}
        kpi_rows = []
        grey_notes = []
        for sid in chosen_ids:
            spec = next(s for s in specs if s.id == sid)
            avail = avail_map[sid]
            payload = _cached_payload(sid)
            kpis = strategy_kpis(spec, ROOT)
            row = {
                "策略": spec.name,
                "状态": _status_label(avail),
                "年化/收益%": kpis.get("ret_ann_pct", kpis.get("ret_pct")),
                "夏普": kpis.get("sharpe"),
                "Calmar": kpis.get("calmar"),
                "近一周%": kpis.get("week_ret_pct"),
                "区间收益%": kpis.get("ret_pct"),
                "最大回撤%": kpis.get("max_dd_pct"),
                "毛收益%": kpis.get("gross_ret_pct"),
                "毛回撤%": kpis.get("gross_max_dd_pct"),
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
                    # Key by strategy id so display names never collide in align_curves.
                    one = df.rename(columns={eq_col: "equity"}) if eq_col != "equity" else df
                    curves[spec.name or sid] = one.copy()
            elif avail == "kpi_only":
                grey_notes.append(f"{spec.name}：KPI 跟踪（无曲线属正常，看上表数字）")
            elif avail == "placeholder":
                grey_notes.append(f"{spec.name}：占位待填")
            elif avail == "missing":
                grey_notes.append(f"{spec.name}：缺少 `{spec.curve_path}`")

        if kpi_rows:
            st.subheader("窗口 KPI / 跟踪数字")
            st.caption("有曲线与仅 KPI 都在此表；外部跟踪本来就没有权益曲线。")
            st.dataframe(pd.DataFrame(kpi_rows), width="stretch", hide_index=True)

        if grey_notes:
            with st.expander("无曲线说明（可折叠）", expanded=False):
                for n in grey_notes:
                    st.caption(n)

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
    with tab_signals:
        render_freshness_header(ROOT, "日信号")
        report = load_l1_report(ROOT)
        if not report:
            st.error("缺少 l1_report.json，请先运行 daily_update.py")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("asof", report.get("asof"))
            c2.metric("权益", f"{report.get('equity'):,.0f}" if report.get("equity") is not None else "—")
            c3.metric("入场过滤", report.get("entry_filter"))
            c4.metric("数据源", str(report.get("data_source") or "")[:24])
            q = report.get("quality") or {}
            if report.get("quality_ok") is False:
                st.error(
                    f"质量门禁未通过：{q.get('failures') or q.get('bad_codes') or '见 quality'}；"
                    "正式报告已扣留，不下单。"
                )
            elif report.get("quality_ok"):
                st.caption(f"质量门禁通过（checked={q.get('checked')}）· live_trading=否")

            from desk.sentiment_panel import render_sentiment_panel

            render_sentiment_panel(ROOT)

            from desk.premarket_compare import render_premarket_card

            render_premarket_card(ROOT)

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

            st.subheader("L1 信号板")
            sigs = pd.DataFrame(report.get("signals") or [])
            if sigs.empty:
                st.info("无信号行")
            else:
                prefer = [
                    "code",
                    "name",
                    "bucket",
                    "align",
                    "direction",
                    "lots_l1",
                    "lots_raw",
                    "selected",
                    "close",
                    "atr",
                    "r20",
                    "r60",
                    "action",
                    "seat",
                ]
                cols = [c for c in prefer if c in sigs.columns] + [
                    c for c in sigs.columns if c not in prefer
                ]
                st.dataframe(sigs[cols], width="stretch", hide_index=True)

    # --- Tab: TV-style chart ---
    with tab_chart:
        render_freshness_header(ROOT, "图表")
        render_chart_tab(ROOT)

    # --- Tab: options ---
    with tab_opts:
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
        for label, sid in (("路径A", "path_a"), ("路径A+保护期权", "path_a_opt_hedge")):
            curve = equity_curve_df(_cached_payload(sid))
            if not curve.empty:
                hedge_curves[label] = curve
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

    with tab_seats:
        render_freshness_header(ROOT, "席位板块")
        render_seat_sector(ROOT)

    with tab_regime:
        render_freshness_header(ROOT, "状态评分")
        render_regime_tab(ROOT)

    with tab_decision:
        render_freshness_header(ROOT, "决策")
        render_decision_tab(ROOT)

    with tab_shadow:
        render_freshness_header(ROOT, "E1·情绪影子·不计分")
        from desk.sentiment_history import render_sentiment_history_tab

        render_sentiment_history_tab(ROOT)


if __name__ == "__main__":
    main()
