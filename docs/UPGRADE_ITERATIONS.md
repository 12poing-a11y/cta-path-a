# CTA Path-A · 升级计划（合并权威版）

**同步日期**：2026-11-22（T-DU/T-GV/T-P1/V-旁路完成 · 余项入库）  
**仓库**：`d:\AI\cta-path-a`（套利影子 worktree：`d:\AI\cta-path-a-arb-v11`）  
**本文件角色**：**唯一刀序权威**。细则仍分散在子文档；状态与优先级以本表为准。

---

## 工作方式（固定）

1. **标记**：本文件为总状态；期权细则 `docs/options/ROADMAP.md`；套利细则 `docs/ARBITRAGE_VOLATILITY_UPGRADE.md`；可信度细则 `docs/PHASE2_AUDIT_DECISIONS.md` + `docs/P0_CODE_AUDIT.md`。  
2. **逐步开放**：未完成项保持「封闭」；只开状态为 **下一刀** 的一项。  
3. **迭代反馈**（每刀结束后必写，3–6 行）：做了什么 / 产物 / 验证 / 风险与未做 / 建议下一刀或停。  
4. **个人档案**：Notion Memory + About「Current work」；本机个人库 `cta-path-a/UPGRADE_PLAN.md`。  
5. **硬围栏**：不写 Path-A `paper_book` / 正式 BT / seats，除非你明示。

---

## 0. 来源清单 · 评估合并

| 来源 | 原定位 | 评估 | 合并处置 |
|------|--------|------|----------|
| `docs/UPGRADE_ITERATIONS.md`（本文件） | 近期一刀一开 | **保留为权威** | 吸收其余轨的状态与候选队列 |
| `docs/options/ROADMAP.md` + AUDIT/DESIGN | 期权 A→F+ | **保留细则** | 状态跟本表；F2 锁定 |
| `docs/ARBITRAGE_VOLATILITY_UPGRADE.md` | 套利影子 V1→V1.5 | **保留细则** | V1.3 观察；V1.4+ 封闭 |
| `docs/PHASE2_AUDIT_DECISIONS.md` + `P0_CODE_AUDIT.md` | 第二阶段可信度 | **吸收为轨 T** | 残留项进「候选队列」；不另立下一刀 |
| `docs/UPGRADE_PLAN.md` | 研究台 P0–P4 / A1–A3 | **归档指向** | 已完成项记入下表；「下次剩余」并入候选或延后 |
| `docs/research_roadmap_12_weeks.md` | 12 周有效性路线（~11/02） | **历史归档** | 原则（证据等级 E0–E5、先可信）已内化；周历不再单独推进 |
| Gemini/HTML 波动率协同（产物+审计） | 旁支模拟 | **观察吸收** | 不晋级 `position_rules`；HV/带可旁路观察 |
| Notion Memory / 个人库镜像 | 提醒偏好与姿态 | **跟本表** | F2 先念内容；样本够再提醒 |

**合并原则**：可信度 > alpha；样本不够不开刀；观察续跑 ≠ 开新刀；正式层需明示。

---

## 1. 当前姿态与锁定下一刀

**姿态（2026-11-22）**：**可信度可做项已清** → 回到 **观察 / 积样本**；默认不开新刀。

**锁定下一刀（未开放）**：**F2** — 含 Bid/Ask 的信用价差研究 BT  

- **内容**：活链 Bid/Ask 快照跑 `credit_vertical`（`pricing_mode=bid_ask`），对照 settle_discount；状态最高 WARN；不写正式层。  
- **门槛**（`research/options/upgrade_gate.py`）：CF 盘口日 ≥10 **或** CF/SR/MA 各 ≥5。  
- **现样（2026-11-22）**：`ready=false`；CF bidask_days=**1**/10，SR/MA=**0**/5；本机日积曾 **no-auth**。  
- **提醒**：日报 `[options-upgrade]`、Desk、`data/options/upgrade_gate_latest.json`；你说「继续/升级」时先念 F2 + 是否够样，**确认后再干**。

**积样本动作（非刀 · 需 Tq 凭证）**：  
`python scripts/run_options_chain_collect.py --codes CF,SR,MA --tq-live-only --deadline 45`

---

## 2. 合并后总览（四轨）

| 轨 | ID 前缀 | 内容 | 状态 | 开放 |
|----|---------|------|------|------|
| **O 期权** | A–E, F1, F1b | 审计→定价→链→信用 BT→纸面→活链→日积 | **完成** | 封闭 |
| **O 期权** | **F2** | Bid/Ask 信用价差研究 BT | **锁定·等样本** | **未开放** |
| **O 期权** | F+ | 买方 / 全宇宙 / 升 PAPER / 写正式层 | **延后** | 封闭 |
| **T 可信度** | Phase2 P0 主修 | 混价锁 / proxy KPI / paper 幂等 / 正式 scorecard | **完成** | 封闭 |
| **T 可信度** | **T-DU** | 日报会话日陈旧熔断 | **完成** | 封闭 |
| **T 可信度** | **T-GV** | Gate↔scorecard（产物推导） | **完成** | 封闭 |
| **T 可信度** | **T-P1** | BT 成交归因 + Regime×袖套 | **完成** | 封闭 |
| **T 可信度** | **T-DQ-diff** | 双源对账报告（免费优先） | **完成** | 封闭 |
| **A 套利影子** | V1–V1.3 | 对齐/协整/费后 BT/双路径监控 | **完成·观察** | 封闭（积样本） |
| **A 套利影子** | V1.4–V1.5 | IV/VRP 监控；动态波动托管 | **封闭·等样本** | 未开放 |
| **V 波动协同** | Gemini P0–P2 | TVS/VRP/Carry 整案模拟+审计 | **观察·不晋级** | 封闭 |
| **V 波动协同** | **V-旁路** | 下行 HV + 容忍带观察快照 | **完成（观察）** | 封闭 |
| **S 会话** | Session brief | 多时段盘中 brief | 交 Grokbot | 本仓不做 |
| **R 研究台旧项** | P1–P4 / A1–A3 | PBO/LSP/Gamma/组合风险/轻量 ML / 主力映射 | **主路径完成** | 封闭 |
| **R 研究台旧项** | 官历/因子注册/聚类 | `UPGRADE_PLAN`「下次剩余」 | **低优延后** | 封闭 |

---

## 3. 轨详（摘要）

### 3.1 期权轨 O — 细则 `docs/options/ROADMAP.md`

| 阶段 | 状态 | 备注 |
|------|------|------|
| A–E | 完成 | settle BT n≈5 WARN |
| F1 / F1b | 完成 | 日积管线在；盘口日仍极少 |
| **F2** | 锁定 | 现样不够 |
| F+ | 封闭 | 无长史盘口不晋升 |

### 3.2 可信度轨 T — 细则 `PHASE2_AUDIT_DECISIONS` / `P0_CODE_AUDIT`

| 项 | 状态 | 数据体量 | 评估 |
|----|------|----------|------|
| 混价锁 / 主力超差 proxy / proxy KPI | 完成 | 期货够 | 已吸收 |
| paper_book 幂等 / 入场日保护 / 原子写 | 完成 | — | 已吸收 |
| 正式 scorecard 重跑 | 完成 | — | 已吸收；Path-A 仍 SUSPENDED |
| **T-DU**：日报 `bar_date` 陈旧熔断 | **完成** | 期货够 | `expected_session` 硬闸；`asof`=会话日 |
| **T-GV**：Gate 接线 scorecard | **完成** | 期货够 | 产物推导；缺 Stress→`ok=false`；登记实验 |
| **T-P1**：归因 + Regime 影子矩阵 | **完成** | BT closed_pnls | `shadow_attribution_latest.json`；Desk 只读 |
| DQ 惰性闸门清理 | **延后** | — | 低优；不挡 F2 |
| 组合帽 / next_open 纸面完全对齐 | **延后** | — | 低优；需明示再开 |

### 3.3 套利轨 A — 细则 `ARBITRAGE_VOLATILITY_UPGRADE.md`

| 阶段 | 状态 |
|------|------|
| V1–V1.3 | 完成·观察（协整闸下不达开仓；fade 优于 follow） |
| V1.4 | 封闭（需期权 IV/盘口样本，宜在 F2 之后再议） |
| V1.5 | 封闭 |

**非刀**：可续跑 `run_arb_v13_shadow.py` 追加 ledger。

### 3.4 波动协同轨 V

| 层 | 状态 |
|----|------|
| P0 TVS 影子 / OOS | 观察；`promote_path_a=false` |
| P1 VRP 代理 / P2 Carry | 封闭/弱 |
| **V-旁路** | **完成** | `vol_observe_latest.json` + HV 面板只读；`promote_path_a=false` |

### 3.5 研究台旧轨 R — 原 `UPGRADE_PLAN.md`

已完成并封闭：P0 数据/成交、P1 PBO、P2 LSP+Gamma 研究、P3 组合风险影子、P4 轻量 ML、A1 成绩统一、A2 历史主力、A3 purge/embargo。  
延后：官历精校、因子注册表、组合聚类 B、重型 ML — **不进入近期刀序**。

### 3.6 12 周路线图 — 原 `research_roadmap_12_weeks.md`

**归档**。证据分级与「先可信再 alpha」已并入工作方式与轨 T；周 3–12 的因子/事件/模拟观察等，仅在 T-P1 与后续研究需要时按题单开，不再按周历推进。

---

## 4. 剩余项（写入计划 · 现均未开放）

| 序 | ID | 内容 | 阻塞 | 状态 |
|----|-----|------|------|------|
| 0 | （非刀） | F1b 日积盘口 | **需 Tq 凭证/网络** | 运维续跑 |
| **锁** | **F2** | Bid/Ask 信用价差研究 BT | 盘口日不够 | **等样本+确认** |
| 1 | A-V1.4 | 商品期权 IV/VRP/Greeks 监控 | 宜 F2/盘口后 | 封闭 |
| 2 | F+ | 买方 / 全宇宙 / 升 PAPER | 长史盘口+人工评审 | 封闭 |
| 3 | V1.5 | 动态波动托管进风险预算 | 决议+样本 | 封闭 |
| 4 | DQ 清理 / 纸面组合帽对齐 | 工程抛光 | 低优 | 延后 |
| 5 | 官历精校 / 因子注册 / 聚类 B | 旧研究台剩余 | 低优 | 延后 |
| — | 写正式 `paper_book`/seats / 解 SUSPENDED | 明示+Gate 人工 | **硬围栏** | 封闭 |

**默认建议**：配 Tq 凭证日积 → 样本够后确认开 **F2**；其余保持封闭。

---

## 5. 硬不做（合并后仍有效）

- ADX/布林等堆正式开仓过滤  
- 观察袖套并入 `paper_book` / 改 `position_rules` / seats（无明示）  
- Transformer / RL / 换重量级回测平台  
- 多时段 brief 合入本仓  
- 为凑覆盖率灌脏合约数据  
- 盘口不够时跑 F2 或抬策略至 PAPER  

---

## 6. 文档指向（合并后）

| 文件 | 角色 |
|------|------|
| **本文件** | 刀序 + 合并状态 + 候选队列 |
| `docs/options/ROADMAP.md` | 期权细则 |
| `docs/ARBITRAGE_VOLATILITY_UPGRADE.md` | 套利细则 |
| `docs/PHASE2_AUDIT_DECISIONS.md` | 可信度裁决原文 |
| `docs/P0_CODE_AUDIT.md` | 可信度问题清单 |
| `docs/UPGRADE_PLAN.md` | **历史**：P0–P4/A1–A3 执行记录 → 指向本文件 |
| `docs/research_roadmap_12_weeks.md` | **历史**：12 周愿景 → 指向本文件 |
| 个人库 `cta-path-a/UPGRADE_PLAN.md` | 本表镜像 |

---

## 7. 近期迭代反馈（保留）

### F1

- **做了**：活链 Bid/Ask 字段与 `--tq-live`  
- **验证**：相关测绿；历史 BT 仍 WARN  
- **下一刀**：曾开 F1b  

### F1b

- **做了**：快路径+截止；日报 soft 日积  
- **建议**：停；样本够再 F2  

### Arb V1.1–V1.3 + Gemini（2026-11-22）

- **做了**：套利全套影子 + Gemini 整案模拟审计  
- **验证**：不支持开仓 / 改正式规则  
- **建议**：**停 · 观察**；样本够后确认 **F2**  

### 计划合并（2026-11-22）

- **做了**：多源计划评估合并进本文件；旧计划改归档指向  
- **产物**：本文件；个人库镜像；Notion 姿态记忆  
- **验证**：F2 gate 复测仍 `ready=false`  
- **风险/未做**：未改锁定位；未自动开 T-DU  
- **建议下一刀**：停；或你明示开 **T-DU** / 确认等 **F2**  

### T-DU + 日积盘口（2026-11-22）

- **做了**：`expected_session` 硬闸；日报 `asof`=会话日；日积尝试  
- **验证**：research_quality 测绿；日积 no-auth；F2 gate 仍不够  
- **建议**：曾续开 T-GV  

### T-GV + T-P1 + V-旁路（2026-11-22）

- **做了**：Gate 从 BT/PBO 产物推导并写入 scorecard（缺 Stress→`ok=false`；登记 formal_scorecard 实验）；BT `closed_pnls` 归因+规则 Regime×袖套；下行 HV 观察快照挂 HV 面板  
- **产物**：`research/governance/scorecard_gate.py`；`lab/research/validation/formal_scorecard_latest.json`（含 gate）；`shadow_attribution_latest.json`（n=69）；`vol_observe_latest.json`（n=27）；相关 Desk/日更 soft  
- **验证**：`pytest tests/test_scorecard_gate.py tests/test_shadow_attribution.py tests/test_research_quality.py` 19 passed；gate `artifact_build_ok=True`（仍缺 human_approval → `pass=false`）  
- **风险/未做**：未重跑全年 BT（gate-only 刷新）；F2/A-V1.4/F+/正式晋级未开；日积仍需凭证  
- **建议下一刀**：**停 · 积样本**；够样后确认 **F2**  

### T-DQ-diff（2026-11-22）

- **做了**：台内双源对账（新浪 vs history；东财席位 vs 上期/郑商打印 kind 净持仓）；硬禁付费 Key；Desk 只读展开  
- **产物**：`research/data_quality/dual_source_diff.py`；`scripts/run_dual_source_diff.py`；`data/dual_source_diff_latest.json`  
- **验证**：`pytest tests/test_dual_source_diff.py`；CLI 抽样跑  
- **风险/未做**：未对差异硬熔断；DCE 无独立交易所对照；未挂日更强制  
- **建议下一刀**：**停 · 积样本**；够样后确认 **F2**（或明示再加 diff 硬闸）  

---

## 反馈模板

```text
【迭代反馈 · <阶段ID>】
做了：
产物：
验证：
风险/未做：
建议下一刀：开 <ID> / 停
```
