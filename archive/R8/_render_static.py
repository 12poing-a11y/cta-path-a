# -*- coding: utf-8 -*-
"""Render archive/R8/static_sizing.json into the tables of static_sizing.md (numbers only, no prose)."""
import json
from pathlib import Path

R = Path(__file__).resolve().parent
d = json.loads((R / "static_sizing.json").read_text(encoding="utf-8"))
a = d["a_per_symbol"]


def f(x, nd=1):
    return "-" if x is None else f"{x:,.{nd}f}"


rows = []
rows.append("| 品种 | 板块 | 乘数 | 1手名义 中位/最大 (元) | 1手名义/200k 中位/最大 % | 1手名义/1M 中位 % | 1手止损风险 中位/最大 (元) | 风险/200k 中位/最大 % | 风险/1M 中位 % | 最低本金(≥1手 且 名义≤帽一半) 中位 / P90 / 最大 (元) | 谁卡着 | 1M 下可开天数占比 | 1M 下 1手名义>帽 占比 |")
rows.append("|" + "---|" * 13)
for c, v in sorted(a.items(), key=lambda kv: kv[1]["min_equity_yuan"]["median"]):
    me = v["min_equity_yuan"]
    rows.append(
        f"| {c} | {v['bucket']} | {v['mult']:g} | {f(v['notional_1lot_yuan']['median'],0)} / {f(v['notional_1lot_yuan']['max'],0)} "
        f"| {f(v['notional_pct_of_200k']['median'])} / {f(v['notional_pct_of_200k']['max'])} | {f(v['notional_pct_of_1m']['median'])} "
        f"| {f(v['risk_1lot_yuan']['median'],0)} / {f(v['risk_1lot_yuan']['max'],0)} "
        f"| {f(v['risk_pct_of_200k']['median'],2)} / {f(v['risk_pct_of_200k']['max'],2)} | {f(v['risk_pct_of_1m']['median'],2)} "
        f"| {f(me['median'],0)} / {f(me['p90'],0)} / {f(me['max'],0)} | {v['binding_on_median_day']} "
        f"| {v['share_days_openable']['1000k']:.0%} | {v['share_days_1lot_notional_gt_full_cap']['1000k']:.0%} |"
    )
tab_a = "\n".join(rows)

rows = ["| 品种 | " + " | ".join(["100k", "200k", "300k", "500k", "1000k"]) + " |", "|---|---|---|---|---|---|"]
for c, v in sorted(a.items(), key=lambda kv: kv[1]["min_equity_yuan"]["median"]):
    s = v["share_days_openable"]
    rows.append(f"| {c} | " + " | ".join(f"{s[k]:.0%}" for k in ("100k", "200k", "300k", "500k", "1000k")) + " |")
tab_open = "\n".join(rows)

b, c = d["b_floor"], d["c_skips_base"]
rows = ["| 类别 | 信号日数 | 主要品种 |", "|---|---|---|"]
names = {
    "lots0": "算出 0 手（风险预算买不起 1 手）",
    "gross_cap_scaled_to_0": "名义帽缩到 0（总帽−已持仓后的额度，统一缩放后 floor 为 0，且未被 R4b 补回）",
    "positions_full(N cap, slots_left>0)": "持仓数已满（当日候选多于空位，被 N 帽挡掉）",
    "bucket_full": "板块已满（同板块已有持仓或同日更强者占位）",
    "atr_risk_cap_scaled_to_0": "ATR 组合风险帽缩到 0",
    "hard_trim_or_refill_dropped": "硬裁剪/回填后落选",
    "weak_momentum(caps)": "帽内动量过滤",
}
for k, n in c["categories"].items():
    top = ", ".join(f"{x} {y}" for x, y in list(c["by_code"][k].items())[:6])
    rows.append(f"| {names.get(k, k)} | {n} | {top} |")
tab_c = "\n".join(rows)

(R / "_static_tables.md").write_text(
    "<!--TAB_A-->\n" + tab_a + "\n<!--TAB_OPEN-->\n" + tab_open + "\n<!--TAB_C-->\n" + tab_c + "\n", encoding="utf-8")
tpl = (R / "_static_template.md").read_text(encoding="utf-8")
(R / "static_sizing.md").write_text(
    tpl.replace("{{TAB_A}}", tab_a).replace("{{TAB_OPEN}}", tab_open).replace("{{TAB_C}}", tab_c), encoding="utf-8")
print("written static_sizing.md", len(tpl))
