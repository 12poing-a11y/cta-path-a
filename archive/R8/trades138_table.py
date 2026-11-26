# -*- coding: utf-8 -*-
"""Render ATTRIB/trades138.json -> TRADES138_LIST.md (one line per trade that only the official/main/full cell took)."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
o = json.loads((HERE / "ATTRIB" / "trades138.json").read_text(encoding="utf-8"))
WHERE = {
    "fill_time_quality": "成交时质量门（delivery 标记）拦下",
    "caps:not_selected": "组合帽：有候选但未入选",
    "not_evaluated": "未评估（该品种已持仓）",
    "no_free_slot": "无空仓位（满仓日）",
}
lines = ["# 138 笔核查：只在「官方 / 主力开盘 / 完整」(B) 出现、未在「本地 / 日历前月 / 完整」(A) 出现的交易", "",
         "只读；不比较收益、不调参、不计 DSR。B=138 笔（含窗口末 1 笔未平仓，共 139 行）；A=99 笔（共 100 行）；共同 71 笔；只在 B 68 笔；只在 A 29 笔。", "",
         "列：# | 品种 | 方向 | 信号日 → 入场日 | A 中被哪条拦下 | A 的具体情形 | B 为什么没拦 |", "|---|---|---|---|---|---|---|"]
for i, r in enumerate(o["rows"], 1):
    a = r["A"]
    why_b = "—"
    if a["where"] == "fill_time_quality":
        fl = a.get("fill_flags") or {}
        kind = "5 个交易日禁入窗口" if fl.get("delivery_restricted") else "6–10 个交易日临近交割（near_delivery）"
        why_b = (f"B 在主力合约 {r['B']['main_contract_on_fill_day']} 上成交，距其最后交易日 {r['B']['sessions_to_last_trade']} 个交易日，不在窗口；"
                 f"B 的行情条上没有 delivery 标记（未做日历前月标记）")
        detail = f"日历前月合约处于{kind}"
    elif a["where"] == "not_evaluated":
        detail, why_b = a["detail"], "B 此时未持有该品种（路径不同）"
    elif a["where"] == "no_free_slot":
        detail, why_b = a["detail"], "B 此时有空仓位（路径不同）"
    else:
        detail, why_b = a["detail"][:120], "B 的同日候选/持仓不同，该品种入选（路径不同）"
    seat = f"{r['B']['seat_label']}" + ("（席位数据不足，席位过滤被跳过）" if r["B"]["seat_short"] else "")
    lines.append(f"| {i} | {r['code']} | {r['dir']} | {r['signal_day']} → {r['entry_date']} | {WHERE.get(a['where'], a['where'])} | {detail} | {why_b}；B 的席位：{seat}；升贴水：{r['B']['carry']} |")
(HERE / "TRADES138_LIST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(len(o["rows"]))
