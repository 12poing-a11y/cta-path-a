# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from desk.variety_labels import (
    backend_label,
    error_label,
    feature_label,
    p4_task_label,
    variety_label,
)


def render_ml_panel(st, root: Path) -> None:
    path = root / "lab" / "research" / "ml" / "p4_light_latest.json"
    st.caption(
        "P4 轻量（LightGBM）：LSP假突破反转 / 趋势失效 / 突破延续。"
        "**仅研究**，不改 Path-A 入场。"
    )
    if not path.is_file():
        st.info("尚无产物。运行：`python lab/scripts/run_p4_light.py`")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        st.caption(f"读取失败：{exc}")
        return

    code = str(payload.get("symbol") or "CF").upper()
    contract = str(payload.get("contract") or "") or None
    variety = variety_label(root, code, contract=contract, with_bucket=True)
    st.markdown(f"**训练品种：{variety}**")
    st.caption(
        f"品种代码={code} · 合约={contract or '—'} · "
        f"状态={'研究' if payload.get('status') == 'Research' else payload.get('status')} · 不下单"
    )

    counts = payload.get("sample_counts") or {}
    st.dataframe(
        [
            {"项目": "LSP事件", "数量": counts.get("lsp_events")},
            {"项目": "LSP样本行", "数量": counts.get("lsp_rows")},
            {"项目": "趋势失效样本", "数量": counts.get("trend_rows")},
            {"项目": "突破延续样本", "数量": counts.get("breakout_rows")},
            {"项目": "日线根数", "数量": counts.get("daily_bars")},
        ],
        width="stretch",
        hide_index=True,
    )

    tasks = payload.get("tasks") or {}
    rows = []
    for name, t in tasks.items():
        oos = (t or {}).get("oos") or {}
        status = (
            "可用"
            if (t or {}).get("ok")
            else error_label((t or {}).get("error") or "失败")
        )
        rows.append(
            {
                "品种": variety,
                "任务": p4_task_label(name),
                "模型": backend_label((t or {}).get("backend") or ""),
                "样本数": (t or {}).get("n"),
                "样本外AUC": oos.get("auc"),
                "样本外F1": oos.get("f1"),
                "样本外准确率": oos.get("accuracy"),
                "正样本率": oos.get("pos_rate"),
                "状态": status,
            }
        )
    st.subheader("任务表现（样本外）")
    st.dataframe(rows, width="stretch", hide_index=True)

    for name, t in tasks.items():
        if not (t or {}).get("ok"):
            continue
        title = f"{variety} · {p4_task_label(name)} · 特征重要性"
        with st.expander(title, expanded=False):
            imp = (t or {}).get("importance_top") or []
            st.dataframe(
                [
                    {
                        "品种": variety,
                        "特征": feature_label(r.get("feature")),
                        "重要性": r.get("importance"),
                        "原字段": r.get("feature"),
                    }
                    for r in imp
                ],
                width="stretch",
                hide_index=True,
            )
            win = (t or {}).get("oos_window") or {}
            st.caption(
                f"样本外窗口：{win.get('start') or '—'} → {win.get('end') or '—'}"
            )
