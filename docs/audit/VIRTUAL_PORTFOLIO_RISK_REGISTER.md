# CTA Virtual Portfolio — Phase 0 风险登记册

**配套**：`VIRTUAL_PORTFOLIO_AUDIT.md`  
**日期**：2026-11-23  
**等级**：P0 阻断隔离 / P1 高 / P2 中 / P3 低  
**处置**：本阶段只登记；修复须在确认开刀后单独进行。

---

## P0 — 隔离与污染（必须先挡）

| ID | 风险 | 触发场景 | 缓解（Phase 1 设计） |
|----|------|----------|---------------------|
| VP-R01 | 误调 `paper_book.refresh_paper_book` | Desk 按钮复用 / 共享 helper | `guard` 禁止 import 写入路径；CI grep；独立面板 |
| VP-R02 | 改写 `l1_report*` / 信号旁路 | 为「方便」改 daily_update | 适配器只读 JSON；禁止 import `daily_update` |
| VP-R03 | 脏树放宽导致正式写盘失控 | 改 `rule_lock` 忽略规则 | VP 状态落 `data/`（已在 ignore 前缀）；不改 rule_lock |
| VP-R04 | 席位 loader 写 `.cache/member` | 调用 `load_member_seats` | cache-only 适配器；缺文件 → UNKNOWN |
| VP-R05 | 模拟业绩混入正式 KPI | 挂到 `desk/strategies/extra` 或 shadow_perf schema | 独立目录；不入正式候选摄入 |

---

## P1 — 口径与验收错误

| ID | 风险 | 说明 | 缓解 |
|----|------|------|------|
| VP-R10 | 用 paper PnL 验收 VP | paper=收盘无成本；正式=next_open+成本 | 文档强制分离；Dashboard 双栏标注口径 |
| VP-R11 | 跟错成交时序 | 信号日收盘 vs 次日开盘混用 | `fill_policy` 字段 + 单测 |
| VP-R12 | history 落后 asof | 盯市/诊断用过期 bar | 优先 sina 日缓存；标记 STALE |
| VP-R13 | 冻结 sentiment latest 当真源 | 日更只写 shadow | 适配器优先 shadow |
| VP-R14 | vol 仅 7 品种当全市场 | 误信波动信号 | 非覆盖品种强制 UNKNOWN |

---

## P1 — 现有系统异常（不修，但影响对照）

| ID | 观察 | 影响 VP |
|----|------|---------|
| VP-R20 | Palm `P` 疑似错过纸面止盈（11-18） | paper 对照不可信为「策略真值」 |
| VP-R21 | `equity_state.json` 无写入点 / 与 paper 不一致 | 勿读作账户权益 |
| VP-R22 | 席位缺数 fail-open（审计 BT-03） | 诊断须暴露「无席位证据」 |
| VP-R23 | paper 与正式 BT 长期分叉（PB-03） | VP 应选一侧并写清，推荐正式口径 |

---

## P2 — 能力缺口

| ID | 风险 | 阶段 |
|----|------|------|
| VP-R30 | 无保证金真源 → 杠杆失真 | Phase 1 静态表；标注假设 |
| VP-R31 | 无平今/涨跌停 → 成交过于乐观 | Phase 1–3 |
| VP-R32 | 无完整节假日日历 → 非交易日误成交 | 工作日启发式 + 人工日历 |
| VP-R33 | 无夜盘 → 诊断日盘口径 | 文案强制标注 |
| VP-R34 | DCE/东财席位史短 → 长窗诊断弱 | 缩短窗或降置信度 |
| VP-R35 | 付费源误触（Tq/扶摇/iFinD） | 适配器禁止 fetch 补洞 |

---

## P2 — 工程 / 运维

| ID | 风险 | 缓解 |
|----|------|------|
| VP-R40 | VP 测试脆导致 daily.yml 红 | 稳健单测 / 可选 marker |
| VP-R41 | 大 JSON 入库拖垮 git | 确认提交策略；可 gitignore 日内临时 |
| VP-R42 | 与 F2 刀并行冲突 | 一刀一开；VP Phase 1 须显式确认 |
| VP-R43 | Desk 写权限过大 | 面板默认只读；写操作二次确认 |

---

## P3 — 体验 / 文档

| ID | 风险 | 缓解 |
|----|------|------|
| VP-R50 | 诊断词与 Desk「持有/建议平」不一致 | Phase 0 决策表确认词表 |
| VP-R51 | 手动单被标成 CTA_SIGNAL | source 枚举 + 审计字段 |
| VP-R52 | 多账户净值串账 | account_id 路径隔离 + 单测 |

---

## 开 Phase 1 前检查清单

- [ ] 四份 Phase 0 文档已审阅  
- [ ] 确认 VP 是否入库 / Actions  
- [ ] 确认默认 `fill_policy`（建议 `next_open`）  
- [ ] 确认保证金静态表来源  
- [ ] 确认与 F2 刀序（单独开刀 vs 等待）  
- [ ] 明确：**不修** VP-R20/21 等现有异常，除非另开刀  

**未全部确认前：禁止 Phase 1 代码。**
