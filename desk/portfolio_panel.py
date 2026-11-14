# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from desk.variety_labels import strategy_label, stress_label


def render_portfolio_panel(st, root: Path) -> None:
    path = root / "lab" / "research" / "portfolio" / "portfolio_risk_latest.json"
    with st.expander("组合风险影子（相关 / MRC / CVaR）", expanded=False):
        if not path.is_file():
            st.caption("尚无产物。运行：`python lab/scripts/run_portfolio_risk.py`")
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            st.caption(f"读取失败：{exc}")
            return
        st.caption("等权影子分析 · 仅研究 · 不调整正式持仓。")
        names = [strategy_label(n) for n in (payload.get("names") or [])]
        raw_names = payload.get("names") or []
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("策略数", len(names))
        c2.metric("样本日", payload.get("n_obs"))
        c3.metric("最大|相关|", payload.get("max_pairwise_corr"))
        vc = payload.get("var_cvar") or {}
        c4.metric("条件风险价值5%", vc.get("cvar"))
        corr = payload.get("corr") or []
        if corr and names:
            import pandas as pd

            st.caption("策略收益相关系数")
            st.dataframe(pd.DataFrame(corr, index=names, columns=names), width="stretch")
        if payload.get("mrc"):
            st.caption("边际风险贡献（等权）")
            st.dataframe(
                [
                    {"策略": strategy_label(n), "内部代码": n, "边际风险贡献": m}
                    for n, m in zip(raw_names, payload.get("mrc") or [])
                ],
                width="stretch",
                hide_index=True,
            )
        if payload.get("stress"):
            st.caption("情景冲击")
            stress_rows = []
            for row in payload["stress"]:
                stress_rows.append(
                    {
                        "情景": stress_label(row.get("scenario")),
                        "组合收益": row.get("port_ret"),
                        "涉及策略": "、".join(
                            strategy_label(x) for x in (row.get("names") or [])
                        ),
                    }
                )
            st.dataframe(stress_rows, width="stretch", hide_index=True)
