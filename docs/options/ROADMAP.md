# 期权研究台 · 路线图

**日期**：2026-11-23（用户决议：先积样 · 够样后再升级）  
**已完成**：阶段 A–E + F1 + F1b；旁轨 **Vol-V1.4**（已轻量入库 · Shadow only · **结果弱 · 不晋级**）  
**原则**：全程不改 Path-A 正式层（`paper_book` / 正式 BT / seats）。  
**逐步开放 / 迭代反馈 / 合并总表**：见 `docs/UPGRADE_ITERATIONS.md`（五轨 O/T/A/V/VP；个人档案已同步）。  
**当前姿态**：**只积盘口，不开新刀**；锁定下一刀仍为 **F2**，gate `ready=false`（CF=2/10，SR/MA=1/5）前不升级。  
**R 审计升级旁注（2026-11-25）**：R8 本金 + 极端风险过滤研究已跑完（分支 `r8-equity-filter`，未合入；无组通过预注册标准；正式层未动；后续已冻结候选并提交样本外预注册，长样本数据可行性检查已完成（`archive/R8/LONG_FEASIBILITY_REPORT.md`，只读，27 个品种不能算全部齐全，待磊决定；磊决定后做了主力字面重判与本地数据核对 `archive/R8/MAIN_RECOMPUTE_REPORT.md`，因换月对等比较不为 0 停在等磊；磊选成交量守卫（5%，仅官方路径）后，做了阈值敏感性与 216 天窗口缺口检查（`GUARD_SENSITIVITY_REPORT.md` / `WINDOW_GAP_REPORT.md`，A/B 交易均不受影响），并已提交附录 1 `archive/R8/APPENDIX_1.md`（早于任何长样本运行）；之后实现长样本入口与 C，9 个正式组已跑完：A/B/C 均未通过预注册标准，B、C 均不优于 A，见 `archive/R8/OOS_VERDICT.md`；之后 30 万诊断档已跑（均不适用）、分支已合入 main、收尾前三项只读归因已做（R8_CLOSEOUT.md 附录 A.5：信号层判定无优势，问题在信号层）；管道未实现、shadow 未开，停在等磊看诊断结果），详见 `docs/UPGRADE_ITERATIONS.md` §7；与本期权研究台路线无依赖。  
**官方数据管道（2026-11-26）**：已实现并注册本地计划任务（official_pipeline/，docs/OFFICIAL_DATA_PIPELINE_DESIGN.md 实现记录）；**shadow 未开**：衍生主力依赖的新浪当日 bar 待磊定来源，5 天计数尚未开始。  
**旁轨**：可信度旁轨已完成；**Vol-V1.4 已归档但不晋级**；**VP-1A** 已合 main；**VP-1B-0 只读收件箱已落地（停）**；锁定 **F2**（积样）。后续刀序见总表 §4。

---

## 总览

| 阶段 | 内容 | 状态 | 依赖 |
|------|------|------|------|
| **A** | 审计、设计、OH-01、本路线图 | **完成** | — |
| **B** | Black-76 定价核 + CF/SR/MA 合约规格 | **完成** | A |
| **C** | 日链落盘 + 质量闸；option_compare 缓存过期 | **完成** | B |
| **D** | 卖方信用价差研究回测 + Desk 只读面板 | **完成** | C |
| **E** | 研究纸面台账 + 风险报告 + soft 日报钩子 | **完成** | D |
| **F1** | 活链 Bid/Ask 写入快照（Tq） | **完成** | E |
| **F1b** | 日积活链盘口（快路径+截止时间） | **完成** | F1 |
| **F+** | 买方 / 全宇宙 / 历史盘口晋升 / 写入正式层 | **延后** | F1b + 稳定历史报价 |

```mermaid
flowchart LR
  A[A 审计设计] --> B[B 定价+规格]
  B --> C[C 链存储+质量]
  C --> D[D 信用价差BT]
  D --> E[E 纸面+风险]
  E --> F[F+ 买方/全宇宙]
```

---

## 阶段 B — 基础定价与合约规格（**完成**）

见 `research/options/pricing/black76.py`、`specs.py`、`docs/options/SPECS_CF_SR_MA.md`。

---

## 阶段 C — 链数据与质量闸（**完成** 2026-11-15）

1. [x] `research/options/chain_store.py` + `parse.py` + `quality.py` → `data/options/snapshots/`  
2. [x] 质量闸 OK/WARN/REJECT；无 Bid/Ask → WARN  
3. [x] `scripts/run_options_chain_collect.py`；日报 soft 钩子  
4. [ ] Tq 活链 Bid/Ask 字段扩展 → **挪到 F+**（报价未稳）  
5. [x] `option_compare` hist/months 缓存带 `fetched_at`，24h 过期  

**实测**：CF 6 日 / SR 1 / MA 1 快照已落盘（gamma raw 缓存）。

---

## 阶段 D — 卖方信用价差研究回测（**完成** 2026-11-15）

1. [x] `strategies/credit_vertical.py`：选腿、settle_discount / bid_ask  
2. [x] `backtest/engine.py` + `metrics.py`；产物 `data/options/backtests/credit_vertical_latest.json`  
3. [x] `desk/options_research_panel.py` 挂在「期权机会」页  
4. [x] 无未来函数：出场日必须严格晚于入场日（单测）  

**实测（settle_discount）**：n_closed=5，win=0.4，state=**WARN**。

---

## 阶段 E — 研究纸面与风险（**完成** 2026-11-15）

1. [x] `data/options/paper_trades/ledger.jsonl` 幂等指纹  
2. [x] `risk_report.py` → `data/options/risk_reports/latest.json`  
3. [x] 状态：`RESEARCH` / `WARN` / `PAPER_CANDIDATE`（人工）  
4. [x] `daily_update` soft：链采集 + BT + 风险报告，失败不挡 Path-A  

---

## 阶段 F1 — 活链 Bid/Ask（**完成** 2026-11-15）

1. [x] `tqsdk_client.quote_bid_ask` + 链行写入 `买价`/`卖价`/`bid`/`ask`  
2. [x] `parse.normalize_leg` 识别盘口；Tq 无 CZCE 码时用 期权类型+行权价  
3. [x] `chain_store.build_from_tq_live`；`run_options_chain_collect.py --tq-live`  
4. [x] 有盘口的快照质量可为 OK；**历史 settle BT 仍 WARN**（无历史盘口不晋升）  

## 阶段 F1b — 日积活链盘口（**完成** 2026-11-15）

1. [x] 快路径：`compute_iv=False` + `overall_deadline_s`（避免挂死）  
2. [x] `accumulate_live_bidask`；`--tq-live-only` / `--deadline`  
3. [x] `daily_update` soft 挂载（45s/品种）  

```bash
python scripts/run_options_chain_collect.py --codes CF --tq-live-only --deadline 45
```

## 阶段 F+ — 仍延后

| 项 | 为何延后 |
|----|----------|
| 历史 Bid/Ask 回测与状态晋升到 PAPER | 日积刚起步，无长史；策略上限仍 WARN |
| 买方引擎 / 跨式 / 日历 | 阶段一先卖方 |
| 全品种扫描 | CF/SR/MA 样本仍薄 |
| 写入 Path-A `paper_book` / 替换 seats | 审计禁止，需人工决议 |
| Gamma Flip / VRP 当交易信号 | 语义不足 |

---

## 常用命令

```bash
python scripts/run_options_chain_collect.py --codes CF,SR,MA
python scripts/run_options_credit_bt.py --codes CF,SR,MA --ingest-paper
python -m pytest tests/test_options_pipeline.py tests/test_options_black76.py -q
```

---

## 与观察模块

| 模块 | 状态 |
|------|------|
| `option_hedge` Synthetic | 保留；OH-01 已修 |
| `gamma_wall` | 保留；共享 black76 |
| `desk/options_panel` | 保留 Synthetic；研究面板另建 |

## 相关研究轨（非本 ROADMAP 主刀，见总计划）

| 轨 | 状态 | 说明 |
|----|------|------|
| 套利影子 V1.1–V1.3 | **观察** | 不晋级；细则 `docs/ARBITRAGE_VOLATILITY_UPGRADE.md` |
| Gemini TVS / 波动率协同模拟 | **观察** | 不写 `position_rules`；审计见 `gemini_scheme_sim_audit_latest.json` |
| Vol-V1.4（定价/Greeks/Shadow） | **已归档 · 不晋级** | 结果弱；规格头注禁止作交易/F2 依据；V1.5+ 仍封闭 |
