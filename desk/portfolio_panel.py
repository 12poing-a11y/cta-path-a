# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


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
        st.caption(payload.get("note") or "Research / Shadow only.")
        names = payload.get("names") or []
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("策略数", len(names))
        c2.metric("样本日", payload.get("n_obs"))
        c3.metric("最大|相关|", payload.get("max_pairwise_corr"))
        vc = payload.get("var_cvar") or {}
        c4.metric("CVaR 5%", vc.get("cvar"))
        corr = payload.get("corr") or []
        if corr and names:
            import pandas as pd

            st.dataframe(pd.DataFrame(corr, index=names, columns=names), width="stretch")
        if payload.get("mrc"):
            st.caption("边际风险贡献（等权）")
            st.json(dict(zip(names, payload.get("mrc") or [])))
        if payload.get("stress"):
            st.caption("情景冲击")
            st.dataframe(payload["stress"], width="stretch", hide_index=True)
