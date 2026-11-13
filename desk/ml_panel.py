# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


def render_ml_panel(st, root: Path) -> None:
    path = root / "lab" / "research" / "ml" / "p4_light_latest.json"
    st.caption(
        "P4 轻量（LightGBM）：LSP 反转 / 趋势失效 / 突破延续。"
        "**Research only**，不改 Path-A 入场。"
    )
    if not path.is_file():
        st.info("尚无产物。运行：`python lab/scripts/run_p4_light.py`")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        st.caption(f"读取失败：{exc}")
        return
    st.write("样本量", payload.get("sample_counts") or {})
    tasks = payload.get("tasks") or {}
    rows = []
    for name, t in tasks.items():
        oos = (t or {}).get("oos") or {}
        rows.append(
            {
                "任务": name,
                "后端": (t or {}).get("backend"),
                "N": (t or {}).get("n"),
                "OOS AUC": oos.get("auc"),
                "OOS F1": oos.get("f1"),
                "OOS Acc": oos.get("accuracy"),
                "正样本率": oos.get("pos_rate"),
                "状态": "ok" if (t or {}).get("ok") else (t or {}).get("error"),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)
    for name, t in tasks.items():
        if not (t or {}).get("ok"):
            continue
        with st.expander(f"{name} · 特征重要性", expanded=False):
            st.dataframe((t or {}).get("importance_top") or [], width="stretch", hide_index=True)
            st.caption(f"OOS 窗 {(t or {}).get('oos_window')}")
