# 期权研究台 · 路线图

**日期**：2026-11-15  
**已完成**：阶段 A–E + F1  
**原则**：全程不改 Path-A 正式层（`paper_book` / 正式 BT / seats）。  
**逐步开放 / 迭代反馈**：见仓库根计划 `docs/UPGRADE_ITERATIONS.md`（个人档案已同步）。

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
