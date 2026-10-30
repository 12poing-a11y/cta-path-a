# -*- coding: utf-8 -*-
"""Read-only Plan A lab gate + IC summary for the research desk.

Does NOT change entry_filter, lots, or paper book. Loads
``lab/research/oos/oos_vs_path_a_latest.json`` and
``lab/research/ic/ic_groups_latest.json`` if present.
Optional button re-runs lab IC/OOS scripts (still read-only to trading).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.loaders import load_json


def _rerun_lab_reports(root: Path) -> tuple[bool, str]:
    """Recompute IC + OOS JSON under lab/research. Does not touch entry_filter."""
    scripts = [
        root / "lab" / "scripts" / "run_ic_groups.py",
        root / "lab" / "scripts" / "run_oos_vs_path_a.py",
    ]
    logs: list[str] = []
    for script in scripts:
        if not script.is_file():
            return False, f"缺少脚本 {script.name}"
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"{script.name} 失败: {exc}"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-400:]
            return False, f"{script.name} exit={proc.returncode}: {err}"
        logs.append(script.name)
    return True, "已重跑 " + " + ".join(logs)


def lab_snapshot(root: Path) -> dict[str, Any]:
    oos_path = root / "lab" / "research" / "oos" / "oos_vs_path_a_latest.json"
    ic_path = root / "lab" / "research" / "ic" / "ic_groups_latest.json"
    oos = load_json(oos_path) if oos_path.is_file() else None
    ic = load_json(ic_path) if ic_path.is_file() else None
    missing = []
    if not oos:
        missing.append("oos_vs_path_a_latest.json")
    if not ic:
        missing.append("ic_groups_latest.json")
    gates = (oos or {}).get("gates") or {}
    g_is = gates.get("is_sign") or {}
    g_prior = gates.get("prior") or {}
    any_pass = bool(g_is.get("pass") or g_prior.get("pass"))
    return {
        "ok": bool(oos),
        "missing": missing,
        "oos": oos,
        "ic": ic,
        "any_gate_pass": any_pass,
        "entry_filter_advice": (
            "可放入策略台讨论（gate 已过：风险优先或收益/回撤路径；仍需人工确认，不自动改 entry_filter）"
            if any_pass
            else "保持 Path-A entry_filter=seats（gate 未过）"
        ),
    }


def _fmt_pct(x: Any) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _ic_top_rows(ic: dict | None, *, n: int = 5) -> list[dict]:
    if not ic:
        return []
    fac = ((ic.get("out_of_sample") or {}).get("factors") or {})
    rows = []
    for name, body in fac.items():
        icir = body.get("icir_ann")
        rows.append(
            {
                "因子": name,
                "OOS_IC": body.get("ic_mean"),
                "OOS_ICIR": icir,
                "OOS五分组收益%": (body.get("quintile_ls") or {}).get("ret_pct"),
            }
        )
    rows.sort(
        key=lambda r: abs(float(r["OOS_ICIR"])) if r.get("OOS_ICIR") is not None else -1.0,
        reverse=True,
    )
    return rows[:n]


def render_lab_gate_panel(
    root: Path, *, compact: bool = False, widget_ns: str | None = None
) -> None:
    snap = lab_snapshot(root)
    # Streamlit executes every tab each rerun; callers must pass distinct widget_ns.
    key_sfx = widget_ns or ("compact" if compact else "full")
    st.markdown("**因子实验室 · Gate（只读）**")
    st.caption(
        "Plan A 长样本验货摘要。不改开仓、不改模拟仓。"
        "也可命令行：`python lab/scripts/run_ic_groups.py` 与 "
        "`python lab/scripts/run_oos_vs_path_a.py`。"
    )
    if st.button("重跑 lab IC+OOS 摘要", key=f"lab_rerun_gate__{key_sfx}"):
        with st.spinner("重跑因子实验室（数秒）…"):
            ok_run, msg = _rerun_lab_reports(root)
        if ok_run:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)
    if not snap.get("ok"):
        st.info(
            "尚未生成 lab OOS 报告（缺 "
            + "、".join(snap.get("missing") or ["产物"])
            + "）。先在仓库根目录跑 lab 脚本。"
        )
        return

    oos = snap["oos"] or {}
    meta = oos.get("meta") or {}
    win = oos.get("oos_window") or {}
    gates = oos.get("gates") or {}
    g_is = gates.get("is_sign") or {}
    g_prior = gates.get("prior") or {}
    lab_is = oos.get("lab_composite_is_sign") or {}
    proxy = oos.get("path_a_proxy_tsmom_oos") or {}
    aligned = ((oos.get("aligned_lab_vs_proxy") or {}).get("is_sign") or {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("IS符号 gate", "通过" if g_is.get("pass") else "未过")
    c2.metric("先验 gate", "通过" if g_prior.get("pass") else "未过")
    c3.metric("lab IS合成 OOS", _fmt_pct(lab_is.get("ret_pct")))
    c4.metric("Path-A 代理 OOS", _fmt_pct(proxy.get("ret_pct")))

    if snap["any_gate_pass"]:
        st.success(snap["entry_filter_advice"])
    else:
        st.warning(snap["entry_filter_advice"])

    st.caption(
        f"OOS {win.get('start') or '—'}→{win.get('end') or '—'} · "
        f"panel {meta.get('panel_sha16') or '—'} · "
        f"生成 {str(meta.get('created_at') or '')[:19] or '—'}"
    )
    try:
        from lab_signal import load_latest_pack

        edge_pack = load_latest_pack(root)
        if edge_pack.get("ok"):
            st.caption(
                f"今日 lab 边：面板 {edge_pack.get('date')} · "
                f"{edge_pack.get('n_codes')} 品种截面（逆向→决策观望，不改 seats）。"
            )
    except Exception:
        pass

    if not compact:
        if aligned.get("lab") and aligned.get("path_a_proxy_tsmom"):
            a, b = aligned["lab"], aligned["path_a_proxy_tsmom"]
            st.caption(
                f"对齐窗 {aligned.get('start')}→{aligned.get('end')}： "
                f"lab 回撤 {_fmt_pct(a.get('max_dd_pct'))} / "
                f"代理 {_fmt_pct(b.get('max_dd_pct'))}；"
                f"lab 夏普 {a.get('sharpe')} / 代理 {b.get('sharpe')}。"
            )
            bits = []
            if g_is.get("better_dd"):
                bits.append("回撤优于代理")
            if g_is.get("not_worse_ret"):
                bits.append("收益不差于代理")
            if g_is.get("strong_ret_over_dd"):
                bits.append(
                    f"收益/回撤达标 ({g_is.get('lab_ret_over_dd')}× vs 代理 {g_is.get('proxy_ret_over_dd')}×)"
                )
            if g_is.get("path"):
                bits.append(f"路径={g_is.get('path')}")
            if g_is.get("overlap_ok") is False:
                bits.append("官方短窗重叠未过")
            if bits:
                st.caption("IS符号门禁细项：" + "；".join(bits) + "。")

        contrib = oos.get("contribution") or {}
        screen = contrib.get("is_screen") or {}
        selected = screen.get("selected") or []
        loo = contrib.get("leave_one_out") or []
        loo_by = {str(r.get("factor")): r for r in loo if isinstance(r, dict)}
        if selected or screen.get("rejected"):
            st.markdown("**IS 入选与 OOS 边际贡献（只读）**")
            rows = []
            for s in selected:
                name = str(s.get("factor") or "")
                lo = loo_by.get(name) or {}
                rows.append(
                    {
                        "因子": name,
                        "IS入选": "是",
                        "符号": s.get("sign"),
                        "权重": s.get("weight"),
                        "OOSΔ收益pp": lo.get("delta_ret_pct"),
                        "OOSΔ回撤pp": lo.get("delta_max_dd_pct"),
                        "正贡献": (
                            "是"
                            if lo.get("contributes")
                            else ("否" if lo.get("ok") else "—")
                        ),
                    }
                )
            for r in screen.get("rejected") or []:
                rows.append(
                    {
                        "因子": r.get("factor"),
                        "IS入选": f"否({r.get('reason')})",
                        "符号": "—",
                        "权重": "—",
                        "OOSΔ收益pp": "—",
                        "OOSΔ回撤pp": "—",
                        "正贡献": "—",
                    }
                )
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            eq = contrib.get("equal_weight_oos") or {}
            full = contrib.get("full_oos") or {}
            st.caption(
                f"ICIR加权 OOS {_fmt_pct(full.get('ret_pct'))} / DD {_fmt_pct(full.get('max_dd_pct'))}；"
                f"等权对照 {_fmt_pct(eq.get('ret_pct'))} / DD {_fmt_pct(eq.get('max_dd_pct'))}。"
                " Δ收益>0 = 去掉该因子后变差 → 有贡献。"
            )

        ic_rows = _ic_top_rows(snap.get("ic"))
        if ic_rows:
            st.markdown("**OOS |ICIR| 靠前因子（只读）**")
            st.dataframe(pd.DataFrame(ic_rows), width="stretch", hide_index=True)

        reason = g_is.get("reason") or g_prior.get("reason")
        if reason:
            st.caption(f"门禁说明：{reason}")

        _render_today_lab_edge(root, key_sfx=key_sfx)
        _render_r2_align_paper(root)


def _render_r2_align_paper(root: Path) -> None:
    path = root / "lab" / "research" / "oos" / "r2_align_paper_latest.json"
    rep = load_json(path) if path.is_file() else None
    if not rep or not rep.get("ok"):
        st.caption(
            "尚无 R2 同向/逆向纸面对照（可跑 "
            "`python lab/scripts/run_r2_align_paper.py`）。"
        )
        return
    st.markdown("**趋势R2 × Path-A 开仓纸面对照**")
    win = rep.get("window") or {}
    buckets = rep.get("buckets") or {}
    rows = []
    for name in ("agree", "disagree", "flat", "missing"):
        b = buckets.get(name) or {}
        if not b.get("n"):
            continue
        rows.append(
            {
                "对齐": name,
                "笔数": b.get("n"),
                "胜率%": b.get("win_rate_pct"),
                "均R": b.get("mean_R"),
                "ΣR": b.get("sum_R"),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(
        f"窗 {win.get('start') or '—'}→{win.get('end') or '—'} · "
        f"Δ均R(agree−disagree)={rep.get('agree_minus_disagree_mean_R')} · "
        f"{rep.get('hint') or ''} · 不改 seats"
    )


def _render_today_lab_edge(root: Path, *, key_sfx: str = "full") -> None:
    """Show latest cross-section lab edge vs Path-A momentum direction."""
    try:
        from lab_signal import (
            lab_edge_bypass_cfg,
            lab_edge_decision,
            load_latest_pack,
            refresh_latest,
        )
    except Exception as exc:  # noqa: BLE001
        st.caption(f"实验室边模块不可用：{exc}")
        return
    uni = load_json(root / "universe.json") or {}
    cfg = lab_edge_bypass_cfg(uni.get("lab_edge_bypass"))
    if st.button("刷新今日 lab 边", key=f"lab_refresh_edge_{key_sfx}"):
        try:
            refresh_latest(root=root, cfg=cfg)
            st.success("已写入 lab/research/signals/latest.json")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
    pack = load_latest_pack(root)
    st.markdown("**今日实验室边（软旁路）**")
    if not cfg.get("enabled"):
        st.caption("lab_edge_bypass 关闭。")
        return
    if not pack.get("ok"):
        st.caption(f"无可用截面：{pack.get('reason') or '—'}（缺数放行）。")
        return
    report = load_json(root / "l1_report.json") or {}
    sig_dir = {
        str(s.get("code") or "").upper(): s.get("direction")
        for s in (report.get("signals") or [])
        if s.get("code")
    }
    rows = []
    for code in sorted(pack.get("percentiles") or {}):
        want = sig_dir.get(code)
        if want not in ("多", "空"):
            # fallback: score sign as hypothetical
            sc = float((pack.get("scores") or {}).get(code) or 0.0)
            want = "多" if sc >= 0 else "空"
            src = "分位假设"
        else:
            src = "日报方向"
        edge = lab_edge_decision(want, code, pack, cfg)
        rows.append(
            {
                "品种": code,
                "方向": want,
                "来源": src,
                "分位": edge.get("percentile"),
                "得分": edge.get("score"),
                "标签": edge.get("label"),
                "观望?": "是" if edge.get("force_observe") else "否",
            }
        )
    st.caption(
        f"面板日 {pack.get('date')} · 品种 {pack.get('n_codes')} · "
        f"逆向阈值 {cfg.get('disagree_frac')} · entry_filter 仍为 seats"
    )
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
