# VP Phase 1A — Independent Acceptance Audit

**规格来源**：ChatGPT「CTA模拟仓可行性分析」下文（独立验收；不改业务代码）  
**审计日期**：2026-11-23  
**范围**：`virtual_portfolio/` · `configs/virtual_portfolio/` · `desk/virtual_portfolio_panel.py` · `tests/test_vp_phase1a.py` · `docs/audit/VP_PHASE1A_*.md`  
**性质**：**只审计**；本文件交付后停止；不接 1B、不改 F2、不修 PA-001。  
**GitHub**：本地未推送；GPT 在 remote `main` 看不到本刀产物 — **属实**（与「当前未同步」一致）。

**证据类型标注**：`[T]`=自动化测试已证明 · `[R]`=代码审查推断 · `[D]`=文档宣称

---

## 0. 总体结论

| 裁决 | 内容 |
|------|------|
| **Phase 1A 功能开发** | **暂停**（与 GPT 决策表一致；本刀不继续加功能） |
| **1A 独立验收** | **PARTIAL PASS** — 可作 RESEARCH 手工账本继续用；**未**达「完整期货账务验收」 |
| **完整 Phase 1B** | **NO-GO** |
| **1B-0（信号只读）** | **CONDITIONAL GO · 规格已备** — 见 `VP_PHASE1B0_SPEC.md`；实现须另行明示开刀 |
| **1B-1 / 1B-2 / Phase 2** | **暂缓** |
| **F2 / PA-001** | **继续锁定 / 独立追踪**（不与 VP 混刀） |

**一句话**：1A 已从设计变成可运行隔离账本，10 项测试绿且污染哨兵有效；但保证金可信度字段未产品化、读路径会重写投影、复杂期货账务测试仍有缺口 — **不能**据此批准自动跟信号。

---

## 1. 架构与数据流 `[R]`

```text
Desk/CLI
  → virtual_portfolio.engine (MANUAL|SYSTEM_TEST only)
      → ledger.append_event → data/virtual_portfolio/<id>/ledger.jsonl  (append)
      → rebuild_account → account.json / positions.json / equity.json (projection rewrite)
  → instruments: configs/virtual_portfolio/instruments_v1.json (RO)
  ⇏ paper_book / l1_report / upgrade_gate / universe 字段
```

| 项 | 标记 | 说明 |
|----|------|------|
| 物理隔离命名空间 | **PASS** `[R][T]` | 数据仅 `data/virtual_portfolio/`；`guard` 禁写正式文件名 |
| 不接自动信号 | **PASS** `[T]` | `source=CTA_SIGNAL` 抛错 |
| 与 options paper 类比 | **PASS** `[R]` | 顶层包 + data 子树，合理 |
| 读路径无副作用 | **FAIL** `[R]` | `load_account_state`→`rebuild_account` **每次查询重写**三份投影 JSON；Desk 选账户即触发 |

---

## 2. 账本完整性

| 检查 | 标记 | 证据 |
|------|------|------|
| API 路径追加-only | **PASS** `[R][T]` | `append_event` 仅 `open("a")`；无 update/delete API；dedupe 测通过 |
| 禁止静默改历史 | **PARTIAL** `[R]` | 应用层不改写；**文件系统仍可手工改 jsonl**（无签名/密封） |
| 事件唯一 ID | **PASS** `[R][T]` | `event_id` / `client_event_id`；重复提交不双开 |
| 从账本重建 | **PASS** `[T]` | `test_persistence_rebuild` |
| 账本/权益/持仓原子一致 | **PARTIAL** `[R]` | 无 DB 事务；顺序=先 append 再 rebuild。崩溃后可用 rebuild 恢复；**无**「半条 ledger 行」防护（非原子行写入） |
| 部分提交 / 回滚 | **FAIL** `[R]` | 无事务回滚模型；测试矩阵「事务回滚」**未覆盖** |
| 并发写入 | **UNKNOWN** `[R]` | 无文件锁；多进程 Desk+脚本未测 |

---

## 3. 资金核算公式 `[R]`（抽查）

| 公式 | 实现 | 标记 |
|------|------|------|
| 开仓扣费 | `cash -= fee`（fee=`fill_cost` 含滑点+手续费） | **PASS** |
| 保证金占用 | `margin_used = qty×mult×mark×rate`；**不**从 cash 再扣一遍 | **PASS**（未双重扣减） |
| 可用资金 | `available = equity − margin_used` | **PASS** |
| 平仓已实现 | `realized = signed(price−avg)×mult×qty − fee`；`cash += realized` | **PASS** `[R]` |
| 多头开加平 | 测试覆盖 | **PASS** `[T]` |
| 空头开仓+盯市 | 有 short open；**无** dedicated short 平仓盈亏断言 | **PARTIAL** |
| 分批开仓 lots | `test_lots_batches` | **PASS** `[T]` |
| 部分平仓 | 减仓测有；FIFO lots 削减有；**缺**费用按批分摊专项断言 | **PARTIAL** |
| 平今费率 | 代码有 `close_today` 回退 + flag；**无测试** | **PARTIAL** / 缺口 |
| tick/手数精度 | 手数 `int`；**未**校验 price 对齐 tick | **FAIL**（缺口） |

---

## 4. 保证金参数可信度

| 检查 | 标记 | 说明 |
|------|------|------|
| 与 universe 分离 | **PASS** `[R]` | 独立 `instruments_v1.json`；未写回 universe |
| exchange/broker/stress 分列 | **PASS** `[R]` | 已分列 |
| `verified_at=null` 不伪装已核验 | **PARTIAL** `[R]` | 有 `MARGIN_UNVERIFIED` flag；**未**落盘 `ACCOUNT_MODE=RESEARCH_ONLY` / `MARGIN_STATUS=UNVERIFIED` / `AUTO_OPEN_ALLOWED=FALSE` 显式字段 |
| MISSING 不静默默认 | **PASS** `[T]` | `VPTEST` → `MARGIN_DATA_MISSING` |
| UI 显示可信度 | **PARTIAL** `[R]` | Desk 显示 `margin_complete` 与 flags；未用 GPT 建议的三态字段名 |
| 过期参数 | **PARTIAL** `[R]` | `effective_to` 有过滤；**无**过期用例测试 |
| 未核验禁自动开仓 | **PASS**（1A 语境）`[T]` | 1A 本就禁 `CTA_SIGNAL`；1B 前仍须产品化 AUTO_OPEN 开关 |

---

## 5. 模拟成交审计

| 检查 | 标记 | 说明 |
|------|------|------|
| 保存价/量/asof/source/fee/slip | **PASS** `[R]` | open/close 事件字段齐全 |
| 合约乘数 | **PASS** `[R]` | 来自 instruments；缺失拒开 |
| 参数版本 | **PARTIAL** `[R]` | 记 margin_tier/rate；**未**记 instruments schema version / 文件哈希 |
| fill_policy=next_open | **PASS** `[D][R]` | 字段记录；1A 由人工填价（不自动拉行情） |
| 拒绝异常 | **PASS** `[T]` | 负手数、超量平、禁 CTA_SIGNAL |

---

## 6. 隔离与污染防护

| 检查 | 标记 | 说明 |
|------|------|------|
| Paper Book 不变 | **PASS** `[T]` | 哨兵 SHA |
| L1 信号不变 | **PASS** `[T]` | 哨兵 SHA |
| F2 ready/id 不变 | **PASS** `[T]` | `ready=false`, `next_upgrade_id=F2` |
| 无 `refresh_paper_book` 引用 | **PASS** `[R]` | VP 包内仅文档/禁名单提及 |
| 正式 BT 产物 | **UNKNOWN** `[R]` | 污染测试未放 BT 哨兵文件 |

复跑：`pytest tests/test_vp_phase1a.py -q` → **10 passed**（本审计时）。

---

## 7. Desk 界面

| 检查 | 标记 | 说明 |
|------|------|------|
| 独立页不进正式 KPI | **PASS** `[R]` | 「虚拟组合」页；非 strategies/extra |
| 加载/刷新不写 ledger | **PASS** `[R]` | 无按钮不 append |
| 加载不写任何状态 | **FAIL** `[R]` | `load_account_state` 重写投影（见 §1） |
| 展示与账本一致 | **PARTIAL** `[R]` | 展示来自 rebuild 投影；与 ledger 一致依赖 rebuild 正确（有测） |

---

## 8. 测试覆盖矩阵

| GPT 要求项 | 现状 | 标记 |
|------------|------|------|
| 多账户隔离 | 有 | **PASS** |
| 多头盈亏 | 有（开加平） | **PASS** |
| 空头盈亏 | 仅 open+mark | **PARTIAL** |
| 多批次开平 | 开仓批次有；平仓 FIFO 弱测 | **PARTIAL** |
| 部分平仓 | 有减仓 | **PARTIAL** |
| 开/平/平今手续费 | 开平间接；平今无 | **PARTIAL** |
| 乘数与 tick | 乘数间接；tick 对齐无 | **PARTIAL** |
| 缺失/过期保证金 | 缺失有；过期无 | **PARTIAL** |
| 重复订单/成交 | 有 | **PASS** |
| 事务回滚 | 无 | **FAIL**（缺口） |
| 重启恢复 | 有 | **PASS** |
| 账本重建一致 | 有 | **PASS** |
| Paper/L1/F2 污染 | 有 | **PASS** |

**结论**：不得以「10 passed」代替完整验收 — GPT 要求成立；缺口见下。

---

## 9. 缺陷与严重程度

| ID | 严重度 | 问题 | 建议阶段 |
|----|--------|------|----------|
| ACC-01 | **P1** | 查询/`load_account_state` 重写投影，读路径有写副作用 | 1A 修补刀（须另开） |
| ACC-02 | **P1** | 缺显式 `ACCOUNT_MODE` / `MARGIN_STATUS` / `AUTO_OPEN_ALLOWED` | 1A 修补或 1B-0 前置 |
| ACC-03 | **P2** | 无 tick 对齐校验 | 1A 修补 / 1B-1 前 |
| ACC-04 | **P2** | 空头平仓、平今费、过期保证金、事务/并发测试缺口 | 验收补测刀 |
| ACC-05 | **P2** | 成交未绑定 instruments 版本哈希 | 1B-1 前 |
| ACC-06 | **P3** | ledger 无密封；可被盘外篡改 | 延后 |
| ACC-07 | **P3** | 远程 GitHub 无本刀代码，外部无法复核 | **推送/提交**（运维，非功能） |

---

## 10. Phase 1B 准入建议（对齐 GPT 拆分）

| 子阶段 | GPT 决策 | 本审计建议 |
|--------|----------|------------|
| **1B-0** 信号只读（不开仓） | 审计通过后开放 | **CONDITIONAL**：先修 ACC-01/02 或你书面豁免；且只读适配器+污染测 |
| **1B-1** 订单意图验证 | 暂缓 | **同意暂缓** |
| **1B-2** 模拟成交 | 保证金与成交规则合格后 | **同意**；须 verified 保证金策略 + 补测矩阵 PASS |
| **Phase 2** | 暂缓 | **同意** |
| **F2** | 继续锁定 | **同意**（`ready=false`） |
| **PA-001** | 独立追踪 | **同意** |

---

## 11. 停止条件（验收刀当时）

验收刀交付时未改业务代码。随后 GPT 授权 **VP-1A-Fix**（见更新）。

---

## 12. 1A-Fix 后更新（2026-11-23）

详见 `VP_PHASE1A_FIX_REPORT.md`。

| 原缺口 | 修复后 |
|--------|--------|
| ACC-01 查询写投影 | **PASS** — `load_account_state` 只读；`rebuild_account` 显式 |
| ACC-02 运行状态 | **PASS** — RESEARCH_ONLY + AUTO_*/SIGNAL fail-closed |
| 补测矩阵 | **PASS** — 17 tests（含查询只读 / 空头平仓 / 平今 / tick / 拒单不写账） |

**Phase 1A 最终结论**：**PASS（RESEARCH_ONLY）**  
**1B-0**：GPT 已给 CONDITIONAL GO；规格见 `VP_PHASE1B0_SPEC.md`；**实现**仍须明示开刀，本文件不自动授权。
