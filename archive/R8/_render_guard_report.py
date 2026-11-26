# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

R8 = Path(__file__).resolve().parent
G = json.loads((R8 / "guard_sensitivity.json").read_text(encoding="utf-8"))
P = json.loads((R8 / "guard_vs_local.json").read_text(encoding="utf-8"))
D = json.loads((R8 / "guard_part2_diag.json").read_text(encoding="utf-8"))
T = G["tiers"]
L = []
w = L.append
w("# R8 跟进：成交量守卫阈值敏感性 + 加守卫后的官方对本地比较（只读，未跑策略，不计入 DSR）")
w("")
w("> 分支 `r8-equity-filter`（本地）。**触发了你定的停止条件（§4），已停下**：未提交附录 1、未实现入口与 C、未跑长样本。")
w("")
w("## 1. 守卫与复刻校验")
w("")
w("- 守卫：官方数据路径上，候选合约当日官方 volume < 当日所有候选最大 volume × 阈值 → 不能当主力；被拦下后剩余候选仍走引擎的价格匹配（`match_main_contract`），匹配不上则按未识别处理、沿用前一日主力、不换月。")
w("- 分析脚本 `guard_sensitivity.py` 自带一份主力图循环（日历候选 + 价格匹配 + 守卫），**阈值 0% 时与引擎 `build_main_map` 逐日比对 0 处不一致**（27 个品种 2015-06~2025-12 全部日期），所以敏感性数据用的是引擎规则本身。")
w("- 口径：窗口 2016-01-04~2025-12-31（晚上市品种按上市+60 根起点，FU 自 2018-10-16）；参考最大成交量取该品种当日全部官方候选。基线换月事件 {} 次（我上一份报告写 1256，多出的 1 次落在晚上市品种预热期内，本次按起点规则去掉）。".format(T["0%"]["roll_events"]))
w("")
w("## 2. 阈值敏感性（1% / 5% / 10%，基线 0%）")
w("")
w("| 阈值 | 换月事件 | 未识别品种日 | 三日内来回换月 | 其中新主力成交量 <5% | 其中 ≥5% | 基线\"正常换月\"未复现 | 基线事件未复现（全部类型） |")
w("|---|---|---|---|---|---|---|---|")
for k in ("0%", "1%", "5%", "10%"):
    t = T[k]
    w(f"| {k} | {t['roll_events']} | {t['unidentified_symbol_days']} | {t['immediate_reversals']} | {t['reversals_new_main_lt5pct']} | {t['reversals_new_main_ge5pct']} | {t['normal_rolls_blocked_or_delayed']} | {t['baseline_events_not_reproduced_all_kinds']} |")
w("")
w("- 分类口径：新主力 / 旧主力 = 换月日当日官方成交量之比，阈值固定 5%，三档同一口径。")
w(f"- **5% 档：<5% 的来回换月 35 → 0**；剩下 {T['5%']['reversals_new_main_ge5pct']} 次都是新主力成交量 ≥ 旧主力 5% 的同量级来回（基线就有的那 35 次，守卫不处理，如你所定）。1% 档剩 10 次 <5%；10% 档总数 27（>=10% 的同量级抖动也被部分拦下）。")
w(f"- 守卫的代价：未识别品种日 135 → {T['1%']['unidentified_symbol_days']}（1%）/ {T['5%']['unidentified_symbol_days']}（5%）/ {T['10%']['unidentified_symbol_days']}（10%）；5% 档新增 {T['5%']['unidentified_symbol_days']-135} 个按沿用处理的品种日。")
w("")
w("### 被拦下或推迟的\"正常换月\"（基线中 3 日内未换回的换月，在守卫下没有在同一天以同样的合约对出现）")
w("")
w("三档**完全相同**，共 6 条，是 3 个两跳链：基线先换到一个极薄的合约、次日再换到真正的新主力；守卫只是跳过了薄合约这一跳，**真正换到新主力的日期没有变**：")
w("")
w("| 品种 | 基线第 1 跳 | 新合约当日成交 / 旧主力 / 当日最大 | 基线第 2 跳 | 守卫下的结果 |")
w("|---|---|---|---|---|")
rows = G["details"]["5%"]["normal_blocked_or_delayed"]
byk = {}
for r in rows:
    byk.setdefault(r["symbol"], []).append(r)
for s, rr in byk.items():
    a, b = rr[0], rr[1]
    g = a["guarded_rolls_within_5_days"][0]
    w(f"| {s} | {a['date']} {a['roll']} | {a['new_main_vol']:.0f} / {a['old_main_vol']:.0f} / {a['max_cand_vol_that_day']:.0f} | {b['date']} {b['roll']} | {g[0]} {g[1]}->{g[2]}（同一天到达同一新主力） |")
w("")
w("- **按\"被推迟\"的字面意思（同一对合约晚几天才换）：0 条。**按\"未复现\"（路径不同）：6 条，且 1%/5%/10% 三档都是这 6 条，档间差 0。")
w(f"- 另一种读法（把所有被拦下的基线换月事件算上，含被消掉的来回换月）：{T['1%']['baseline_events_not_reproduced_all_kinds']} / {T['5%']['baseline_events_not_reproduced_all_kinds']} / {T['10%']['baseline_events_not_reproduced_all_kinds']}，档间差 {T['10%']['baseline_events_not_reproduced_all_kinds']-T['1%']['baseline_events_not_reproduced_all_kinds']}。这一差值主要来自被拦下的来回换月本身，不是正常换月。")
w("")
w("## 3. 加守卫后重做 2024-09~2025-12 官方对本地主力比较")
w("")
w("官方侧加 5% 守卫、本地侧保持默认（无守卫），官方数据限制在本地存储有的（合约，日期）上。")
a = P["official guarded 5% on local set"]
w(f"- 结果：{a['totals']['symbol_days']} 个品种日，主力不同 **{a['totals']['main_differs_days']}** 个品种日；换月事件官方侧 {a['totals']['roll_events_official']}、本地侧 {a['totals']['roll_events_local']}。")
snap = [r for r in a["main_differs"] if r[1] == "2024-09-25"]
non = [r for r in a["main_differs"] if r[1] != "2024-09-25"]
w(f"- 其中快照日 2024-09-25 共 {len(snap)} 个品种日（与上一份报告一致的快照机制）；**快照日以外 {len(non)} 个品种日**（AL 21 个、CU 1 个），逐条：")
w("")
w("| 品种 | 日期 | 官方侧(守卫) | 本地侧 | 官方当日成交最大的合约（成交） | 该合约在本地存储中？ | 本地侧主力当日成交 |")
w("|---|---|---|---|---|---|---|")
for c, d, ao, bo, top, tv, intl, lv in D["a_non_snapshot"]:
    w(f"| {c} | {d} | {ao or '未识别'} | {bo or '未识别'} | {top}（{tv:.0f}） | {'是' if intl else '**否**'} | {'-' if lv is None else f'{lv:.0f}'} |")
w("")
w("**原因（22 条同一个）**：本地存储没有当日成交最大的那个合约（AL2501/2503/2504/2505/2506、CU2410），本地侧在缺少真主力的候选集里，只能匹配到成交仅几十~几百手的远月合约（本地侧不加守卫）；官方侧加守卫后，多数薄合约被拦下变成未识别，少数匹配到另一个薄合约（两侧都在残缺候选集里，各自落在不同的薄合约上）。这是**覆盖缺口 + 守卫只在官方侧**造成的比较伪影，不是价格、快照或 volume 数值问题。")
w("")
w("补充（只在\"本地存储包含当日成交最大合约\"的日子比较，共 {} 个品种日，另 {} 个品种日因本地缺该合约被排除）：官方加守卫 vs 本地默认，**15 个不一致全部是 2024-09-25 快照日**；不加守卫同样 15 个，全在 2024-09-25（守卫只改变了其中个别品种官方侧的取值，如 BU、M 由合约号变为未识别）。".format(7605, 1116))
w("")
w("## 4. 停止条件判定")
w("")
w("- ① 5% 档\"被推迟的正常换月\"：按字面（同对合约延后）= **0**；但有 6 条\"未复现\"（3 个两跳链，薄合约一跳被跳过，到达日期不变）。我的判断是未触发，但这是解读，**请你确认**。")
w("- ② 三档之间被拦下的换月差：正常换月 0（6/6/6）；全部类型 36。按\"正常换月\"读法未触发，按\"全部类型\"读法触发。")
w("- ③ **快照日以外的差异：按你指定的比较口径（§3 第一段）出现 22 条，已触发**，原因是本地存储缺当日最大成交合约，不是快照日。我已停下。")
w("")
w("## 5. 建议与需要你确认")
w("")
w("1. 确认 ③ 的原因判断：22 条差异来自\"本地缺真主力 + 守卫只在官方侧\"，在本地覆盖了当日最大成交合约的日子里，官方加守卫与本地默认只剩快照日差异。")
w("2. 确认 ① 的解读：6 条未复现是两跳链，不算\"被推迟的正常换月\"。")
w("3. 三项都确认后，我按顺序继续：提交附录 1 → 实现入口和 C → 回归测试 → 跑长样本。附录 1 将登记你列的 6 项，并补充本报告的新增披露：守卫新增 36 个未识别品种日（135→171）、35 次同量级来回换月的次数与换月成本、基线换月事件口径 1255。")
(R8 / "GUARD_SENSITIVITY_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("written", len(L))
