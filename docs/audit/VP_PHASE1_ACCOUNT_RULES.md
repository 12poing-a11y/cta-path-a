# VP Phase 1 — 账户与资金核算规则（草案）

**配套**：`VP_PHASE1_GO_NO_GO.md`  
**日期**：2026-11-23  
**性质**：规则锁定文档；**无代码**。Phase 1A 实现须遵守本表。

---

## 1. 账户

| 项 | 规则 |
|----|------|
| 隔离 | 每账户独立目录 `data/virtual_portfolio/<account_id>/` |
| 起始资金 | 创建时设定 `initial_cash`；之后仅经 `deposit`/`withdraw` 事件变更本金口径 |
| 多账户 | 禁止跨 `account_id` 读写；净值不得串账 |
| 币种 | 默认 CNY |

## 2. 权益恒等式（日终）

```text
equity           = cash + unrealized_pnl
                   （或等价：cash + Σ mark_to_market 持仓价值贡献）
margin_used      = Σ |qty| × mult × mark × margin_rate   （静态表）
available        = equity − margin_used − frozen
frozen           = 未成交订单预占保证金 + 预估手续费（可先 0，但字段保留）
```

| 项 | 规则 |
|----|------|
| 浮动盈亏 | `(mark − avg_price) × mult × qty`；空头符号反向 |
| 已实现盈亏 | 平仓腿：价差×乘数×手数 − 开平手续费 − 滑点成本 |
| 强平 | Phase 1A：**仅风险预警**（`MARGIN_WARN` / `MARGIN_BREACH`），不自动强平 |

## 3. 保证金

| 项 | 规则 |
|----|------|
| 来源 | **静态配置** `configs/virtual_portfolio/margin_rates.json`（Phase 1A 新建；本阶段只定规则） |
| 缺省 | 品种无 `margin_rate` → **拒绝新开仓**（`REJECTED:MISSING_MARGIN`），不得用魔法默认值偷偷成交 |
| 与正式层 | 不写回 `universe.json`；不把 VP 保证金当 Path-A 正式风控 |

## 4. 手续费与滑点

| 项 | 规则 |
|----|------|
| 手续费 | 优先复用 `universe.symbols[].fee_yuan` / `fee_rate` + `path_a_filters.fill_cost` 逻辑；VP 自管调用，不改正式表 |
| 平今 | Phase 1A：**未区分平今** → 文档标注 `close_today_fee=UNKNOWN`；有平今表前用「开/平同费率」并打 flag |
| 滑点 | 默认对齐 `research_cost.path_a_fill.slippage_ticks`（Base=1 tick）；可按账户覆盖，不得 silent 0 |

## 5. 盯市行情

| 项 | 规则 |
|----|------|
| 来源 | 只读 `.cache/sina` 优先，其次 `.cache/history` |
| 缺失/过期 | 当日不得新开；已有持仓盯市标记 `STALE_MARK`；**禁止捏造成交价** |
| 夜盘 | Phase 1 口径 = **日盘**；文案强制标注 |

## 6. 人工干预

| 项 | 规则 |
|----|------|
| 入金/出金/手工开平 | `source=MANUAL`；必须 `note` + `actor` |
| 禁止 | 将手工单标记为 `CTA_SIGNAL` |
