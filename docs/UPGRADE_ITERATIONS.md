# CTA Path-A · 升级计划（合并权威版）

**同步日期**：2026-11-23（VP-1A 已合 GitHub main · 1B-0 规格已备 · F2 仍锁定 · **新登记 R 审计升级轨 R0–R16 + carry 袖套 K0–K7，优先级排在 F2 之前**）  
**仓库**：`d:\AI\cta-path-a`  
**本文件角色**：**唯一刀序权威**。细则仍分散在子文档；状态与优先级以本表为准。

---

## 工作方式（固定）

1. **标记**：本文件为总状态；期权细则 `docs/options/ROADMAP.md`；套利细则 `docs/ARBITRAGE_VOLATILITY_UPGRADE.md`；可信度细则 `docs/PHASE2_AUDIT_DECISIONS.md` + `docs/P0_CODE_AUDIT.md`；**R 审计升级轨细则 `docs/UPGRADE_R_TRACK.md`（carry 袖套另见 `docs/CARRY_SLEEVE_R14.md`，证据依据见 `docs/STRATEGY_EVIDENCE_REVIEW.md`）**。  
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
| `docs/UPGRADE_R_TRACK.md`（AWS Quick 全项目审计，2026-11-23） | 回测可信度修复 → 降回撤 → 新收益来源 → 治理（R0–R16） | **吸收为轨 R（审计升级）** | 优先级排在 F2 之前；🔒 刀（R1–R7）改正式 KPI，需磊签字；ID 与「R 研究台旧项」（P1–P4/A1–A3）不同 |
| `docs/CARRY_SLEEVE_R14.md`（2026-11-23） | R14 期限结构 carry 独立袖套细则（K0–K7） | **并入轨 R 的 R14** | Research → Shadow；K0–K2 只动数据层，可与 R0–R7 并行；不写 `paper_book` |
| `docs/STRATEGY_EVIDENCE_REVIEW.md`（2026-11-23） | 量化与期权策略证据综述（37 个来源） | **依据文档** | 不开刀；R9–R14 开刀前先读对应章节 |

**合并原则**：可信度 > alpha；样本不够不开刀；观察续跑 ≠ 开新刀；正式层需明示。

---

## 1. 当前姿态与锁定下一刀

**姿态（2026-11-23）**：**VP-1A** 已上 main；**VP-1B-0 已落地（只读收件箱）· 停**；不自动开 1B-1/F2；期权轨继续积样。

### 1.0 轨 R（审计升级）优先级 · 新登记 2026-11-23

- **结论**：审计发现正式回测引擎至少有 5 类错误（分钟线合约错配造成 3 笔假止损、夜盘交易日归属、跳空止损按止损价成交、组合帽不计已有持仓、模拟账本缺日线兜底），现行 +5.78% / DD 6.74% 不可信。详见 `docs/UPGRADE_R_TRACK.md` §0–§2。
- **优先级**：**轨 R 阶段 A（R0–R7）排在 F2 之前**。F2 仍按原门槛等样本，不受影响；但说「继续/升级」时，**先念轨 R 的下一刀，再念 F2 是否够样**。
- **下一刀候选**：R0–R7 阶段 A 已由 R7b 收口（方案 B 账本、正式 v14 窗口末 11-25）；阶段 B（R8+）封闭，待磊明示。R3 核对后磊决定 **R6 提前到 R4 之前**；R6a/b/c、R4（组合帽计入已有持仓）、R4b（缩手后补手）、R5a（日报信号与回测同口径）与 R5b（模拟账本共用回测持仓引擎）已完成，R7 未开。
- **硬围栏（轨 R 追加）**：R1–R7 完成前不提交 `historical_backtest_latest.json`、`paper_book_latest.json`；R7 重跑并签字后才更新 `configs/formal_rule_lock.json`；结果变差也不回退修复。
- **对齐**：§3.2「组合帽 / next_open 纸面完全对齐」原为低优延后，现由轨 R 的 R4、R5 接手。

**已完成旁轨**：**VP-Phase0**；**VP-Phase1-GoNoGo**；**VP-Phase1A**；**VP-1A-Acceptance**；**VP-1A-Fix**；**VP-1B-0-SPEC**；**VP-1B-0**；**VP-1A → main**  
**Vol-V1.4**：已**轻量入库** GitHub（Shadow only · **结果弱 · 不晋级**）；见规格头注 + `LOCAL_WIP_INVENTORY.md`。  

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
| ✅ | **VP-1B-0 实现** | **完成 · 停** | 只读 L1→inbox；`SIGNAL_READ_ALLOWED`；未开 `SIGNAL_INGEST` |
| 🚫 | 1B-1（订单意图） | NO-GO | 须另批；不自动进入 |
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
| **V 波动引擎** | **Vol-V1.4** | 定价 / IV 面 / Greeks / Shadow Greeks | **已归档 · 弱结果 · 不晋级** | 封闭 |
| **V 波动引擎** | Vol-V1.5–V2.0 | VRP/TVS/执行成本/奇异/OOS | **封闭** | 未开放 |
| **S 会话** | Session brief | 多时段盘中 brief | 交 Grokbot | 本仓不做 |
| **R 研究台旧项** | P1–P4 / A1–A3 | PBO/LSP/Gamma/组合风险/轻量 ML / 主力映射 | **主路径完成** | 封闭 |
| **R 研究台旧项** | 官历/因子注册/聚类 | `UPGRADE_PLAN`「下次剩余」 | **低优延后** | 封闭 |
| **R 审计升级** | **R0–R7（阶段 A）** | 冻结基线 → 假止损 / 夜盘归属 / 跳空止损 / 组合帽 / 账本对齐 / 换月复权 → v14 重跑签字 | **优先于 F2** | **R7b 完成（本地，未 push）· 阶段 A 收口 · PBO 闸门未过** |
| **R 审计升级** | R8（本金 + 极端风险过滤，磊指定的研究项） | R8a 本金网格 100k–1M；R8b 实际本金 100 万下 F1 名义 / F2 ATR 突增过滤；预注册 7 组 | **研究完成 · 分支 `r8-equity-filter`（未合入）· 无组通过预注册标准；后续：候选已冻结（tag `r8-cand-freeze`）、OOS 预注册已提交、长样本数据覆盖报告已出；长样本 9 组已跑完（`archive/R8/OOS_VERDICT.md`）：A/B/C 均未通过，B、C 均不优于 A；30 万诊断档已跑（三组均「不适用」）；`r8-equity-filter` 已快进合入 main（`f113c33`），`r8-gross-equity` 打 tag 归档；收尾前三项只读归因已做（桥接 / 亏损 / 信号层，`R8_CLOSEOUT.md` 附录 A.5）：信号层判定「无优势」→ 问题在信号层，不追加组合帽账户；停在等磊看诊断结果（管道未实现、shadow 未开）** | 不改正式层 |
| **R 审计升级** | R8–R12（原阶段 B：长样本入口等） | 长样本入口、出场预注册 5 组、风险预算生效、波动目标 + 回撤刹车、品种池 | **封闭** | 依赖 R7 |
| **R 审计升级** | R13（阶段 C） | 席位因子长样本验证（回补 2019+） | **封闭** | 依赖 R8 |
| **R 审计升级** | **R14 / K0–K7（阶段 C）** | carry 独立袖套：分月库 → 可交易曲线 → 持有指数 → 预登记 10 试验 → 闸门 → Shadow | **封闭** | K0–K2 可与阶段 A 并行（需明示）；K4 起依赖 R6、R8 |
| **R 审计升级** | R15–R16（阶段 D） | 试验登记强制化 + DSR 真实 n_trials；晋级门槛写进代码 | **封闭** | 可随时插入 |

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
| **Vol-V1.4** | **已轻量入库 · 不晋级** | Shadow only；人工反馈偏弱；禁作交易/F2 依据 |

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
| **1B-0 规格** | **完成** | `VP_PHASE1B0_SPEC.md` |
| **1B-0 实现** | **完成 · 停** | 报告 `VP_PHASE1B0_REPORT.md`；不进 1B-1 |
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
| — | **VP-1B-0** | 信号只读 + inbox + `SIGNAL_READ_ALLOWED` | 已明示并落地 | **完成 · 停** |
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
| `docs/UPGRADE_R_TRACK.md` | 轨 R 细则：R0–R16 每刀的证据、改法、测试、验收（2026-11-23 审计） |
| `docs/CURSOR_PROMPTS_R0_R1.md` | R0、R1 可直接粘贴给 Cursor 的执行指令（一次一段） |
| `docs/CARRY_SLEEVE_R14.md` | R14 carry 袖套细则：原型结果、数据缺陷 D1–D4、K0–K7、闸门 |
| `docs/STRATEGY_EVIDENCE_REVIEW.md` | 证据综述：哪些量化/期权策略有长期证据、在中国是否成立（37 个来源） |
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

### R8 本金 + 极端风险过滤（研究，分支 `r8-equity-filter`，2026-11-25，本地未 push、未合入）

- **做了**：第 0 步静态检查（`archive/R8/static_sizing.md`）；PREREG 单独提交（7 个新增组，n_trials=18）；`--equity` / `--filter-unit-risk` / `--filter-atr-spike`（仅带 `--out` 生效，默认关，正式输出键集不变；`research/execution/entry_filters.py`、`AdjustedSeries.atr_n`）；R8a 本金网格 + R8b 三个过滤组，全部 live 运行 + Stress，且在同一冻结快照上离线重放与 live 逐位一致。结果表 `archive/R8/results_table.{md,json}`，进度 `archive/R8/progress.md`。
- **结果**：R8a Base/Stress：E100k −2.16/−3.46、E300k +8.75/+1.60、E500k +3.22/+2.14、**E1000k（实际本金）+4.97/+3.48**，不随本金单调；E1000k 的 PBO 0.857、走步 3/5。R8b：**F1 / F2 / F1F2 均未通过预注册标准**。F2、F1F2 满足第 1–5 条（Base +10.94/+11.00、Stress +9.03/+9.43、回撤 ≈3.1%、PBO 0.386、走步 5/5），但第 6 条不满足（被过滤交易前半年 −6.5k 元、后半年 +3.1k 元）；DSR(18) 0.34。F1 只碰 CU/AG/AU，对结果几乎无影响。
- **事后描述（不改判定）**：F2 相对对照的约 +58k 元价格盈亏里，被直接过滤的 20 笔合计仅 −3.5k 元；其余来自路径变化（腾出名额后的新交易），其中单笔 FU 2026-09-24 就 +40.3k 元（约 70%）。
- **验证**：全量 pytest 554 passed（新增 25）；`base` 与根目录正式结果逐项一致（勘误：输入差异不止 `oi`，还有窗口末日 36 处盘后版本字段，见 `archive/R8/PREREG_ERRATUM.md`）；E1000k / F2 出场审计 0 不符（信息性）；E300k/E500k/E1000k 与上一轮 B300/B500/B1000 数字一致。
- **风险/未做**：单个 216 天窗口、8 个组、样本内；没有组在预注册意义上通过；正式层（`execution_rules.json` / `universe.json` / 规则锁 / paper_book）未动；`historical_backtest.yml` 仍暂停。
- **建议**：停。是否另行预注册样本外验证（例如 observe 袖套按 100 万 + F2 做 shadow）由磊决定。

### R8 后续：候选冻结 + 样本外预注册 + 长样本数据覆盖报告（分支 `r8-equity-filter`，2026-11-25，本地未 push、未合入；**只做到步骤 5，停在等磊确认**）

- **做了**：①冻结 A（E1000k）/ B（A+F2，只作对照）/ C（A + 月度品种池 N_i ≤ 25%×E），`archive/R8/CANDIDATE_LOCK.md` + tag `r8-cand-freeze`（含规则锁 / universe / 数据哈希，A 输入快照入库）；②`archive/R8/PREREG_OOS.md` 单独提交：10 个自然年分折、Base/Stress 同 R8、DSR n_trials=30（18+3+9，30 万诊断 3 组不计）、A 通过 / B 优于 A / C 优于 A 的判定、30 万诊断档、前向 shadow；③`archive/R8/LONG_COVERAGE_REPORT.md`（只读侦察，没跑任何策略）。**没有跑长样本、没有启动 shadow，C 没有代码。**
- **发现（影响长样本的含义）**：`historical_backtest.py` 没有长样本入口；本地合约级数据只有 2024-09 以后；席位只有郑商所/上期所 2018+、升贴水只有 2025-10 以后；乘数/手续费只有当前值；大商所 10 个品种有两段缺 `settle`（2017-11~2018-03、2019-12~2020-07）；FU 2016~2018-06 有 450 根零成交 bar；5 个品种晚于 2016 上市（SP/EG/SS/EB/SA）。所以长窗口只能是**“A 的核心”（基础模式）**，不能检验完整 A 的席位 / carry / 换月复权层。C 静态估计：100 万下基本等于去掉 AU（118/120 月）和 CU（77/120 月）；30 万下有色板块有 44/120 个月为空。
- **验证**：冻结后全量 pytest 554 passed；`execution_rules.json` / `universe.json` / `configs/formal_rule_lock.json` / `historical_backtest_latest.json` / `paper_book_latest.json` / README / `historical_backtest.yml` 与 main 的 diff 为空。
- **风险/未做**：预注册 §9 的数据模式、缺口处理、乘数/手续费套用当前值待磊确认后写入附录 1；shadow“6 个月或 30 笔”被我解读为“且”（待确认）；A/B 的 216 天结果与 C 的设计动机都来自已看过的窗口。
- **建议**：停，等磊对 `LONG_COVERAGE_REPORT.md` §5 的 4 项确认；确认前不做附录 1、不做长样本入口、不跑组。

### R8 长样本数据可行性检查（只读，分支 `r8-equity-filter`，2026-11-25，本地未 push、未合入；**停在等磊决定**）

- **做了**：磊确认 4 项后，抓取四家交易所里本池涉及的三家（上期所 / 郑商所 HTTP；大商所经浏览器同源会话，官网对脚本返回 412）2016-01-04~2025-12-31 逐合约日行情，独立缓存 `archive/R8/raw_contract/`（`.gz` 不入库，只入库 `MANIFEST_*.json` 与聚合哈希）；用引擎 `build_main_map` 在官方数据上重算主力；与本地 2024-09 以后合约 bar 交叉验证；换月跳空（ATR14）；乘数变更核对。报告 `archive/R8/LONG_FEASIBILITY_REPORT.md`。**没跑任何策略、没写附录 1、没实现入口。**
- **结论**：按预先写死的标准，**27 个不能算全部齐全**：FU 默认起点主力可确定仅 79.77%（移到 2018-10-16 后 99.89%）；“每日都能确定主力”的字面读法只有 SA 通过（26 个品种有 1–12 个未识别日，主要是缓存连续序列在 9 个共同日期的毛刺），≥99% 容忍读法下 26/27 + FU 移起点后通过。缓存连续序列**未复权**（简单拼接），换月跳空中位 0.51 ATR14、P90 2.81、最大 17.34，>1 ATR 417/1248 次。乘数 2016–2025 唯一真实变更是 FU 50→10 吨/手（2018-07-16，上期所 2018-06-26 公告），官方成交额反推逐日复现该台阶，FU 起点晚于变更日故无需分段；其余品种逐日反推 0.9958~1.0075。交叉验证：价格/settle 基本逐位一致（51,507 对），volume/OI 有 0.8–3.8% 行不一致，且 volume 全部是本地 ≤ 官方（单向）。
- **验证**：只读；脚本与结果 JSON 入库；全量 pytest 与受保护文件 diff 见本次提交说明。
- **风险/未做**：25 个品种的乘数只有“数据反推 + 现行规格表”，没有逐条交易所公告；SHFE/CZCE 未抓 2019-04-22（引擎日历本来没有这天）；fee/tick 用当前值（已知偏差）；volume/OI 单向偏差是否接受、FU 取舍、字面/容忍读法、settle 缺失月是否改“官方 settle 优先”，均待磊定（报告 §8）。
- **建议**：停，等磊对 `LONG_FEASIBILITY_REPORT.md` §8 的决定；之后才写附录 1，再做入口与 C。

### R8 跟进：主力字面重判 + volume/OI 与本地数据核对（只读，分支 `r8-equity-filter`，2026-11-26，本地未 push、未合入；**第 3 项出现不一致，停在等磊**）

- **做了**：磊对可行性报告的 6 项决定到位后，按其顺序先做第 1、3 项（`archive/R8/MAIN_RECOMPUTE_REPORT.md`）：官方逐合约数据 + 引擎规则字面重判（未识别日沿用前一日主力）；本地 volume 偏低原因；换月规则是否依赖 volume/OI；官方 vs 本地的对等主力/换月比较。**没写附录 1、没实现入口、没跑长样本。**
- **结论**：26/27 品种仍有未识别日，共 135 个品种日、38 个日期（SA 为 0）；原先“≥5 个品种的 9 个共同日期”表述有误，≥5 只有 7 个、9 个对应 ≥4（已更正），这些日子新浪连续序列是盘前快照（2024-09-25 本地连续与本地逐合约逐位相同、官方终值不同）。换月规则纯价格匹配、不依赖 volume/OI，base 模式也不读；但对等比较**不为 0**：2024-09~2025-12 有 17 个品种日主力不同、9 次换月事件不一致（2018~2025 扩展区间 135/19），原因是快照口径 + 薄合约 1 tick 误匹配；官方数据全样本 1256 次换月里有 70 次三日内原路换回（35 次新主力成交量 <5%）。更正：本地存储还读 `.cache/sina`，有 1122 个合约、最早 2018-01，该来源与官方 volume/OHLC 偏差较大（2018–2019 volume 不一致约 40%），支持长样本不与本地混用。
- **验证**：只读；全量 pytest 与受保护文件 diff 见提交说明。
- **风险/未做**：是否给官方路径加成交量守卫（登记为附录 1 偏离）待磊定；附录 1、入口、C、长样本均未开始。
- **建议**：停，等磊对 `MAIN_RECOMPUTE_REPORT.md` §4 的选择。
- **后续（磊选方案 2 成交量守卫，5%，仅官方路径，2026-11-26）**：已做阈值敏感性 + 加守卫后的官方对本地比较（`archive/R8/GUARD_SENSITIVITY_REPORT.md`，只读、不跑策略、不计 DSR）。5% 档 <5% 的来回换月 35→0，未识别品种日 135→171；6 条\"正常换月未复现\"三档相同，是 3 个两跳链（跳过极薄合约，到达日期不变）；比较在本地覆盖不全的口径下出现 22 个快照日以外差异（本地缺当日最大成交合约），在本地覆盖该合约的日子里只剩 2024-09-25 快照日 15 个。**触发停止条件，停在等磊确认；附录 1、入口、C、长样本均未开始。**

### R8 长样本（附录 1 → 入口 + C → 回归 → 9 组运行 → `OOS_VERDICT.md`；分支 `r8-equity-filter`，2026-11-26，本地未 push、未合入；**长样本已跑完，停在等磊**）

- **做了**：磊确认三项后做 216 天窗口只读缺口检查（A/B 冻结交易均不受影响，`WINDOW_GAP_REPORT.md`）；提交附录 1（`APPENDIX_1.md`，早于任何长样本运行）；实现长样本入口（`archive/R8/long_sample.py`、`historical_backtest._simulate_cfg(long_sample=…)`，官方逐合约拼接主力序列 + 5% 成交量守卫，仅官方路径）与 C（`entry_filters.MonthlyNotionalPool`，只用构造数据测）；回归：216 天本地路径 E1000k、F2 逐位复现冻结结果（`tests/test_r8_long_sample.py`）；跑 9 个正式组（A/B/C × 80/100/120 万，Base + Stress，`archive/R8/OOS/<组>/`，`run_oos.py`，一次跑完、重放一致性检查通过），评估 `_evaluate_oos.py` → `OOS_VERDICT.md/.json`。
- **结果**：A、B、C **均未通过**，B 不优于 A，C 不优于 A。100 万档 Base/Stress：A −20.4/−26.7、B −30.2/−45.0、C −16.8/−52.0；最大回撤 Base 40–48%、Stress 43–59%（标准 ≤10%）；走步正折 A 4/10、B 3/10、C 0/10。C 的三档 Stress 极差（10.9pp）小于 A（25.6pp），但 C 本身不通过且 100 万档低于 A 25pp。被过滤交易为负的年份 6/10（需 ≥7）。降级规则未触发（识别率 <99% 的品种 0 个，无空板块）；C 池 117 个月，有色为空 0 个月，settle→close 兜底 0 条。DSR(30) 均 ≤0.007（只报告）。
- **验证**：全量 pytest 568 passed；受保护文件（universe / execution_rules / formal_rule_lock / historical_backtest.yml）与 main diff 为空；2025-12-31 之后无任何加载；未写 paper_book / 席位 / 正式 BT。
- **风险/披露**：预热在窗口内消耗（2016 折不足一年）；成交取主力合约（≠216 天日历前月口径）；守卫仅官方路径；乘数/手续费用当前值套全部年份；未跑 30 万诊断档与 shadow（须在 `OOS_VERDICT.md` 提交后、且经磊明示）。
- **建议**：停，等磊决定是否开 30 万诊断档 / shadow，或结束 R8。
- **后续（磊明示，2026-11-26）**：①30 万诊断档已跑（`DIAG300K_REPORT.md`，一次跑完）：A300k/B300k/C300k Base −23.1/−15.7/−43.8、Stress −43.2/−54.6/−64.3，Stress 回撤 46/58/66%，标签均「30 万不适用」；C300k 有色全不在池内的月数 76/117；只报告，不计 DSR。②`PREREG_SHADOW_300K.md` 已提交（C@300k 主对象、A@300k 参照，原 A/B/C@100 万并行；完整模式、不进正式账本；6 个月且 30 笔，12 个月不足标低统计效力；账户回撤 >15% 即停；**未启动**，需官方数据管道连续 5 个交易日正常）。③`R8_CLOSEOUT.md` 已写；分支合入**未执行，停在等磊确认**（`r8-equity-filter` 相对 main 可快进；`r8-gross-equity` 打 tag 归档、不合入）。④官方数据每日管道**只出了设计**（`docs/OFFICIAL_DATA_PIPELINE_DESIGN.md`），未实现，等磊确认。
- **收尾指令（磊，2026-11-26）**：①`r8-equity-filter` 快进合入 main（核对：全量 pytest、受保护文件 diff 空、216 天逐位复现）；`r8-gross-equity` 打 tag `r8-gross-equity-archive` 不合入；shadow §9 五个默认读法接受；管道 7 项决定（本机任务计划、`D:\AI\data\official\`、Playwright 锁版本、种子校验哈希、本地告警文件 + Windows 通知、日摘要不入 main）；`daily.yml` 的 `test_vol_engine_v14.py` 失败另修。②三项只读归因（解读规则 `d008eb2` 先于 2.3 提交；`archive/R8/ATTRIB/`，`R8_CLOSEOUT.md` 附录 A.5，不改判定、不计 DSR）：桥接——引擎 + 官方数据在 2026 年窗口 +5.38/+3.11 ≈ 冻结 +4.97/+3.48，三因素方向不一互相抵消，另有一个未解释的 +13.2/+9.4 交互单元；亏损——2017–2021 −296k（2019–2021 占 97%），2022–2025 +87k，亏损面宽、不是少数品种；大商所 settle 缺口时间上重叠但不读 settle，非因果；"持仓数已满"差距大部分来自模式（108→333）；信号层（Stress，(b)）：全部信号平均每笔 R −0.065 [−0.132, +0.001]，**判定「信号无优势」**，A 实际成交 −0.039 优于全部信号，被板块挡掉的更差（−0.152），"取最强"选中不低于落选 → 不追加组合帽 / 风险预算账户，"挑选规则存疑"不触发；对账：1,710/1,675 笔与 A 逐笔一致。③风险预算账户草案 `docs/RISK_BUDGET_ACCOUNT_DRAFT.md`（仅 docs/）。**停在等磊看诊断结果；管道未实现、shadow 未开。**
- **诊断确认 + 138 笔核查（磊，2026-11-26 晚）**：①判定「信号无优势」「问题在信号层」确认，不追加风险预算账户（草案标「不启用」）；`R8_CLOSEOUT.md` 加「现有规则在任何本金、组合帽、选品配置下都不进入实盘」，tag `r8-closed`（`efc49b9`）。②138 笔核查（只读，`archive/R8/TRADES138_REPORT.md` + `TRADES138_LIST.md`，不比较收益、不计 DSR）：官方/主力/完整比本地/日历前月/完整多出的 68 笔里 **52 笔是 A 的成交时质量门（日历前月合约的 delivery 标记）拦下的**（35 笔禁入窗口、17 笔 6–10 个交易日临近交割），B 的行情条无任何标记故不拦，其余 16 笔是持仓路径连锁；信号层 A/B 逐日一致；席位 / 升贴水数据 A/B 逐格相同；入场时无静默缺失（席位数据不足 60 日的跳过是按设计且有标记）。更正 A.5.1：桥接里"本地/主力开盘/完整"没去掉质量门（本地 bar 上的标记仍在），+13.2/+9.4 那格是质量门被一起去掉，不是数据交互。三个设计层疑点（`near_delivery` 6–10 日也拦；升贴水对与官方主力不对齐、`MONTHS` 表只含主力月；长样本引擎无成交质量门）**均未确认是 bug，未开 issue、未改代码，等磊裁定**。**停在等磊；管道（步骤 3）与 2010–2015 覆盖查询（步骤 4）未开始。**

### R7b v14 正式写入（阶段 A 收口，2026-11-25，本地未 push）

- **做了**：先做候选冻结输入 + HEAD 重放（56 笔逐笔一致、216 天权益逐日一致，−1.068 / 7.623 / 56 复现）。按磊确认的方案 A：正式窗口末 11-25（`historical_backtest_latest.json`，v14，−1.721% / gross +0.938% / DD 8.232% / 57 笔；审计 0 不符；缓存与空缓存重放一致）；方案 B 账本根目录 `paper_book_latest.json`（asof 11-25，盯市权益 196,557.68，无持仓、P 待开 1 手；旧桌面版归档 `archive/R7/paper_book_legacy_desk_20261125.json`，`pre_R7` 未动）；`formal_rule_lock.json` 写入 end=2026-11-25、git_commit=18c7135、input_snapshot_sha256=016deed…；README KPI 标记块由 `render_readme_kpi.py` 生成；`test_proxy_positions` 改为检查代理袖套 ID。
- **与候选的差异**：窗口滚动（+11-25，−12-31）；重叠 215 天权益逐日相同；11-25 当天 −1,305.36 元（P 空 1 手 11-23 入场 8278，11-25 止损 8438.29，R=−1，即第 57 笔）；回撤 7.623% → 8.232% 由该日造成。PBO：0.386 为**修复前引擎**（`ee4476b` 提交的矩阵，矩阵 T=214，CSCV 实用 208 个观测）；0.729 为 **v14**（矩阵 T=215，CSCV 实用 208）。两者都是 S=8 组（C(8,4)=70 组合）、K=11 个试验。**不可直接比较**：敏感性曲线整体变了（组数 4/6/8/10/12/16：修复前 0.17/0.25/0.39/0.41/0.28/0.45 → v14 1.00/0.95/0.73/0.89/0.94/0.80），不是分组选择造成的；v14 主分组 0.729 恰是各组数里最低的。磊于 11-25 决定接受现状，**逐项核对留到 R8**；闸门 ≤0.3 未过。DSR：签字报告 0.043；正式结果内验证块 0.0355（n_trials=11）；scorecard 试验矩阵口径 0.0927。三者均远低于阈值，结论不变。
- **验证**：全量 pytest 529 passed（PYTHONUTF8=1）；`daily_update --dry-run` 不改根文件（4 个受保护文件哈希不变，paper noop）。
- **风险/未做**：PBO 0.729 与 scorecard `human_approval` 硬闸未过，**未晋级**；未 push（15:30 CI 覆盖风险，push 前需 fetch/rebase 并暂停 daily.yml/historical_backtest.yml）；`docs/R_TRACK_HANDOFF.md` 已搬回。
- **建议**：阶段 A 收口，停；推送与 PBO 结论待磊决定。R8+ 仍封闭。

### R7a v14 候选正式重跑 + 签字报告（2026-11-24）

- **R7a-D（6493f4e、198642a，磊已核对）**：main_map 候选改为按上市日历逐日取（月份 = public_curve.MONTHS ∪ 交割规则月份）；合约读取统一走 ContractStore（缓存或冻结合约包）；快照内嵌合约日线 `contract_bars`；正式运行先预取全部上市候选合约；测试改用冻结分钟线 fixture。11-23 快照新旧 main_map 0/7425 天不同，空缓存下用合约包 replay 与原结果逐位相同（−0.769 / 7.469 / 56）。
- **做了（第 4 步）**：`SCHEMA_VERSION = "cta-backtest-v14-execfix"`；`n_trials_census` 取以下三者最大值：1+已归档参数数、PBO 矩阵试验数、`archive/shadow_strategy_*.json` 行数（当前 5 / 11 / 8 → **11**，R0 时按 5）。结果和验证包里写入 `n_trials_breakdown`，DSR 用新 n_trials 计算。`run_formal_scorecard.py` 的 `code_schema` 改为取自结果，不再写死 v13。`test_legacy_reproduces_ee4476b_…` 改名为 `test_legacy_path_kpi_lock_and_fix_has_no_cross_delivery`（注释同步，断言不变）。新增 `scripts/render_readme_kpi.py`（README KPI 标记块，本次只输出预览 `archive/R7/README_kpi_preview.md`）。`test_proxy_positions` 只写了修改方案（见报告第 9 节）。
- **候选（第 5 步，数据到 11-24）**：Base 净 **−1.068%** / 毛 1.575% / 回撤 **7.623%** / 56 笔 / 胜率 33.93% / 0.03R / 成本 5286；Stress 净 −1.674% / 回撤 7.032%。PSR 0.460、DSR 0.043（n_trials=11）、PBO 0.386；WF 5 折正 Sharpe 占比 0.8，最后一折 −3.23。预取：619 个候选合约中 247 个已缓存，请求 372 次，8.1 s，成功 364、失败 8（EG/EB/JD2711、AU 单月均返回空数据）；缓存从 353 增到 615 个文件。
- **核验**：出场审计 checked=52、不符 0（gap_through_target_conservative=1）；`.cache/contracts` 移走后，只用快照和合约包 replay，结果字段与候选逐项一致（只有 curve_coverage 来源标签和 ifind_slot 不同）；离线重跑的 Base 和 Stress 也一致；缓存已恢复，615 个文件。方案 B 账本 `archive/R7/paper_book_candidate.json`：盯市权益 197,863.04、持 P 空 1 手（11-23 入场 8278）、无 pending；旧根账本复制到 `paper_book_legacy_pre_R7.json`。日报 dry-run：selected=[]=pending，根目录 9 个受保护文件哈希不变。
- **三方对比**：旧正式 +5.777 / 6.739 / 66 → 冻结重放 −0.769 / 7.469 / 56 → 候选 −1.068 / 7.623 / 56。新数据（旧引擎，旧正式 → R0）+1.48pp；引擎修复（R0 → R5b，同一份数据）−8.02pp；新增 11-24 一天 −0.30pp（P 空盯市 −600 元）。D 的预取让 8 笔从 continuous_proxy 改为合约成交（出场日和 R 值不变，+1.60 元）。在同一份缓存上 main_map 新旧算法 0/7452 天不同。
- **发现并修复**：当天刚播种的 R5b 账本（asof 等于当天、没有 base）在日报里走 no-op 分支，`daily_update.main` 打印 roll 计数时报 `KeyError: 'days_rolled'`。改为 `.get`。R7b 写入根账本当天就会走这条路径。另外，`test_formal_write_dirty_exit2` 的驱动脚本自 R7a-D 起会真实联网（main 在 simulate 前先拉行情包并预取合约）；现在把这两步也换成离线替身，耗时 13 秒，断言不变。
- **风险/未做**：① 晚间（19:25）跑时，当天合约日线还没发布，最后一天 27 个品种 main_map 都为 None，信号退回原始连续价（回测和日报一致）；② PBO 矩阵没有用 v14 重算；③ 只有 1 年样本，不能证明有正期望；④ `test_proxy_positions` 的修改须与根账本替换同一次提交；⑤ 本地 main 比 origin 多 20 个提交，push 前要先 fetch 再 rebase，运行产物取 CI 一方（见报告第 10 节）。
- **产物**：`archive/R7/R7_signoff_report.md`、`candidate_bt.json`（+ `.log`/`_equity.svg`）、`audit_candidate.json`、`replay_candidate_empty_cache.json`、`candidate_kpis.json`、`_candidate_offline.py`、`paper_book_candidate.json`、`paper_book_legacy_pre_R7.json`、`l1_report_dryrun.json`、`paper_book_candidate_dryrun.json`、`main_map_compare_candidate.json`、`README_kpi_preview.md`、`progress.md`；`archive/snapshots/bt_input_20261124_6574c6a4dbcd.json`。
- **建议下一刀**：R7b（磊签字后：正式重跑写根目录、方案 B 根账本、README KPI 块、scorecard、formal_rule_lock、test_proxy 修改）；或停

### R5b 模拟账本共用回测持仓引擎（2026-11-24）

- **问题**：旧模拟账本按 T 日收盘价入场、入场当天不管理、只看 15m 且无日线兜底（还依赖 CODE0 历史缓存取交易日和当日日线）、不换月、不扣成本、权益只加已实现；日报先于账本刷新，组合帽按"含当天可能平掉的仓"偏保守。P 空单（11-13 入场，止盈 8644.3）和 I 空单（11-17 入场，止损 650.0）价格早已穿过却一直挂着——当时提交的 `.cache/history/P0.json` 只到 11-09、`I0.json` 只到 11-11，旧检查拿不到当天日线就静默"不平仓"。
- **做了**：① 新增 `book_core.PositionEngine`：simulate 的单仓管理段（换月/持有合约计价/跳空止损/15m 首触 + 日线兜底/复权信号失效/交割冻结/盯市/成本/平仓行）和 T+1 开仓段原样搬入，simulate 改为调用它（纯重构，四种开关组合与 replay 逐位一致）；simulate 新增 `state_log`，candidate_log 增 `selected_full`。② `paper_book` 新增 R5b 引擎账本（`"engine": "R5b"`）：T 日写 pending（方向、手数、止损/止盈、ATR、信号日及候选原字段），T+1 用共用逻辑开盘成交并平移止损/止盈；每天先成交 pending，再管理全部持仓（含刚成交的，去掉"入场当天跳过"）；成本和盯市权益与回测同口径；新仓手数用**账本自己的权益**（当天成交后、当天盈亏前），不再用 `equity_state.json`；同日重跑从 `base` 重算、结果指纹相同即 no-op；漏跑交易日逐日补管理。③ `daily_update`：账本是 R5b 格式时，先对当天 bars 做 `prepare_pack_for_execution`（仅缓存，补上 R5a 遗留缺口）→ roll 账本 → 用账本权益定手数 → 剩余持仓算组合帽（R4/R4b）→ 日报 selected 就是新 pending；新增 `--paper-book`/`--paper-out`（dry-run 预览，拒绝写根账本）。旧格式根账本仍走旧顺序与旧 refresh（含"偏保守"那条），直到 R7 换格式；`refresh_paper_book` 遇到 R5b 账本拒绝运行。④ `paper_book.py --rebuild-preview --out PATH`（冻结快照 + 本地缓存）。
- **对账**（`tests/test_paper_vs_backtest_reconcile.py`，快照窗口末 40 个交易日，用回测前一日状态播种）：平仓交易 12 笔逐字段一致；40 天 pending 与回测当日选中一致（20 单），次日成交与回测新开仓一致（12 笔，含成交价/合约/held_contract）；同口径权益最大差 0（逐位相等），未扣未成交 pending 入场成本的原始权益差最大 2.94e-4（0.029%，验收线 0.5%）；同日重跑 no-op、缺分钟时日线兜底平仓均有测试。
- **P / I 预览**（方案 A，`archive/R5/paper_rebuild_preview.json`）：P 空 11-18 15m 触及止盈 8644.312 平仓，净 +3101.88；I 空 11-19 15m 触及止损 650.012 平仓，净 −1064.11（两笔都按回测成本补扣开平成本）；修复后 11-23 盯市权益 192,370.09、空仓、pending P 空 1 手。方案 B（按回测期末状态重置）：权益 198,461.44、持 P 空 1 手（11-23 开盘 8278 入场）、无 pending。两者权益差 −6,091.35，选哪个留给 R7 签字。
- **验证**：pytest 全量 524 项全绿（R5a 518 + 新增 6），金锁 legacy 4.189/4.294/42 未变；`_bitwise_refactor_check.py`（对 42cb2e9）四种配置 ALL_IDENTICAL；replay `archive/R5/replay_after_R5b.json` 与 R5a 除 git_sha/config_version 外逐位一致（−0.769 / 7.469 / 56）；`daily_update --dry-run --paper-book <方案A账本>` 一次：根目录 42 个 JSON 与 `archive/l1_report_*` 哈希不变，selected=[P 空 1] = 新 pending；未写根 `paper_book_latest.json`/`historical_backtest_latest.json`；未 push。
- **风险/未做**：① 根账本仍是旧格式，正式修复（方案 A 回补 `backfill_R5` 或方案 B 重置）待 R7；② R5b 持仓 `fill_price_basis="continuous_proxy"` 会触发 `test_proxy_positions` 对根账本的"无 proxy 字样"断言，R7 写根账本前须处理；③ 引擎账本的权益与回测相差"当天 pending 的入场成本"（回测记在信号日，账本记在成交日）；④ 漏跑日只补管理不补信号；日报最后一天的"下一交易日"用工作日近似（不含节假日，仅影响交割月检查）；⑤ mode=roll 的 roll_carry 入场分支未接入（当前 seats 不触发）；⑥ lab_edge 若改为 action=block，会从 pending 候选中排除（已接入 exclude），observe 袖套 min_lots 仍为日报参数（对账用 0）。详见 `archive/R5/paper_path_diff.md`。
- **产物**：`book_core.py`、`tests/test_paper_vs_backtest_reconcile.py`、`archive/R5/paper_path_diff.md`、`paper_rebuild_preview.json`（+ `_bookA.json`/`_bookB.json`）、`replay_after_R5b.json`、`l1_report_dryrun_R5b.json`、`paper_book_dryrun_R5b.json`、`dryrun_R5b.log`、`progress.md`。
- **建议下一刀**：R7（v14 重跑签字 + 账本修复方案 A/B 二选一，待明示）；或停

### R5a 日报信号与回测同口径（2026-11-24）

- **问题**：R6c 把回测改成无换月价差的 roll-free 序列，日报仍用 120 根原始连续价、当天席位/升贴水、无 vol_bypass；同一天两边可能给出相反的方向（旧日报 r60 与 roll-free 相差可达 10+ 个百分点甚至变号）。
- **做了**：① 新增 `signal_core.py::path_a_candidate`（r20/r60/ATR → 动量门槛 → seats（含 `min_seat_days`）→ carry → vol_bypass → ATR 止损距离 → 手数），`simulate` 与 `daily_update.compute_signals` 都调它；simulate 纯重构，replay 与 R4b 逐位一致（−0.769 / 7.469 / 56），`adjusted_signals=False`、`caps_include_book=False`、`freeze_fix=False` 三个对照配置与 1cfe6fc 的 `simulate` 完整结果也逐位一致。② 日报 `fetch_history(n=LOOKBACK_DAYS)`（实测 275 根）；新增 `research/data_quality/contract_cache.py::ensure_contract_bars(code, upto, root)`：先读 `.cache/contracts`，只补缺：上一主力 + 近 150 天内到期的合约（窗口内曾是主力）+ 最近三个上市月，写回缓存并统计请求数/耗时；拉取失败走 R6c 回退，品种级 `adj_fallback` + `adj_note="本日信号含换月价差…"`，顶层 `contract_cache` / `adj_fallback_codes`。③ 席位、升贴水现在在日报里也按回测的 `lag_member`/`lag_curves_carry`（前一交易日簿）使用；vol_bypass 读 universe.json 同一配置（action=observe 不拦）。④ `daily_update.py --dry-run [--out PATH] [--signal-path core|legacy]`：只算不写（不写根目录 `l1_report*.json`、`archive/l1_report_*`、paper_book、Notion、分钟线、桌面研究、IV、sentiment 影子）；`legacy` 保留旧路径仅用于对比。⑤ 新测试 `tests/test_daily_vs_backtest_signals.py`（冻结快照、无网络，窗口末 40 个交易日，r20/r60/ATR/止损距离/手数/各过滤结果逐项 ≤1e-9 一致，注入回测当日持仓后组合帽选中列表一致；仓库缓存与空缓存两种）、`tests/test_contract_cache.py`。
- **不能统一**：lab_edge（依赖当日 live 实验室面板，历史无逐日序列，回测无法调用，仍只在日报）；observe 袖套 `min_lots`（日报独有的账本规则，回测配置 `min_lots=0`，以参数传入 core，仅 observe 袖套且 ATR<25%×收盘才抬）。详见 `archive/R5/signal_path_diff.md`。
- **接口开销（本机实测）**：热缓存下日报 0–12 次合约请求、<0.1 s；**冷缓存（CI 空 `.cache/contracts`）**：27 品种 191 次请求、19.1 s（Sina ~0.09 s/次），第二次 0 请求。冷拉取后的信号与本地完整缓存逐品种一致（0 个差异）；**若什么都不拉**（空缓存且不调 ensure），27 个品种全部 `adj_fallback`，5 个品种方向与 roll-free 不同（EG、EB、JD、FU、BU）。
- **CI 方案建议（磊定）**：`.cache/contracts` 被 `.gitignore` 忽略，当前 CI 不带；本刀没动 `.gitignore`/workflows。ensure 已能在 CI 冷启动自愈（约 19 s，191 次请求），所以**不加也能用**。推荐在 `daily.yml` 加 `actions/cache`（key 用固定前缀 + 日期，`restore-keys` 回退到前缀）保存 `.cache/contracts`，缓存命中后每天只补当天几十个请求；不建议把缓存提交进仓库（341 个文件 ≈ 11.9 MB，且每天增量，会让仓库膨胀）。
- **日报旧 vs 新（`archive/R5/dryrun_old_vs_new.json`，同一时刻两次 dry-run）**：27 品种中 21 个有数值变化；方向变化 5（EG、EB、JD、FU、BU：旧"空"→新"空仓"，r60 变号）；手数变化 8（L、RB、CF、RU、AL、I、JM 由 0 变正，FU 1→0）；block 变化 11（旧口径对弱信号也写席位/升贴水 block，新口径弱信号不再带 block）；`selected` 两边都为空（P 已在账本持仓、SR 同板块、gross 额度已满），无变化。
- **验证**：pytest 全绿（全量 518 项（R4b 499 + R5a 新增 19），另有 `test_no_lookahead_bt` 等通过 hook 保持 `historical_backtest.entry_block` 等 monkeypatch 点有效）；金锁 legacy 4.189/4.294/42 未变；replay `archive/R5/replay_after_R5a.json` 与 `archive/R4/replay_after_R4b.json` 除 git_sha/config_version 外逐位一致；未写根目录 formal latest；未 push。
- **产物**：`archive/R5/signal_path_diff.md`、`replay_after_R5a.json`、`l1_report_dryrun.json`、`l1_report_dryrun_legacy.json`、`dryrun_old_vs_new.json`、`contract_fetch_cold.json`、`_bitwise_refactor_check.py`、`_cold_contract_fetch.py`、`_compare_dryrun.py`、`progress.md`。
- **风险/未做**：① 新测试依赖的快照 `archive/snapshots/bt_input_20261123_da9c8de64ab4.json` 与 `archive/R0/fresh_bt.json` 目前未被 git 跟踪（R0–R3 的 archive 目录均未跟踪），干净检出时这批测试会 skip，需磊决定是否提交；② 日报 `held` 仍是 paper_book 持仓（连续价估值，偏保守），本刀不动账本；③ lab_edge 口径差无法消除；④ 席位/升贴水改为前一交易日簿，日报 block 文案会比旧版晚一天；⑤ 本地 dry-run 里日报的 R6c 回退只在缓存缺口时出现，CI 冷启动若 Sina 限流，会退回原始序列并在报告里标出。
- **建议下一刀**：R5b（模拟账本按回测逻辑逐日记账、T+1 成交、补记历史平仓、对账测试，待明示）

### R4b 组合帽缩手后补手，修掉取整误杀（2026-11-24）

- **问题**：`apply_portfolio_caps` 对所有候选按同一比例缩手后 `floor`，剩余额度小时会把"其实够开 1 手"的候选缩成 0（2026-01-12 CF：剩余 37.14%，1 手 36.56%，4 手×0.2008→0 手）。R4 诊断 `floor_artifact_diag.json` 统计到 19 个这类候选日。
- **做了**：只改 `position_rules.apply_portfolio_caps`。原有比例缩手 / hard trim / refill 不动；在 refill 之后、min_lots 之前新增 top-up：对象是动量过关后手数低于原始请求的所有候选（含被缩成 0 的），按 `_strength` 从强到弱多轮循环，每轮每个对象加 1 手；加之前检查加完后的选中组合名义 ≤ 名义额度、ATR 风险 ≤ 风险额度、持仓数 ≤ max_positions、每板块 ≤ max_per_bucket（含 `existing_buckets`），且不超过原始请求手数；一轮加不上任何一手即停；0 手补到 ≥1 手的重新加入 selected。新参数 `topup: bool = True`；`topup=False` 与 aa65cb1 逐位一致（meta 也不含新键）。meta 新增 `topup_lots`、`topup_revived`。`simulate` 主入场分支累加到结果 `caps_topup_lots` / `caps_topup_revived`（roll_carry 分支也计入）；`caps_include_book=False` 时传 `topup=False`，仍复现 R4 前的帽口径。daily_update / paper_book 调用不改，自动使用新逻辑；`scripts/shadow_*.py` 三个影子脚本也调用该函数，默认同样 `topup=True`（本刀未动）。
- **结果（R6c / R4 / R4b，不调参）**：ret 12.744 / −1.053 / **−0.769**；gross_ret 15.434 / 1.005 / 1.875；maxDD 4.124 / 4.552 / 7.469；笔数 64 / 56 / 56（exits 23/37/4、18/34/4、18/34/4）；成本 5379.74 / 4114.88 / 5287.84；`caps_entry_gross_max` 113.52 / 49.65 / 49.83；`caps_entry_risk_max` 3.17 / 2.64 / 2.33；`caps_scaled_n` — / 52 / 64；`caps_topup_lots` 114、`caps_topup_revived` 29（按"调用日"累计，同一候选连续几天未成交会重复计入）；`caps_drift_days_gt55` 35 / 0 / 0（R4b 曲线 gross 最大 50.77%，为盯市漂移）；曲线 gross 中位数 19.08 / 19.24 / 36.76；平均持仓 0.94 / 0.83 / 0.91；单笔实际风险中位数 0.458% / 0.436% / 0.555%。R4→R4b 逐笔：手数变化 17 笔、新增 14 笔、移除 14 笔；这 45 笔 R4 合计 −8 034 元 → R4b −6 294 元。maxDD 明显上升（4.55→7.47）是因为同样的信号现在占满额度，个别大手数止损（EG 11-13 2 手 −3 136、MA 09-14 2 手 −2 280）放大回撤。
- **诊断复跑**：`_floor_artifact_diag.py` 在 R4b 回放上"下一手仍放得下却被丢掉"的候选 **0**（R4 为 19）。
- **验证**：pytest 499 全绿（新增 6 条 top-up 用例）；金锁 legacy 4.189/4.294/42 未变；audit checked=52 mismatches=0；未写 formal latest；未 push。为保持 R4 测试断言不变，`test_no_existing_buckets_gives_the_old_result_exactly` 里两处调用加了 `topup=False`（该测试断言的正是 aa65cb1 的旧结果）。
- **产物**：`archive/R4/replay_after_R4b.json`、`audit_after_R4b.json`、`R4_vs_R4b.json`、`_build_compare_R4b.py`、`floor_artifact_diag_R4b.json`；`_floor_artifact_diag.py` 加 `DIAG_OUT` 环境变量选输出名。随本次提交一并带入磊对 `docs/UPGRADE_R_TRACK.md` 的 R5 节修改（正文未动）。
- **风险/未做**：① 补手让仓位更满，回撤变大、收益仍为负，整体 R4b 仍明显低于 R6c；R6c 的 +12.7% 有相当部分来自超限持仓；② 逐笔变化大多是路径连锁（手数/名额变化改变权益与后续入场），未逐笔证明；③ 日报 `held` 偏保守；④ 影子脚本默认也变为 top-up
- **建议下一刀**：R5（待明示）；或停

### R4 组合帽计入已有持仓（2026-11-24）

- **修前（R6c，只读统计，`archive/R4/prefix_R6c_caps.json`）**：41 个入场日里，名义占用 >50% 的有 **17 天**（曲线口径 15 天），最大 **113.52%**（2026-10-09 CF+I+MA；其次 11-17 EG+I+P 112.2%、10-16 FU+I+MA 91.2%）；ATR 风险 >8% 的 **0 天**（最大 3.17%）——风险帽从不起作用，名义帽才是约束。原因：`apply_portfolio_caps` 只看当日候选，不看已有持仓的名义/风险/bucket。
- **做了（引擎）**：`historical_backtest._book_usage(pos, idx, series, d)` → `(used_gross, used_risk, held_buckets)`：continuous_proxy 持仓按连续合约 d 日收盘；合约口径持仓优先用持有合约的真实收盘（`load_contract_bar`），无则退连续；风险用 R6c 统一的调整后 ATR（不是原始 `atr14`）；无当日 bar 的持仓按最近盯市/入场价、入场 ATR（保守）。主入场分支与 roll_carry 分支共用。主分支传入剩余额度：`max_gross = max(0, 50 − used_gross/eq×100)`、`max_risk = max(0, 8 − used_risk/eq×100)`（eq=sizing_eq）与 `existing_buckets=held_buckets`；`position_rules.apply_portfolio_caps` 新增 `existing_buckets: dict|None=None`（主循环与 refill 的 bucket 计数从它起算；不传＝旧行为）。信号日收盘做 order-time 断言：已有+新单名义 ≤50%、ATR 风险 ≤8%。新增结果键 `caps_entry_gross_max`、`caps_entry_risk_max`、`caps_scaled_n`（与"不看持仓的满额度"反事实相比手数变少/被丢的候选数）、`caps_drift_days_gt55`（曲线 gross_pct>55 的天数，仅统计）、`caps_entry_log`、`caps_include_book`（默认随 `freeze_fix`；False 复现 R6c 的帽口径）。
- **做了（日报）**：`daily_update._apply_caps(signals, *, sizing_equity, held=None)`；`held` 取只读 `paper_book_latest.json` 的持仓，同口径扣额度/占 bucket/占名额，已持有品种不再作为新候选，meta 加 `held_book`。**保守性**：日报在 `refresh_paper_book` 之前跑，所以 `held` 可能包含当天就会被平掉的仓位，会少给新单额度（宁少勿多）。`held=None` 与旧行为一致。
- **做了（模拟账本）**：`paper_book.refresh_paper_book` 开仓循环——在当日平仓之后、新开仓之前，按已保留持仓校验：持仓数 ≤ max_positions、同 bucket ≤ max_per_bucket、名义 ≤50%、ATR 风险 ≤8%（signal 收盘价与乘数）；不通过则跳过并记 `skip_reason="caps_book"`（输出 `skipped_today`）。未改入场价口径、未做 pending/T+1、未补历史平仓（R5 的事）。
- **结果（R6c → R4，不调参）**：ret 12.744 → **−1.053**，gross_ret 15.434 → 1.005，maxDD 4.124 → 4.552，笔数 64 → 56（target 23→18、stop 37→34、signal 4→4），成本 5379.74 → 4114.88；曲线 gross_pct 最大 113.64 → 49.96（中位数 19.08 → 19.24），入场日 >50% 17 天 → 0，`caps_entry_gross_max` 113.52 → 49.65，`caps_entry_risk_max` 3.17 → 2.64，`caps_scaled_n`=52，`caps_drift_days_gt55`=0（R6c 为 35 天），平均持仓 0.94 → 0.83，单笔实际风险中位数 0.458% → 0.436%。**收益变化的来源**：R6c 的 +12.7% 有相当一部分来自超限（最大 113%）持仓；逐笔 R6c→R4：26 笔被丢（其中 11 笔因 R6c 当日账本名义 >50%、2 笔含 bucket 占用、其余为前序变化的路径连锁）、8 笔手数缩小、18 笔路径连锁新增；被丢 26 笔 R6c 合计 +16 535 元，新增 18 笔合计 −9 622 元。
- **验证**：pytest 493 全绿（新增 `tests/test_caps_include_book.py` 9 条）；金锁 legacy 4.189/4.294/42 未变；audit checked=52 mismatches=0；未写 formal latest；未 push
- **产物**：`archive/R4/replay_after_R4.json`、`audit_after_R4.json`、`R6c_vs_R4.json`（对比表、逐笔变化、17 个修前超限日处理）、`_build_compare_R4.py`、`_step0_prefix.py`、`prefix_R6c_caps.json`、`_floor_artifact_diag.py`/`floor_artifact_diag.json`、`progress.md`
- **风险/未做**：① `apply_portfolio_caps` 对剩余额度用"全体候选统一比例 + `floor`"缩手数，剩余额度较小时会把"其实够开 1 手"的候选缩成 0 手丢掉（例：2026-01-12 CF 4 手→比例 0.2008→0 手，而 1 手占 36.6% 仍低于剩余 37.1%）；诊断统计在整段回测的"账本感知"调用里有 19 个候选日属于此类（`floor_artifact_diag.json`），因此 R4 的收益下降里含一部分取整假象，未调、留待磊决定是否单开一刀（不是调参，是取整方式）；② 日报 `held` 偏保守（见上）；③ 被丢/新增的逐笔归因中"路径连锁"为推断；④ 首次 R4 指令因连接超时中断过一次，中途只留下 `archive/R4/` 的 Step 0 文件，无代码改动，已从头重做
- **建议下一刀**：R5（待明示）；或先决定是否单开"取整/最小 1 手回填"一刀；或停

### R6c 信号和 ATR 不受换月影响 + 审计例外（2026-11-24）

- **审计例外**：`audit_exit_vs_daily.py` 新增 `gap_through_target_conservative`——reason=target、当日开盘已越过止盈价（多 open≥target，空 open≤target）、成交价=止盈价（±0.5 跳）时，不再报 `exit_outside_held_bar_range`，单独计数并列出；止损及其他情形判定不变。CF 05-06 即此例（引擎按目标价保守成交，未改引擎）。
- **做了**：新增 `research/data_quality/adjusted.py`（不做全样本向后复权价格水平，只用 ≤T 数据）：roll-free 日收益（换月日 = 新合约自己 close_d / close_{d−1} − 1，其余日 = 连续合约收益）；`ret_n` = 最近 n 个日收益连乘 −1（窗口内无换月/无回退时与原序列逐位相同）；同合约 TR（C*_{d−1} = 当天主力合约 d−1 收盘）、ATR14 = 最近 14 个 TR 均值；`vol_hist()` 给 vol_bypass 用的前向构建收益指数；价格缺失（main_map 为 None 或新合约 d−1 无价）退回原始连续口径并计数 `adj_fallback_days`。`simulate` 的入场 r20/r60 及门槛、信号失效出场、ATR14（止损止盈距离、手数、组合风险占用、roll_carry 候选）、vol_bypass 波动率改用该序列；成交、止损止盈判定、盯市仍用真实价格（R6b 的 held_contract 逻辑不变）；新参数 `adjusted_signals`（默认随 `freeze_fix`，=False 逐位复现 R6b-fix）；carry/席位等不动。
- **main_map 全历史**：覆盖每个品种 hist 全部 275 根 bar（含 WARMUP）共 7425 个品种日，补抓 JD/SP 2510、2511、2512 六个合约（`backfill_R6c.log`）后 7425/7425 全部匹配，0 天 None（补抓前 JD 15 天、SP 3 天 None）。
- **daily_update 信号位置**：`daily_update.py::_fetch_snapshot`（约 145–185 行）对 `fetch_history(u, n=120)` 的新浪原始连续序列直接调用 `historical_backtest.ret_n` / `atr14`，得 r20/r60/ATR，随后在同一函数里判方向与 `entry_block`。与回测的差异：无 main_map、无换月复权（换月日的价差仍计入 r20/r60/ATR），只有 120 根历史；回测 R6c 起用 roll-free 序列。本刀未改，留待后续对齐。
- **产物**：`archive/R6/replay_after_R6c.json`、`audit_after_R6c.json`、`R6bfix_vs_R6c.json`（对比表、167 个换月日 raw/adj 差异、63 条逐笔变化含 K 线）、`_build_compare_R6c.py`、`_replay_R6bfix_rawsignals.json`（adjusted_signals=False 复现 R6b-fix，用于候选数对比）、`backfill_R6c.log`。
- **结果**：R6b-fix 12.244 / dd 5.923 / 66 笔 → **R6c 12.744 / dd 4.124 / 64 笔**（target 26→23、stop 35→37、signal 5→4）；过门槛候选 1528→1612；adj_fallback_days=0；窗口内换月日 125 个，r20 方向翻转 28 次、r60 翻转 11 次；63 条逐笔变化里直接由信号变化造成的是入场门槛 13 笔 + 假 signal 出场 2 笔（MA 04-13、SA 08-14，均为换月日原始 r20 假翻转），ATR 变化 9 笔，其余为手数/路径连锁。
- **验证**：pytest 484 全绿；金锁 legacy 4.189/4.294/42 未变；audit checked=60 mismatches=0（`gap_through_target_conservative`=1）；未写 formal latest；未 push
- **风险/未做**：真实数据里仍无 continuous_proxy 持仓被换月穿越；daily_update 未对齐；R4 未做；逐笔「路径连锁」归因按"门槛判定一致→受前序权益/名额影响"推断，未逐笔重放证明
- **建议下一刀**：R4（待明示）；或停

### R6b-fix 按真实主力合约处理换月（2026-11-24）

- **替代说明**：b195c25 的 R6b（日历合约字段 / OI+gap 换月、`roll_exit`）**已被本次返工取代**；R6a 保留并按新规则收口。b195c25 保留在历史中，未 amend。
- **三个错误**：(1) roll_exit 在建仓日用建仓前一根收盘价平仓（TA 01-12 / JD 06-11 / L 09-11）；(2) 日历合约字段每月翻转被当成换月（MA 10-12 止损→止盈）；(3) 价差仍记入盈亏（last_mark 未平移）。
- **做了**：新增 `research/data_quality/main_map.py`（某合约自己的日收盘与新浪连续收盘差 ≤1 tick 才记为主力，否则 None；仅用当日及之前数据）；`rolls.py` 重写；`simulate`：换月只认 `main_map[d]≠main_map[d−1]`；continuous_proxy 持 `held_contract`，主力已变则用持仓合约自己的 bar 判 stop/target/PnL，d+1 开盘旧合约开盘平、新合约开盘开，stop/target 与 last_mark 平移，成本 2×；取不到价格走不会变好的处理并计数；删除 roll_exit；断言：出场日≥入场日、入场日只能用成交 bar 起；审计 +3 项（出场早于入场 / continuous_proxy 出场价在持仓合约出场日 [low,high] 内 / 换月日出场价取自持仓合约），口径与引擎一致。补抓 222+80 个合约日线（`.cache/contracts/`，gitignore）。
- **产物**：`archive/R6/replay_after_R6b_fix.json`、`audit_after_R6b_fix.json`、`R3_vs_R6ab_vs_R6bfix.json`、`_build_compare.py`、回填日志
- **结果**：R3 10.026 / dd 6.904 / 65 → R6ab 12.449 / 4.64 / 64 → **R6b-fix 12.244 / 5.923 / 66**；main_map 5805 天 0 天为 None；真实数据里无 continuous_proxy 持仓被换月穿越（roll_shifted=0，平移逻辑由合成测试覆盖）
- **验证**：pytest 475 全绿；金锁 legacy 仍 4.189/4.294/42 未改；audit checked=61 mismatches=1（CF 05-06 目标跳空按目标价保守成交，R3 约定，未放宽审计）；未写 formal latest；未 push
- **风险/未做**：信号（含 signal 出场）仍基于带价差的连续序列，MA 04-14 的 signal 出场即由连续序列换月日假下跌触发（R6c）；R4 未做
- **建议下一刀**：R6c（待明示）；或停

### R6a/b 换月不得产生假盈亏和假止损（2026-11-24）· 已被 R6b-fix 取代（R6a 保留）

- **做了**：磊决定 R6 提前到 R4 前；本刀只做 R6a/b。`rolls.is_roll_day`（合约字段变化或 OI≥15%+gap≥0.5%，仅 T−1）；`manage_bar_fixed` 换月废旧 basis_off→真合约 OHLC / `roll_unpriced`；continuous_proxy 移仓平移或 `roll_exit`；审计加换月不符 + `snap_proxied` 与引擎同口径；补抓 FG2605/MA2605/EG2609/EG2610 至 `.cache/contracts/`（gitignore）
- **产物**：`archive/R6/replay_after_R6ab.json`、`audit_after_R6ab.json`、`R3_vs_R6ab.json`；R3→R6ab：10.026→12.449 / dd 6.904→4.64 / 65→64；roll_shifted=6、roll_exit=3、roll_unpriced=0；gap_stop 4→1（仅 EG 08-26 真实 −1.12R）；R<−2 止损=0
- **验证**：pytest 450 全绿；audit checked=57 mismatches=0（含原合约口径 I/P）；金锁 legacy 仍 4.189/4.294/42 未改；未写 formal latest；未 push
- **三笔重判**：MA04-14 假跳空→signal +0.17R；FG04-16 假 −6.08R→真合约 stop −1.0R；EG09-22 跨合约跳空→移仓后 stop −1.0R
- **风险/未做**：R6c 信号/ATR 复权未做；R4 组合帽未做；日历主力≠新浪主力时依赖 OI/gap
- **建议下一刀**：明示后开 **R6c**；或停

### R3 跳空止损按开盘成交（2026-11-24）

- **做了**：`apply_stop_target` 开盘穿越按 open 成交、`target=None` 不触发止盈；`paper_book` 会话日历过滤周末/无 open 假 K；排查周末 bar 来源（iFinD 稀疏解析 → merge_bars 残留，未改写入/未清缓存）；金锁 4.362/4.184/42 → 4.189/4.294/42
- **产物**：`archive/R3/replay_after_R3.json`、`audit_after_R3.json`、`R2_vs_R3.json`；R2→R3：13.414→10.026 / dd 4.044→6.904 / 64→65；gap_stop_exits=4、gap_slippage_R≈6.48、R<−1.05 止损=4
- **验证**：pytest 444 全绿；连续口径不符 0；合约口径仍 I/P 2 笔；根目录 formal latest diff 空；未 push
- **风险/未做**：周末假 K 写入路径未修；组合帽（R4）、账本对齐（R5）未做；本刀收益回撤变差属预期（跳空真实亏损）
- **建议下一刀**：明示后开 **R4**；或停

### R2 夜盘交易日归属（2026-11-24）

- **做了**：核实 (A) 日线 H/L 含夜盘、(B) 日线 open≈夜盘开盘；新增 `trading_day_of` / `load_minute_bars_on_trading_day`；`simulate`/`paper_book` 按交易日加载全时段分钟线，入场日去掉 09:00 cutoff；`minute_manage_checks`；金锁 3.679/4.859/40 → 4.362/4.184/42
- **产物**：`archive/R2/replay_R1_recheck.json`（复核 12.674/4.044/63）、`replay_after_R2.json`、`audit_after_R2.json`、`R1_vs_R2.json`；R1→R2：12.674→13.414 / dd 同 4.044 / 63→64；`minute_manage_checks=13`
- **验证**：pytest 437 全绿；连续口径不符 0；合约口径仍 I/P 2 笔；出场变化：PP 10-14 入场 R1 于 10-26 target+2R → R2 于 10-21 stop−1R；多出 FU 10-22→10-26 target；根目录 formal latest diff 空；未 push
- **风险/未做**：合约口径审计误判仍留给 R7 前；跳空止损（R3）、组合帽（R4）、账本日线兜底（R5）未做
- **建议下一刀**：明示后开 **R3**；或停

### R1 假止损修复（2026-11-24）

- **做了**：`day_session_bars` + `minute_bars_match_daily`（同口径日线校验分钟线）；接入 `simulate` / `paper_book._intraday_stop_exit`；新增 `minute_rejected_mismatch`；单测；顺带更新 `test_freeze_fix_gates` 旧 KPI 金锁（R1 改出场后必然漂移）
- **产物**：`archive/R1/replay_after_R1.json`、`audit_after_R1.json`、`R0_vs_R1.json`；对比基线 R0 replay 7.253%/6.739%/65 → R1 12.674%/4.044%/63；`minute_stop_exits` 6→3，`minute_rejected_mismatch=9`；FU 09-23 入场于 09-28 改为 target +2R
- **验证**：pytest 430 全绿；连续口径不符 0；合约口径仍 2 笔（I/P，第 0 步诊断为审计错：缺 `contract_*` 时误用主连 OHLC，引擎用 continuous+basis_off 触及）；根目录 formal latest `git diff` 空；未 push
- **风险/未做**：合约口径 2 笔与审计脚本 `_ohlc` 回退逻辑留给 R7 前单处理；夜盘归属仍错（R2）；paper 日线兜底（R5）；`.cache/history` 在 `daily_update` 中经 `fetch_history`→`save_chart_history` 于 `refresh_paper_book` 之前已更新
- **建议下一刀**：明示后开 **R2**；或停

### R0 冻结基线（2026-11-24）

- **做了**：文档登记已提交；远端无 `bt_input_20261120_*` → **走 3B**（`historical_backtest.py --out`）；参数化 `lab/shadow/replay.py`；新增 `scripts/audit_exit_vs_daily.py` + 单测；产物落 `archive/R0/`；tag `baseline-R0`
- **产物**：`archive/R0/fresh_bt.json` + snap `archive/snapshots/bt_input_20261123_da9c8de64ab4.json`；`baseline_replay.json`；`audit_formal.json` / `audit_replay.json`；`formal_{bt,paper,weekly}.json` 副本
- **验证**：formal 连续口径不符恰 3 笔（FU 09-28 / PP 10-20 / P 11-13 stop）；replay 与 fresh_bt 完全一致（ret 7.253 / dd 6.739 / n=65）；`git diff` 根目录 formal latest 为空；未 push
- **风险/未做**：正式窗口 20261120 快照未找回，R1 比较基线以 **fresh/replay（3B）** 为准；audit_replay 另见 2 笔合约口径不符（I 04-16 stop、P 11-18 target）照实保留不修；未开 R1
- **建议下一刀**：明示后开 **R1**；或停

### R-REG 轨 R 登记（2026-11-23 · 非刀）

- **做了**：AWS Quick 只读审计本地仓库 + 云端十年近似重放；产出轨 R 清单、carry 袖套细则、证据综述；在本表登记轨 R（§0 / §1.0 / §2 / §6）  
- **产物**：`docs/UPGRADE_R_TRACK.md`；`docs/UPGRADE_R_TRACK_equity.png`；`docs/CARRY_SLEEVE_R14.md`；`docs/STRATEGY_EVIDENCE_REVIEW.md`  
- **验证**：仅文档；未改代码、未写 `paper_book` / 正式 BT / seats / `execution_rules.json`；未提交  
- **风险/未做**：十年重放与 carry 原型为简化近似（无席位、按比例仓位、近似复权、面板 carry 有缺陷），只用于判方向，不替代 R8 / K4；模拟账本现有 P、I 持仓越过止盈/止损未平，留待 R5 处理  
- **建议下一刀**：明示后开 **R0 冻结基线**；F2 继续积样  

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
- **风险/未做**：反馈偏弱 → **禁止晋级**；未开 SABR/VRP/奇异；F2 不够样  
- **建议下一刀**：**停 · 积样本**；够样后确认 **F2**；或明示 **Vol-V1.6**（勿把 V1.4 当可交易）  

### VP-1B-0（2026-11-23）

- **做了**：L1 只读适配器；`signal_inbox`；`SIGNAL_READ_ALLOWED` 与 `SIGNAL_INGEST`/AUTO 解耦；Desk 收件箱；硬门槛测  
- **产物**：`virtual_portfolio/adapters/l1.py`；`signal_inbox.py`；`tests/test_vp_phase1b0.py`；`VP_PHASE1B0_REPORT.md`  
- **验证**：pytest 1A+1B-0 → 25 passed  
- **风险/未做**：无下单/无改账户；未开 1B-1；Desk 须手动开只读开关再摄入  
- **建议下一刀**：**停**；观察收件箱后再明示 **1B-1**，或积样 **F2**  

### Vol-V1.4 轻量入库（2026-11-23）

- **做了**：将本机 Vol-V1.4 模块/规格/测试/定价小改（theta、`--settle-only`）归档进 `main`；规格头注标明 **结果弱 · 不晋级**  
- **产物**：`research/options/volatility/**`；`docs/VOLATILITY_ENGINE_SPEC.md`；`tests/test_vol_engine_v14.py`；`lab/research/run_vol_engine_daily.py`；可选 `vol_engine_daily_latest.json`  
- **验证**：`pytest tests/test_vol_engine_v14.py` → 7 passed  
- **风险/未做**：未开 1B-0；未晋级；日更 cache 未提交  
- **建议下一刀**：**停 · 积样**；或明示 **VP-1B-0** / **F2**  

### 档案同步 + 本地 WIP 登记（2026-11-23）

- **做了**：登记 `LOCAL_WIP_INVENTORY.md`；纠正 Vol「完成」口径；同步个人库 / Notion / 第二大脑  
- **产物**：`docs/audit/LOCAL_WIP_INVENTORY.md`；个人库 `cta-path-a/UPGRADE_PLAN.md`  
- **验证**：清单与 `main` 状态一致（随后 Vol 轻量入库）  
- **建议下一刀**：**停**；或明示旁轨  

---

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

### OFFICIAL-PIPELINE 官方数据管道（2026-11-26）

- **做了**：按磊确认的 7 项决定实现官方日更管道（`official_pipeline/`）：本地计划任务（17:30 + 18:30/20:00/22:00 重试 + 次日 08:30 判定补抓）、仓库外正式库 `D:\AI\data\official\`、哈希清单入库、Playwright 固定版本、种子自 R8 原始库（逐日哈希校验后复制）、告警文件 + 气泡通知、日报不入 main；DCE 请求形式已验证（JSON 体）。
- **产物**：`official_pipeline/`（config/store/sources/validate/state/alerts/notify.ps1/seed/run/install_tasks）；`official_pipeline/manifest_repo/hashes_{shfe,czce,dce}.json`；`tests/test_official_pipeline.py`；`docs/OFFICIAL_DATA_PIPELINE_DESIGN.md` 实现记录与偏差段；5 个计划任务已注册。
- **验证**：新增 12 项单测通过；全量 `pytest tests/` 584 passed；DCE 规范化对 3 个 R8 已入库交易日逐字节一致；种子 2,645 SHFE / 2,645 CZCE / 2,646 DCE 条哈希校验通过、0 不一致；受保护文件无 diff；`lab/research` 由测试产生的改动已还原。
- **风险/未做**：① 衍生主力依赖本地新浪连续缓存的当日 bar（由 CTA 日更生成），2026-11-26 缓存只到 11-25（M 只到 11-20），该日判为**不正常**，**shadow 计数未开始**；② 交易日历无节假日表，以"三所均未发布"判休市；③ 修订记录当前需人工清理；④ 未推送 origin，本地 main 领先。
- **建议下一刀**：**停**。待磊决定衍生用的新浪当日 bar 来源（A 主仓库日更 / B 管道自取）后，再开 5 天计数。

## 反馈模板

```text
【迭代反馈 · <阶段ID>】
做了：
产物：
验证：
风险/未做：
建议下一刀：开 <ID> / 停
```
