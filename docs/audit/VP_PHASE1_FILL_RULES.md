# VP Phase 1 — 模拟成交规范（草案）

**配套**：`VP_PHASE1_GO_NO_GO.md`  
**日期**：2026-11-23  
**性质**：规则锁定文档；**无代码**。默认对齐正式 Path-A `next_open`，**刻意不跟** `paper_book` 收盘成交。

---

## 1. 成交时序（防未来函数）

| 场景 | 规则 |
|------|------|
| 信号日 T 日盘结束后产生的 L1 信号 | **不得**以 T 日收盘价成交 |
| 默认 `fill_policy` | `next_open`：T+1 交易日开盘价 + 滑点 |
| T+1 开盘缺失 | 订单保持 `SUBMITTED`/`EXPIRED`（按会话截止）；**禁止**用收盘或前收替代开仓价 |
| 跳空 | 按实际开盘价成交；滑点仍计 |
| 涨跌停无法开/平 | 保留未成交；状态 `REJECTED:LIMIT_LOCK` 或继续挂到过期（Phase 1A 可简化为当日拒绝） |
| 信号重复 | 同一 `account_id`+`symbol`+`signal_asof`+方向：**幂等**，不得重复开仓 |
| 行情过期 | `REJECTED:STALE_BARS`；不得补价 |

## 2. 订单状态机（最低集）

```text
CREATED → SUBMITTED → PARTIALLY_FILLED → FILLED
                    ↘ REJECTED
                    ↘ EXPIRED
                    ↘ CANCELLED
```

Phase 1A 可先实现：`CREATED / SUBMITTED / FILLED / REJECTED / CANCELLED`（`PARTIALLY_FILLED` 可延后，但枚举预留）。

## 3. 与 paper_book / 正式 BT 对照

| 维度 | paper_book | 正式 BT | VP（本规范） |
|------|------------|---------|--------------|
| 成交价 | 信号日收盘 | next_open | **next_open** |
| 成本 | 无 | 有 | **有** |
| KPI | Desk 纸面 | 正式报告 | **独立**；禁止用 paper 浮盈验收 VP |

## 4. Phase 分轨

| 阶段 | 允许的 `source` | 自动跟 L1 |
|------|-----------------|-----------|
| **1A** | `MANUAL`、`SYSTEM_TEST` | **否** |
| **1B** | + `CTA_SIGNAL`（只读 L1 JSON） | 是（仍不写正式层） |
| 2+ | 诊断仅建议 | 诊断**不得**直接改仓 |

## 5. 拒绝开仓的硬条件（摘要）

- 缺 `margin_rate` / 缺乘数 / 缺开盘价  
- 非交易日（工作日启发式；完整官历延后）  
- 交割禁开窗（可复用 `delivery_rules` 研究近似）  
- `available` 不足以覆盖保证金+费用  
- 幂等键冲突  

任一触发 → 记 `REJECTED` + 原因码；**不得**降级为「用错误价硬成交」。
