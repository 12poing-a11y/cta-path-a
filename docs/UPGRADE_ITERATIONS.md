# CTA Path-A · 近期升级计划（标记 + 逐步开放）

**同步日期**：2026-11-15  
**仓库**：`d:\AI\cta-path-a`  
**原则**：按升级方向**一次只开放下一刀**；每刀结束后**短反馈**再决定是否开下一刀；不改 Path-A 正式层（`paper_book` / 正式 BT / seats），除非你另下决议。

---

## 工作方式（固定）

1. **标记**：本文件 + `docs/options/ROADMAP.md` 为权威状态。  
2. **逐步开放**：未完成项保持「封闭」；只开状态为 **下一刀** 的一项。  
3. **迭代反馈**（每刀结束后必写，3–6 行）：  
   - 做了什么 / 产物路径  
   - 验证（测或实测 KPI）  
   - 风险与未做  
   - 建议下一刀（或停）  
4. **个人档案同步**：迭代反馈同步 Notion Memory + About「Current work」；本机个人库 `cta-path-a/UPGRADE_PLAN.md`。

---

## 方向总览

| 方向 | 阶段 | 状态 | 开放 |
|------|------|------|------|
| 尺子清洗（基差锁/纸面幂等/正式 BT 晋升） | Path-A P0 | **完成** | 封闭 |
| 影子台账 + 品类胜率 | Research shadow | **完成** | 封闭 |
| 期权研究 A→E | Options A–E | **完成** | 封闭 |
| 活链 Bid/Ask | Options **F1** | **完成** | 封闭 |
| 日积活链盘口（快速/有截止） | Options **F1b** | **完成** | 封闭 |
| 历史盘口 / 买方 / 全宇宙 / 写正式层 | Options **F+** | **延后** | **封闭（未开放）** |
| 多时段 brief | Session | 交 Grokbot | 本仓不做 |

**当前下一刀（已锁定，未开放）**：**F2** — 含 Bid/Ask 的信用价差研究 BT  

- **确定内容**：用活链 Bid/Ask 快照跑 `credit_vertical`（`pricing_mode=bid_ask`），对照 settle_discount；状态最高 WARN；不写 Path-A 正式层。  
- **开放条件**（满足其一即提醒）：CF 有盘口日 ≥10 **或** CF/SR/MA 各 ≥5。  
- **提醒通道**：日报 `[options-upgrade]`、Desk 期权研究面板、`data/options/upgrade_gate_latest.json`；你说「继续/升级」时先念 F2 内容与样本是否够，**等你确认再开干**。

---

## 期权轨进度（详）

| 阶段 | 内容 | 状态 | 迭代反馈摘要 |
|------|------|------|----------------|
| A | 审计+设计+OH-01 | 完成 | 文档三件套；ATM=0 热修 |
| B | Black-76 + CF/SR/MA 规格 | 完成 | 24 测过；gamma 薄包装 |
| C | 日链+质量闸+缓存过期 | 完成 | CF 多日快照；WARN 无盘口 |
| D | 信用价差 BT + Desk | 完成 | n=5 win0.4 state=WARN |
| E | 研究纸面+风险+日报 soft | 完成 | ledger 与 Path-A 隔离 |
| F1 | Tq 活链 Bid/Ask | 完成 | 离线测过；活连曾挂起需凭证/网络 |
| F+ | 见 ROADMAP | **封闭** | 无历史盘口不晋升 PAPER |

权威细节：`docs/options/ROADMAP.md`

---

## 下次升级（锁定）

| ID | 内容 | 门槛 | 状态 |
|----|------|------|------|
| **F2** | Bid/Ask 信用价差研究 BT + 与 settle 对照 | CF≥10 盘口日 或 三品种各≥5 | **等样本 / 等确认** |

代码闸门：`research/options/upgrade_gate.py`

## F+ 更后（仍封闭）

1. 买方/借记研究（仍 WARN）  
2. 扩样本后再谈全宇宙  
3. Path-A 写入 — **需你明示**  
4. 策略状态升 PAPER — 需人工评审  
 

---

## 本轮（F1）迭代反馈

- **做了**：`quote_bid_ask`、活链字段、`build_from_tq_live`、`--tq-live`  
- **验证**：`tests/test_options_tq_bidask.py` 等绿；历史 BT 仍 WARN  
- **风险**：Tq 实采依赖凭证与行情，曾超时；未默认挂死循环进日报  
- **下一刀**：开 F1b 日积活链盘口  

## 本轮（F1b）迭代反馈

- **做了**：Tq 快路径（跳过 IV）、`overall_deadline_s`、`accumulate_live_bidask`；日报 soft 挂载（45s/品种）；`--tq-live-only`  
- **产物**：`research/options/chain_store.accumulate_live_bidask`；`daily_update` soft  
- **验证**：无凭证 soft-fail 单测；历史 BT 仍 WARN、不晋升  
- **风险**：无历史盘口长度仍不足以抬策略状态  
- **建议下一刀**：停；样本日积后再开「含 bid_ask 的研究 BT」  
 

---

## 反馈模板（复制用）

```text
【迭代反馈 · <阶段ID>】
做了：
产物：
验证：
风险/未做：
建议下一刀：开 <ID> / 停
```
