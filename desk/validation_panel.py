# -*- coding: utf-8 -*-
"""Overview: Path-A validation + quality/cost contrast (read-only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_bt(root: Path) -> dict[str, Any]:
    path = root / "historical_backtest_latest.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def render_validation_panel(st, root: Path) -> None:
    bt = _load_bt(root)
    if not bt:
        return
    with st.expander("研究验证 / 数据质量（Path-A 最新回测）", expanded=False):
        st.caption(
            "PSR/DSR/PBO 与可交易性闸门为研究指标；**不会**自动改正式参数。"
            " PBO 需多策略试验矩阵；单曲线时仅提示缺矩阵。"
        )
        scorecard = root / "lab" / "research" / "validation" / "formal_scorecard_latest.json"
        if scorecard.is_file():
            try:
                sc = json.loads(scorecard.read_text(encoding="utf-8"))
                d = sc.get("deltas") or {}
                st.caption("A1 正式成绩并列（README旧声称 / 归档BT / 本次重跑）")
                st.dataframe(
                    [
                        {
                            "口径": "README旧声称",
                            "净收益%": (d.get("ret_pct") or {}).get("readme"),
                            "回撤%": (d.get("max_dd_pct") or {}).get("readme"),
                            "PBO": "—",
                        },
                        {
                            "口径": "归档BT(前)",
                            "净收益%": (d.get("ret_pct") or {}).get("bt_before"),
                            "回撤%": (d.get("max_dd_pct") or {}).get("bt_before"),
                            "PBO": (d.get("pbo") or {}).get("before"),
                        },
                        {
                            "口径": "本次正式重跑",
                            "净收益%": (d.get("ret_pct") or {}).get("bt_after"),
                            "回撤%": (d.get("max_dd_pct") or {}).get("bt_after"),
                            "PBO": (d.get("pbo") or {}).get("after"),
                        },
                    ],
                    width="stretch",
                    hide_index=True,
                )
            except Exception as exc:  # noqa: BLE001
                st.caption(f"成绩卡读取失败：{exc}")
        v = bt.get("validation") or {}
        moments = v.get("moments") or {}
        psr = (v.get("psr") or {}).get("psr")
        dsr = (v.get("dsr") or {}).get("dsr")
        pbo = v.get("pbo") or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("夏普(年化估)", moments.get("sharpe"))
        c2.metric("PSR", None if psr is None else round(float(psr), 3))
        c3.metric("DSR", None if dsr is None else round(float(dsr), 3))
        c4.metric(
            "PBO",
            None if pbo.get("pbo") is None else round(float(pbo["pbo"]), 3),
            help=str(pbo.get("error") or pbo.get("note") or ""),
        )
        if (v.get("pbo_source") or pbo.get("ok")) and pbo.get("pbo") is not None:
            st.caption(
                f"PBO 来源：{v.get('pbo_source') or 'validation'} · "
                f"T×K={((v.get('pbo_matrix_meta') or {}).get('n_obs'))}×"
                f"{((v.get('pbo_matrix_meta') or {}).get('n_trials'))}"
            )
        elif pbo.get("error") == "trial_matrix_required":
            st.caption("尚无试验矩阵。仓库根目录运行：`python lab/scripts/run_pbo_path_a.py`")
        qb = bt.get("quality_blocks") or {}
        if qb:
            from desk.variety_labels import quality_block_label

            st.caption("开仓质量拦截计数")
            st.dataframe(
                [
                    {"拦截原因": quality_block_label(k), "次数": v, "原键": k}
                    for k, v in qb.items()
                ],
                width="stretch",
                hide_index=True,
            )
        contrast = bt.get("cost_scenario_contrast") or {}
        rows = (contrast.get("rows") or {}) if isinstance(contrast, dict) else {}
        if rows:
            _cost_zh = {
                "Base": "基准成本",
                "Stress": "压力成本",
                "Extreme": "极端成本",
                "base": "基准成本",
                "stress": "压力成本",
                "extreme": "极端成本",
            }
            st.caption("成本情景对照（正式 KPI = 基准成本）")
            table = []
            for name, row in rows.items():
                if not isinstance(row, dict):
                    continue
                table.append(
                    {
                        "情景": _cost_zh.get(str(name), name),
                        "收益%": row.get("ret_pct"),
                        "回撤%": row.get("max_dd_pct"),
                        "成本(元)": row.get("cost_yuan"),
                        "滑点跳": row.get("slippage_ticks"),
                        "成交笔数": row.get("closed_trades"),
                    }
                )
            if table:
                st.dataframe(table, width="stretch", hide_index=True)
        cfg = bt.get("config_version") or {}
        if cfg:
            st.caption(
                f"配置版本 git={cfg.get('git_commit')} · "
                f"rules={(cfg.get('execution_rules_sha256') or '')[:12]}…"
            )
