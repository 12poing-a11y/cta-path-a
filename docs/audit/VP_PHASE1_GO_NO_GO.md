# VP Phase 1 — GO / NO-GO 准入决策

**规格来源**：ChatGPT Shared Content `t_6b042f86fec081919152bb60502b4452`（Phase 0 复核与 Phase 1 准入）  
**复核日期**：2026-11-23  
**性质**：审计复核 + 准入；**未写业务代码**；**未改** `paper_book` / CTA 信号 / F2 门禁 / Actions。  
**期权锁定刀**：**F2** 仍 `ready=false`（CF=2/10，SR/MA=1/5）— **不解锁、不绕过**。

---

## 0. 总裁决

| 范围 | 裁决 | 说明 |
|------|------|------|
| **完整 Phase 1**（账户+自动跟 L1+诊断） | **NO-GO** | 保证金真源、隔离测试、成交门禁均未落地 |
| **Phase 1A**（独立账户 / 资金 / 订单成交账本；**不接**自动信号） | **CONDITIONAL GO** | 规则文档已锁定；实现前须满足 §4 前置项 |
| **Phase 1B**（只读接入 L1 自动跟单） | **NO-GO（暂缓）** | 须 1A 验收通过后再开刀 |
| **Phase 2**（持仓诊断） | **NO-GO（延后）** | 证据源缺口已知；不挡 1A |
| **F2** | **保持锁定** | 与 VP 准入分离；样本不够 |
| **顺手修 paper 异常** | **NO-GO** | 见 `PAPER_ANOMALY_TRACKER.md` |

**一句话**：可以小步开 **Phase 1A 账户与账本**；不能因 Phase 0 文档齐全就整包开发 VP，也不能为 VP 动 F2 / 正式纸面。

**执行状态（2026-11-23）**：**VP-Phase1A 已落地并测通**（见 docs/audit/VP_PHASE1A_*.md）；**未**进入 1B/2；F2 仍锁定。


---

## 1. 六问逐项标记

标记：`PASS` 证据充分 · `PARTIAL` 有设计仍有缺口 · `BLOCKED` 不具备实施条件 · `UNKNOWN` 信息不足。

### Q1. 现有 CTA 信号能否只读接入？

| | |
|--|--|
| **标记** | **PARTIAL** |
| **证据** | `data/l1_report.json`（及 fingerprint）可只读；正式写入不经读 JSON 发生 |
| **缺口** | 尚无 `adapters/l1.py`；`daily_update` import 有副作用 → 设计已禁 import |
| **1A** | **不需要**信号接入 → 不挡 1A |
| **1B** | 必须落地只读适配器 + 单测证明不调用 `refresh_paper_book` |

### Q2. VP 是否拥有独立账户、订单、成交和持仓账本？

| | |
|--|--|
| **标记** | **PARTIAL**（设计）/ 实现 **BLOCKED** |
| **证据** | Phase 0 字典已定 `data/virtual_portfolio/<id>/` schema；options paper 有隔离先例 |
| **缺口** | 包 `virtual_portfolio/`、ledger、guard **均未创建** |
| **1A** | 本阶段目标正是补齐；CONDITIONAL GO 的核心范围 |

### Q3. 合约乘数、保证金、手续费、交易日历是否有可靠数据来源？

| 数据 | 标记 | 来源 / 缺口 |
|------|------|-------------|
| 乘数 / 跳点 | **PASS** | `universe.json` → `symbols[].mult/tick` |
| 手续费（开/平同费率近似） | **PARTIAL** | `fee_yuan`/`fee_rate` + `fill_cost` / `research_cost`；**无平今分列** |
| 保证金率 | **BLOCKED** | `universe.symbols` **无** `margin_rate`；须新建 VP 静态表，缺则拒开仓 |
| 交割禁开 | **PARTIAL** | `configs/calendar/delivery_rules.json`（研究近似） |
| 交易所节假日 | **BLOCKED**（完整）/ **PARTIAL**（启发式） | 无官历；1A 可用工作日启发式并打 flag |
| 涨跌停价 | **UNKNOWN** / 弱 PARTIAL | `delivery_rules.default.limit_pct` 有近似；非逐日涨跌停板 |

### Q4. 模拟成交是否严格遵循时间顺序？

| | |
|--|--|
| **标记** | **PARTIAL** |
| **证据** | 正式 BT=`next_open`；paper=`close` 无成本 — 审计已分清；`VP_PHASE1_FILL_RULES.md` 已锁定默认 `next_open` |
| **缺口** | 引擎未实现；涨跌停未成交、幂等键、过期拒绝尚无代码 |
| **红线** | 禁止以信号日收盘成交作为 VP 默认（避免重蹈 paper 口径） |

### Q5. 数据不完整时能否自动降级并阻止开仓？

| | |
|--|--|
| **标记** | **PARTIAL**（意图）/ 实现 **BLOCKED** |
| **设计** | 缺保证金/缺开盘/STALE → `REJECTED`（见成交规范） |
| **缺口** | 无实现、无单测；席位 loader 若误用会写缓存（VP-R04） |
| **1A** | 手工单同样必须走拒绝门禁 |

### Q6. 是否有测试证明 VP 不会污染现有 Paper Book？

| | |
|--|--|
| **标记** | **BLOCKED** |
| **证据** | 尚无 VP 包与测试 |
| **要求** | Phase 1A 验收硬门槛：CI/本地测试证明不 import/调用 `refresh_paper_book`；运行后 `paper_book_latest.json` mtime/内容不变（夹具） |

---

## 2. Phase 0 四文档复核摘要

| 文档 | 复核结论 |
|------|----------|
| `VIRTUAL_PORTFOLIO_AUDIT.md` | 隔离结论与正式写入点判断**成立**；「文档写了隔离 ≠ 代码已隔离」须在本 GO/NO-GO 强调 |
| `VIRTUAL_PORTFOLIO_DEPENDENCY_MAP.md` | 拓扑合理；与 options paper 类比正确 |
| `VIRTUAL_PORTFOLIO_DATA_DICTIONARY.md` | schema 可用；保证金字段仍为空洞 — 已升格为 1A 前置 |
| `VIRTUAL_PORTFOLIO_RISK_REGISTER.md` | P0 项仍有效；本刀未关闭任何 P0（设计缓解进规则文档） |

**修订建议（已落地本刀）**：

- 新增本文件 + `VP_PHASE1_ACCOUNT_RULES.md` + `VP_PHASE1_FILL_RULES.md` + `PAPER_ANOMALY_TRACKER.md`  
- 不改 Phase 0 四件套正文（避免无版本漂移）；以本文件为 Phase 1 权威准入

---

## 3. 分类清单

### 3.1 Phase 1A 可以开始的部分（你确认开刀后）

- 顶层包 `virtual_portfolio/` + `guard.py`（只写 `data/virtual_portfolio/**`）  
- 账户 CRUD、入金出金、手工订单 → 成交（`next_open` + 成本）  
- JSONL ledger / positions / equity  
- 静态 `margin_rates.json`（缺则拒开）  
- 污染防护单测（Q6）  
- **不接** L1 自动信号；**不改** Desk 正式页按钮；**不挂** `strategies/extra`

### 3.2 Phase 1 开始前必须解决（1A 编码前置）

1. 你确认本文件 **CONDITIONAL GO · Phase 1A**  
2. 锁定采纳：`VP_PHASE1_ACCOUNT_RULES.md` + `VP_PHASE1_FILL_RULES.md`  
3. 确认 VP 状态是否入库（建议：本机先跑；是否 commit `data/virtual_portfolio/` 另议）  
4. 确认静态保证金表初值来源（人工录入 / 外部摘录；**不**写回 universe）

### 3.3 可延后到 Phase 1B / 2

| 项 | 阶段 |
|----|------|
| 只读 L1 自动跟单 + 信号幂等 | 1B |
| 涨跌停精细未成交 / 平今费率 | 1B+ |
| 完整节假日官历 | 2 前可加强 |
| 持仓诊断（情绪/席位/vol） | Phase 2 |
| Desk 独立面板 | 1A 末或 1B |
| 修复 PA-001 P 止盈等 | **独立 paper 刀** |

### 3.4 不能修改的现有模块

- `paper_book.refresh_paper_book` 及 Desk/sync 调用链  
- `daily_update` 信号产物路径、`l1_report*`  
- `universe.json` / `execution_rules` / `formal_rule_lock` / `rule_lock` 忽略规则  
- `research/options/upgrade_gate.py` 与 F2 门槛  
- 正式 BT / seats / Path-A 晋级

### 3.5 尚未解决的数据依赖

- 全品种 `margin_rate` 静态表  
- 平今手续费  
- 交易所节假日日历  
- 逐日涨跌停价  
- vol 非 7 品种、席位 cache-only 适配器（1B/2）

---

## 4. Phase 1A 验收标准（开刀后）

1. 新建账户 → 入金 → 手工开仓（next_open+成本）→ 盯市 → 平仓 → 权益恒等式可对账  
2. 缺 `margin_rate` / 缺开盘价 → 必 `REJECTED`，无幽灵成交  
3. 重复手工/测试单幂等，不双开  
4. 测试：VP 流程前后 `paper_book` 文件哈希不变；源码级禁止 `refresh_paper_book`  
5. 所有事件带 `source`；禁止伪造成 `CTA_SIGNAL`  
6. F2 gate 文件与门槛未被改动  

---

## 5. 与 F2 的关系

| | VP Phase 1A | F2 |
|--|-------------|-----|
| 门禁 | 本文件 + 你确认 | `upgrade_gate.ready` + 你确认 |
| 现态 | CONDITIONAL GO（待确认） | `ready=false`，**锁定** |
| 可否并行 | 仓库纪律默认 **一刀一开**；若开 1A 则本迭代不碰 F2 | 积样继续 |

---

## 6. 建议你确认的决策（默认建议已填）

| # | 问题 | 建议默认 | 你的确认 |
|---|------|----------|----------|
| 1 | 下一刀是否开 **VP-Phase1A** | 是（确认后才编码） | ☐ |
| 2 | VP 数据是否入库 | 先本机；ledger 可 gitignore 或小样本入库 | ☐ |
| 3 | 保证金 | 静态表；缺则拒开 | ☐ |
| 4 | 默认成交 | `next_open` + research_cost Base | ☐ |
| 5 | 1A 是否接 L1 | **否** | ☐ |
| 6 | paper 异常 | 只进 tracker，本刀不修 | ☐ |

---

## 7. 停止条件

本文件交付后 **停止**。  
在你明示「开 VP-Phase1A」之前：**不写** `virtual_portfolio/` 业务代码，不改测试套件挂日更，不触发 F2。
