# CTA Path-A · 升级计划（合并权威版）

**同步日期**：2026-11-23（VP-1A 已合 GitHub main · 1B-0 规格已备 · F2 仍锁定）  
**仓库**：`d:\AI\cta-path-a`  
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
| ChatGPT v2.0 白皮书审计（2026-11-23） | 波动率策略升级框架 | **吸收为 Vol 轨** | 不整包开发；先 Vol-V1.4 定价/Greeks；见 `docs/VOLATILITY_ENGINE_SPEC.md` |
| Notion Memory / 个人库镜像 | 提醒偏好与姿态 | **跟本表** | F2 先念内容；样本够再提醒 |
| ChatGPT CTA Virtual Portfolio 1.0 | 虚拟组合隔离轨 | **吸收为轨 VP** | Phase 0 审计完成；Phase 1+ 待确认 |

**合并原则**：可信度 > alpha；样本不够不开刀；观察续跑 ≠ 开新刀；正式层需明示。

---

## 1. 当前姿态与锁定下一刀

**姿态（2026-11-23）**：**VP-1A = PASS(RESEARCH_ONLY) 已合入 GitHub `main`**（PR [#30](https://github.com/12poing-a11y/cta-path-a/pull/30) → `d61ec7c`）；**1B-0 规格已备、实现未开**；期权轨继续积样；不自动开 1B-0/F2。

**已完成旁轨**：**VP-Phase0**；**VP-Phase1-GoNoGo**；**VP-Phase1A**；**VP-1A-Acceptance**；**VP-1A-Fix**；**VP-1B-0-SPEC**；**VP-1A → main**  
**Vol-V1.4**：本机研究完成（Shadow only），**尚未合入 GitHub** — 清单见 `docs/audit/LOCAL_WIP_INVENTORY.md`。
**settle BT 现况**：`credit_vertical` put_credit · `--settle-only` → n_closed=17 · 胜率≈18% · 总 PnL≈−2185 元 · **WARN**

**锁定下一刀（期权 · 未开放）**：**F2** — 含 Bid/Ask 的信用价差研究 BT  

- **内容**：活链 Bid/Ask 快照跑 `credit_vertical`（`pricing_mode=bid_ask`），对照 settle_discount；状态最高 WARN；不写正式层。  
- **门槛**（`research/options/upgrade_gate.py`）：CF 盘口日 ≥10 **或** CF/SR/MA 各 ≥5。  
- **现样（gate）**：`ready=false`；CF bidask=1/10，SR=0/5，MA=0/5。  
- **提醒**：说「继续/升级」时先念 F2 + 是否够样，**确认后再干**。

**旁轨已完成**：**VP-Phase1A** — 独立账户/资金/手工成交账本（**不接**自动 L1）；已上 `main`  

- **硬围栏**：未写正式 paper_book / 信号 / seats / 正式 BT；未修 PA-001；F2 未解锁；**未**实现 1B-0。

### 1.1 GPT 后续计划（VP · 对齐裁决 · 未自动开刀）

核心界线：**VP 可观察 CTA 信号，不可按信号交易。**

| 序 | 项 | 状态 | 说明 |
|----|----|------|------|
| ✅ | 1A PASS(RESEARCH_ONLY) | **完成并上 GitHub** | 研究账本 + 人工模拟；≠ 自动交易验收 |
| ✅ | 分支同步 + PR 合 main | **完成** | #30；无敏感账号/DB |
| ✅ | 1B-0 实施规格 | **完成** | `docs/audit/VP_PHASE1B0_SPEC.md` |
| ▶ | **VP-1B-0 实现** | **CONDITIONAL GO · 待你明示** | 只读 L1→独立 inbox；新建 `SIGNAL_READ_ALLOWED`；**禁止**全局开 `SIGNAL_INGEST` |
| ⏸ | 1B-0 硬门槛测 | 随实现 | 污染哨兵、权限拆分、幂等、无改账户 |
| 🚫 | 1B-1（订单意图） | NO-GO | 1B-0 通过后**另批**；不自动进入 |
| 🚫 | 1B-2（模拟成交） | NO-GO | 同上 |
| 📋 | 技术债（不挡 1A） | 挂账 | 投影版本一致性；`append_event` 文件锁；加权均价 vs FIFO 口径（执行阶段前定） |

**1B-0 允许**：读根目录 `l1_report.json`；校验/去重；写 `data/virtual_portfolio/signal_inbox/`；Desk 只读查询。  
**1B-0 禁止**：下单/成交/改资金持仓；写 Paper Book；改正式信号；动 F2/PA-001；猜测信号源。

**积样本动作（非刀 · 需 Tq 凭证 · 日常运维）**：  
`python scripts/run_options_chain_collect.py --codes CF,SR,MA --tq-live-only --deadline 45`

---

## 2. 合并后总览（五轨 · 含 VP）

| 轨 | ID 前缀 | 内容 | 状态 | 开放 |
|----|---------|------|------|------|
| **O 期权** | A–E, F1, F1b | 审计→定价→链→信用 BT→纸面→活链→日积 | **完成** | 封闭 |
| **O 期权** | **F2** | Bid/Ask 信用价差研究 BT | **锁定·等样本** | **未开放** |
| **O 期权** | F+ | 买方 / 全宇宙 / 升 PAPER / 写正式层 | **延后** | 封闭 |
| **VP 虚拟组合** | **Phase0** | 只读审计（边界/依赖/字典/风险） | **完成** | 封闭 |
| **VP 虚拟组合** | **GoNoGo** | Phase 1 准入复核 | **完成** | 封闭 |
| **VP 虚拟组合** | **Phase1A** | 账户/资金/手工成交账本（不接 L1） | **完成** | 封闭 |
| **VP 虚拟组合** | Phase1B / 2 | 自动跟信号 / 诊断 | **NO-GO** | 未开放 |
| **T 可信度** | Phase2 P0 主修 | 混价锁 / proxy KPI / paper 幂等 / 正式 scorecard | **完成** | 封闭 |
| **T 可信度** | **T-DU** | 日报会话日陈旧熔断 | **完成** | 封闭 |
| **T 可信度** | **T-GV** | Gate↔scorecard（产物推导） | **完成** | 封闭 |
| **T 可信度** | **T-P1** | BT 成交归因 + Regime×袖套 | **完成** | 封闭 |
| **T 可信度** | **T-DQ-diff** | 双源对账报告（免费优先） | **完成** | 封闭 |
| **A 套利影子** | V1–V1.3 | 对齐/协整/费后 BT/双路径监控 | **完成·观察** | 封闭（积样本） |
| **A 套利影子** | V1.4–V1.5（旧号） | 已改挂 **Vol** 轨 | 见 Vol-V1.4+ | — |
| **V 波动协同** | Gemini P0–P2 | TVS/VRP/Carry 整案模拟+审计 | **观察·不晋级** | 封闭 |
| **V 波动协同** | **V-旁路** | 下行 HV + 容忍带观察快照 | **完成（观察）** | 封闭 |
| **V 波动引擎** | **Vol-V1.4** | 定价 / IV 面 / Greeks / Shadow Greeks | **本机完成 · 未进 GitHub** | 待明示入库 |
| **V 波动引擎** | Vol-V1.5–V2.0 | VRP/TVS/执行成本/奇异/OOS | **封闭** | 未开放 |
| **S 会话** | Session brief | 多时段盘中 brief | 交 Grokbot | 本仓不做 |
| **R 研究台旧项** | P1–P4 / A1–A3 | PBO/LSP/Gamma/组合风险/轻量 ML / 主力映射 | **主路径完成** | 封闭 |
| **R 研究台旧项** | 官历/因子注册/聚类 | `UPGRADE_PLAN`「下次剩余」 | **低优延后** | 封闭 |

---

## 3. 轨详（摘要）

### 3.1 期权轨 O — 细则 `docs/options/ROADMAP.md`

| 阶段 | 状态 | 备注 |
|------|------|------|
| A–E | 完成 | settle BT（2026-11-23）n=17 WARN |
| F1 / F1b | 完成 | 日积管线在；**本阶段主业=积盘口** |
| **F2** | 锁定 | CF=2/10，SR/MA=1/5；够样+确认再开 |
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
| **Vol-V1.4** | **本机完成 · 未进 main** | 产物在本地 WIP；见 `LOCAL_WIP_INVENTORY.md`；须单独开刀 PR |

### 3.5 研究台旧轨 R — 原 `UPGRADE_PLAN.md`

已完成并封闭：P0 数据/成交、P1 PBO、P2 LSP+Gamma 研究、P3 组合风险影子、P4 轻量 ML、A1 成绩统一、A2 历史主力、A3 purge/embargo。  
延后：官历精校、因子注册表、组合聚类 B、重型 ML — **不进入近期刀序**。

### 3.6 12 周路线图 — 原 `research_roadmap_12_weeks.md`

**归档**。证据分级与「先可信再 alpha」已并入工作方式与轨 T；周 3–12 的因子/事件/模拟观察等，仅在 T-P1 与后续研究需要时按题单开，不再按周历推进。

### 3.7 虚拟组合轨 VP — 细则 docs/audit/VIRTUAL_PORTFOLIO_*.md + VP_PHASE1_GO_NO_GO.md

| 阶段 | 状态 | 备注 |
|------|------|------|
| **Phase 0** | **完成** | 四件套：AUDIT / DEPENDENCY_MAP / DATA_DICTIONARY / RISK_REGISTER |
| **Go / No-Go** | **完成** | VP_PHASE1_GO_NO_GO.md；附账户规则 / 成交规范 / Paper 异常专项 |
| **Phase 1A** | **完成 · 已上 main** | PASS(RESEARCH_ONLY)；PR #30 → `d61ec7c` |
| **1B-0 规格** | **完成** | `VP_PHASE1B0_SPEC.md`（读口/收件箱/权限拆分）；**未写业务代码** |
| **1B-0 实现** | **CONDITIONAL GO · 未开** | 须明示开刀；见规格 §6 |
| 1B-1 / 1B-2 | NO-GO | 订单意图 / 模拟成交；须 1B-0 另批 |
| Phase 2+ | NO-GO | 诊断 / Desk |

**隔离要点**：正式纸面写入唯一入口 paper_book.refresh_paper_book；VP 只读 L1/缓存；席位须 cache-only；默认成交对齐正式 
ext_open。

---

## 4. 后续升级方案（写入计划 · 现均未开放）

**原则**：先积盘口/链样本；**不**因「继续/升级」口头自动开刀；够样后先念锁定项内容，**你确认**再开。一次只开一刀。

### 4.1 积样门槛（开刀前置）

| 检查 | 门槛 | 现样（2026-11-23） | 产物 |
|------|------|---------------------|------|
| F2 主门槛 | CF Bid/Ask 日 ≥10 **或** CF/SR/MA 各 ≥5 | CF=2，SR=1，MA=1 → `ready=false` | `data/options/upgrade_gate_latest.json` |
| settle BT 对照 | 已可重跑；仅 WARN | n=17 · 总 PnL≈−2185 | `data/options/backtests/credit_vertical_latest.json` |
| Vol 日报告 | 非收益；可随链续跑 | Vol-V1.4 已通 | `lab/research/volatility/vol_engine_daily_latest.json` |

### 4.2 候选刀序（够样 / 确认后）

| 序 | ID | 内容 | 开放条件 | 状态 |
|----|-----|------|----------|------|
| 0 | （非刀） | F1b 日积盘口 CF/SR/MA | Tq 凭证 + 交易日续跑 | **运维中** |
| **1 · 锁** | **F2** | Bid/Ask 信用价差研究 BT；对照 settle；最高 WARN；不写正式层 | gate `ready=true` **且** 你确认 | **等样本** |
| — | **VP-Phase1A** | 虚拟账户 + 手工成交账本（不接 L1） | 已确认执行 | **完成 · main** |
| — | **VP-1B-0** | 信号只读 + inbox + `SIGNAL_READ_ALLOWED` | 规格已备 **且** 你明示开刀 | **待明示** |
| 2 | Vol-V1.6 | TVS 风险预算硬化（审计 P0；旁路可加深） | 你明示（可与 F2 并行旁轨，仍一刀一开） | 封闭 |
| 3 | Vol-V1.5 | VRP / Gamma Scalping 研究（Shadow） | V1.4 已完成 + 决议 | 封闭 |
| 4 | Vol-V1.7 | 真实执行成本账本（研究） | 决议 | 封闭 |
| 5 | Vol-V1.8+ | 压力测试 / OOS；奇异暂缓 | 分阶段决议 | 封闭 |
| 6 | F+ | 买方 / 全宇宙 / 升 PAPER | 长史盘口 + 人工评审 | 封闭 |
| 7 | DQ / 纸面帽 / 官历·因子 | 低优抛光 | — | 延后 |
| — | 写正式 `paper_book`/seats / 解 SUSPENDED | 明示 + Gate 人工 | **硬围栏** | 封闭 |

**默认下一动作**：**停**（期权积样）。VP 旁轨若续开：明示 **开 VP-1B-0**（按 `VP_PHASE1B0_SPEC.md`）；或够样后确认 **F2**（一刀一开）。

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
| `docs/audit/VIRTUAL_PORTFOLIO_*.md` | VP Phase 0 审计四件套 |
| `docs/audit/VP_PHASE1_GO_NO_GO.md` | VP Phase 1 准入裁决 |
| `docs/audit/VP_PHASE1B0_SPEC.md` | 1B-0 实施规格（读口/inbox/权限） |
| `docs/audit/LOCAL_WIP_INVENTORY.md` | 本机未入库文件清单（含 Vol-V1.4） |
| `docs/audit/VP_PHASE1_{ACCOUNT,FILL}_RULES.md` | 1A 账户/成交规则 |
| `docs/audit/PAPER_ANOMALY_TRACKER.md` | Paper 异常专项（不混入 VP） |
| `docs/VOLATILITY_ENGINE_SPEC.md` | Vol-V1.4 规格（v2 审计吸收） |
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

### Vol-V1.4（2026-11-23）

- **做了**：吸收 v2 审计进规格；落地 IV 面 / Black-76 Greeks / Sticky Strike·Delta Shadow Greeks / 日报告（Shadow only）  
- **产物**：`research/options/volatility/{iv_surface,greeks_engine,shadow_greeks,daily_vol_report}.py`；`lab/research/run_vol_engine_daily.py`；`lab/research/volatility/vol_engine_daily_latest.json`；`docs/VOLATILITY_ENGINE_SPEC.md`  
- **验证**：`pytest tests/test_vol_engine_v14.py` 绿；CF 2026-11-23 快照跑通（surface ok≈61，ATM Shadow 腿 6）；`live_trading=false` / `promote_path_a=false`  
- **风险/未做**：**上述产物仍为本地 WIP，未合 GitHub main**（2026-11-23 清库确认）；未开 SABR/VRP/奇异；F2 不够样  
- **建议下一刀**：**停 · 积样本**；或明示 **Vol-V1.4 入库 PR** / **F2** / **Vol-V1.6**  

### 档案同步 + 本地 WIP 登记（2026-11-23）

- **做了**：登记 `LOCAL_WIP_INVENTORY.md`；纠正 Vol-V1.4「已完成」≠「已上 GitHub」；同步个人库 / Notion Memory·About / 第二大脑卡片与主台账  
- **产物**：`docs/audit/LOCAL_WIP_INVENTORY.md`；个人库 `cta-path-a/UPGRADE_PLAN.md`  
- **验证**：`origin/main` tip=`98d9790`；本机 `main` 对齐；Vol 路径未出现在 `git ls-tree origin/main`  
- **风险/未做**：未提交 Vol WIP；未开 1B-0  
- **建议下一刀**：**停**；或明示 **开 VP-1B-0** / **Vol-V1.4 入库** / 积样等 **F2**  

### 积样决议 + settle BT 快照（2026-11-23）

- **做了**：用户决议「先积攒数据，后续方案入库，够样再升级」；§4 重写为积样门槛 + 候选刀序；settle BT `--settle-only` 重跑入库  
- **产物**：本文件 §1/§4；`credit_vertical_latest.json`（WARN · n=17 · 总 PnL≈−2185）；个人库/Notion 姿态同步  
- **验证**：gate 仍 `ready=false`（CF=2/10，SR/MA=1/5）  
- **风险/未做**：未开 F2 / Vol-V1.5+ / 正式层；日积仍依赖 Tq 凭证  
- **建议下一刀**：**停 · 只积样**；够样后确认 **F2**  

### VP-Phase0（2026-11-23）

- **做了**：按 ChatGPT Virtual Portfolio 1.0 规格只读审计；登记隔离边界、依赖、数据字典、风险；吸收为轨 VP  
- **产物**：`docs/audit/VIRTUAL_PORTFOLIO_{AUDIT,DEPENDENCY_MAP,DATA_DICTIONARY,RISK_REGISTER}.md`；本文件 §1/§2/§3.7  
- **验证**：未改代码 / 未写 `paper_book` / 未开 Phase 1；F2 gate 仍锁定  
- **风险/未做**：账户模型与保证金仍缺；现有 paper 异常（如 P 止盈）只登记不修；决策表待你确认  
- **建议下一刀**：**停**；审阅后明示 **VP-Phase1**，或积样后确认 **F2**  




### VP-1A-merge + 1B-0-SPEC（2026-11-23）

- **做了**：`feature/vp-phase1a-fix` merge 最新 main；pytest 17 绿；起草 1B-0 规格（真源=`l1_report.json` 根路径、inbox、`SIGNAL_READ_ALLOWED` 拆分）；Draft PR → 审查合入  
- **产物**：`docs/audit/VP_PHASE1B0_SPEC.md`；本表 / ROADMAP 同步  
- **验证**：`pytest tests/test_vp_phase1a.py` 17 passed（merge 后）  
- **风险/未做**：**未**实现 1B-0；未改权限代码；投影陈旧/无文件锁/FIFO 口径仍挂账  
- **建议下一刀**：**停**；或你明示 **开 VP-1B-0**（按规格）；期权轨仍积样等 **F2**  

### VP-1A-Fix（2026-11-23）

- **做了**：ACC-01 查询只读/显式 rebuild；ACC-02 RESEARCH_ONLY+AUTO fail-closed；补测；Desk 状态展示  
- **产物**：`virtual_portfolio/permissions.py`；引擎拆分 load/compute/rebuild；VP_PHASE1A_FIX_REPORT.md  
- **验证**：pytest tests/test_vp_phase1a.py 17 passed  
- **风险/未做**：未开 1B-0；instruments 哈希弱绑定；无文件锁  
- **建议下一刀**：**停**；分支推送后人工复核；明示再开 **1B-0**  

### VP-1A-Acceptance（2026-11-23）

- **做了**：按 GPT 下文只做 1A 独立验收；标出读路径写投影、保证金三态未产品化、测试缺口；确认 GitHub 未同步  
- **产物**：docs/audit/VP_PHASE1A_ACCEPTANCE_AUDIT.md  
- **验证**：复跑 pytest tests/test_vp_phase1a.py 10 passed；未改业务代码  
- **风险/未做**：ACC-01/02 未修；1B-0 未开；仍未 push  
- **建议下一刀**：**停**；推送或明示开 1A 修补 / 豁免后 1B-0  

### VP-Phase1A（2026-11-23）

- **做了**：按 GPT 批准落地独立账户/ledger/手工成交/版本化保证金表/Desk 查询页；污染与核算测试  
- **产物**：irtual_portfolio/；configs/virtual_portfolio/；desk/virtual_portfolio_panel.py；	ests/test_vp_phase1a.py；docs/audit/VP_PHASE1A_*.md  
- **验证**：pytest tests/test_vp_phase1a.py → 10 passed；F2/paper/l1 哨兵哈希不变  
- **风险/未做**：保证金为研究估计（未核实）；未接 L1；未开 1B/2；未修 PA-001  
- **建议下一刀**：**停**；审阅后明示 **VP-Phase1B**，或积样确认 **F2**  

### VP-Phase1-GoNoGo（2026-11-23）

- **做了**：按新 GPT 分享复核 Phase 0；锁定账户/成交规则；Paper 异常专项独立；给出 1A CONDITIONAL GO / 完整 Phase1 NO-GO  
- **产物**：`docs/audit/VP_PHASE1_GO_NO_GO.md`；`VP_PHASE1_ACCOUNT_RULES.md`；`VP_PHASE1_FILL_RULES.md`；`PAPER_ANOMALY_TRACKER.md`  
- **验证**：对照 `universe`（无 margin_rate）、`research_cost`（next_open）、`rule_lock`（data/ 忽略）、F2 `ready=false`；无业务代码  
- **风险/未做**：污染防护测试尚未存在（1A 验收硬门槛）；保证金静态表未建  
- **建议下一刀**：**停**；确认后开 **VP-Phase1A**；或积样确认 **F2**  

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
