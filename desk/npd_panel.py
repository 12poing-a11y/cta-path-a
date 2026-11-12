# -*- coding: utf-8 -*-
"""Cotton NPD — entry-day shadow reminders only (research desk).

Shows a banner / table solely when the desk asof is an NPD entry day
(first session after event publication calendar date). Never sizes Path-A
lots, never writes formal signals, never uses divergence labels as inputs.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

LABEL = "E1·NPD影子·不计分"


def _desk_asof(root: Path) -> str:
    try:
        from market_data import latest_expected_session_date

        return latest_expected_session_date().isoformat()
    except Exception:  # noqa: BLE001
        pass
    try:
        import json

        rep = json.loads((Path(root) / "l1_report.json").read_text(encoding="utf-8"))
        raw = str(rep.get("asof") or "")
        if len(raw) == 8 and raw.isdigit():
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        if len(raw) >= 10:
            return raw[:10]
    except Exception:  # noqa: BLE001
        pass
    return date.today().isoformat()


def load_npd_reminders(root: Path, asof: str | None = None) -> dict[str, Any]:
    from cotton_npd import shadow_reminders_for_root

    day = asof or _desk_asof(root)
    return shadow_reminders_for_root(root, asof=day)


def render_npd_event_day_banner(root: Path, asof: str | None = None) -> dict[str, Any]:
    """Compact banner for other desk pages — silent when not an entry day."""
    import streamlit as st

    pack = load_npd_reminders(root, asof=asof)
    if not pack.get("is_entry_day"):
        return pack
    lines = []
    for row in pack.get("reminders") or []:
        lines.append(
            f"{row.get('lean')} · {row.get('category') or '事件'} · "
            f"{row.get('headline') or row.get('event_id')} "
            f"(进入开盘={row.get('entry_open') or '—'})"
        )
    st.info(
        f"【{LABEL}】今日为棉花 NPD **进入日**（影子提醒，不计分 / 不下单）\n\n"
        + "\n\n".join(f"- {x}" for x in lines)
    )
    return pack


def render_npd_panel(root: Path, asof: str | None = None) -> dict[str, Any]:
    """Dedicated research-desk page for NPD entry-day shadow reminders."""
    import pandas as pd
    import streamlit as st

    st.caption(
        f"【{LABEL}】新闻–价格背离（NPD）只在**进入日**弹出影子提醒："
        "发布日（北京时间日历日）之后第一个交易日开盘口径。"
        "不进 Path-A 评分、不改仓、不下单；背离标签是事后结果，不作输入。"
        "收表须官方原文链接 + 原文摘录 + 发布时间，否则标待核。"
    )
    pack = load_npd_reminders(root, asof=asof)
    asof_s = pack.get("asof") or _desk_asof(root)
    st.markdown(f"**对照日** `{asof_s}` · 进入规则：`{pack.get('entry_rule') or '—'}`")

    with st.expander("中国六类盯盘 + 收表规则", expanded=False):
        watch = pack.get("cn_watchlist") or {}
        if watch:
            st.dataframe(
                pd.DataFrame(
                    [{"代码": k, "含义": v} for k, v in watch.items()]
                ),
                width="stretch",
                hide_index=True,
            )
        st.markdown(
            "- **中国六类**：国储轮入/出、滑准税配额、CASDE、统计局产量、新疆目标价格、海关进口月报\n"
            "- **USDA**：WASDE 等官方发布\n"
            "- **accepted**：官方链接 + 原文摘录 + 可解析发布时间\n"
            "- **待核**：缺出处/时间，留表但不进统计、不弹进入日提醒\n"
            "- 出结果时分开：**中国 / USDA / 合并**，看郑棉对哪边更敏感"
        )

    by_fam = pack.get("by_family") or {}
    if by_fam:
        sens_rows = []
        for key, label in (("CN", "中国"), ("USDA", "USDA"), ("combined", "合并")):
            block = by_fam.get(key) or {}
            h1 = (block.get("horizons") or {}).get("1") or {}
            sens_rows.append(
                {
                    "样本": label,
                    "事件数": block.get("event_count"),
                    "1日N": h1.get("n"),
                    "1日顺消息胜率": (
                        None
                        if h1.get("news_direction_win_rate") is None
                        else round(100.0 * float(h1["news_direction_win_rate"]), 1)
                    ),
                    "1日方向均收益%": (
                        None
                        if h1.get("directional_mean") is None
                        else round(100.0 * float(h1["directional_mean"]), 3)
                    ),
                }
            )
        st.markdown("**敏感性快览（accepted 样本 · 1 日）**")
        st.dataframe(pd.DataFrame(sens_rows), width="stretch", hide_index=True)
        if pack.get("pending_count"):
            st.caption(f"待核事件 {pack.get('pending_count')} 条（未计入上表）。")

    if pack.get("error"):
        st.warning(f"NPD 输入未就绪：{pack['error']}")
        return pack
    if pack.get("note") and not pack.get("is_entry_day"):
        st.caption(pack["note"])

    if not pack.get("is_entry_day"):
        st.success("今日非 NPD 进入日 — 无影子提醒（静默）。")
        with st.expander("如何加入事件", expanded=False):
            st.markdown(
                "编辑 `data/cotton/cotton_events.csv`：\n"
                "`event_id,published_at,family,category,headline,score,"
                "official_url,official_excerpt,status`\n\n"
                "中国 `category` 用 `CN_RESERVE` / `CN_SLIDING_QUOTA` / `CN_CASDE` / "
                "`CN_NBS_OUTPUT` / `CN_XJ_TARGET_PRICE` / `CN_CUSTOMS_IMPORT`；"
                "USDA 用 `USDA_WASDE` 等。`score` −3…+3（0=中性）。"
                "仅 **accepted** 且对照日=进入日 时提醒。"
            )
        return pack

    st.warning(
        f"进入日影子提醒 ×{pack.get('n')} "
        f"（已评分 {pack.get('n_scored')}）— 仅研究观察。"
    )
    rows = pack.get("reminders") or []
    table = [
        {
            "族": r.get("family"),
            "偏向": r.get("lean"),
            "评分": r.get("score"),
            "类别": r.get("category"),
            "标题": r.get("headline"),
            "发布日": r.get("event_date"),
            "进入日": r.get("entry_date"),
            "进入开盘": r.get("entry_open"),
            "事件前5日%": (
                None
                if r.get("pre_5d") is None
                else round(100.0 * float(r["pre_5d"]), 2)
            ),
            "官方链接": r.get("official_url") or r.get("source"),
        }
        for r in rows
    ]
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
    st.caption(
        "完整中国/USDA/合并统计：`python cotton_npd.py --bars … --events …`；"
        "本页不展示可执行边，也不把背离当信号。"
    )
    return pack
