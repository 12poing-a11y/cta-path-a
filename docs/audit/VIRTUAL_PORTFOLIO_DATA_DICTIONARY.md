# CTA Virtual Portfolio — Phase 0 数据字典

**配套**：`VIRTUAL_PORTFOLIO_AUDIT.md`  
**日期**：2026-11-23  
**范围**：审计到的现有字段 + Phase 1 建议 schema（**未落地**）。

---

## A. 现有正式 / 诊断源（只读）

### A.1 `data/l1_report.json`

| 字段（代表） | 含义 | VP 注意 |
|--------------|------|---------|
| `asof` / `generated_at` | 信号日 / 生成时刻 | 幂等指纹须含 asof |
| `rows[]` / 信号行 | 品种、方向、动作建议 | schema 以实盘文件为准 |
| fingerprint 文件 | `l1_report_fingerprint.json` | 变更检测 |

### A.2 `data/paper_book_latest.json`

| 字段 | 含义 | VP 注意 |
|------|------|---------|
| 开平事件 | 信号日**收盘**成交 | **无**手续费/滑点 |
| 持仓 / 浮盈 | 盯市 | 不可作 VP KPI 真值 |
| — | — | 仅对照展示 |

### A.3 `universe.json`（合约元数据）

| 字段 | 含义 |
|------|------|
| `mult` | 合约乘数 |
| `tick` | 最小变动价位 |
| `fee_*` | 手续费相关（与 `fill_cost` / research_cost 配合） |

### A.4 日线缓存

| 路径 | 内容 | VP 注意 |
|------|------|---------|
| `.cache/sina/` | 免费日线 | 优先 |
| `.cache/history/` | 历史连续 | 可能落后 asof；禁止付费补洞路径 |

### A.5 情绪 / 波动

| 路径 | 内容 | 缺口 |
|------|------|------|
| `data/sentiment_mds/shadow/*.json` | 日更影子情绪 | 优先用此 |
| `data/sentiment_mds/latest.json` | 正式 latest | **常冻结**，勿当日更真源 |
| `data/vol_engine_latest.json` | 波动引擎 | **仅** CF/SR/MA/TA/RU/AG/RB |

### A.6 席位缓存

| 路径 | 内容 | VP 注意 |
|------|------|---------|
| `.cache/member/` | 席位快照 | **cache-only**；勿调会联网写盘的 loader |

### A.7 规则 / 成本配置

| 路径 | 用途 |
|------|------|
| `configs/calendar/delivery_rules.json` | 交割月规则 |
| `research_cost.json` + `path_a_filters.fill_cost` | 正式成本口径参考 |
| `position_rules` / 组合帽 | 仓位上限参考 |

---

## B. Phase 1 建议 VP 状态（目标 schema，未实现）

根目录：`data/virtual_portfolio/<account_id>/`

### B.1 `account.json`

| 字段 | 类型 | 说明 |
|------|------|------|
| `account_id` | str | 稳定 ID |
| `name` | str | 展示名 |
| `currency` | str | 默认 CNY |
| `initial_cash` | float | 起始资金 |
| `created_at` | ISO8601 | |
| `status` | enum | `active` / `archived` |

### B.2 `ledger.jsonl`（追加）

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | str | 幂等键 |
| `ts` / `asof` | str | 事件时间 / 业务日 |
| `kind` | enum | `open` / `close` / `adjust` / `deposit` / `withdraw` / `fee` |
| `symbol` | str | 品种代码 |
| `side` | enum | `long` / `short` / `flat` |
| `qty` | float | 手数 |
| `price` | float | 成交价 |
| `fee` | float | 手续费 |
| `slippage` | float | 滑点成本（可 0） |
| `source` | enum | `CTA_SIGNAL` / `MANUAL` / `DIAGNOSIS_HINT`（hint 不得伪造成交） |
| `signal_asof` | str? | 关联 L1 日 |
| `note` | str? | 人工备注 |

### B.3 `positions.json`

| 字段 | 说明 |
|------|------|
| `symbol` / `side` / `qty` | 持仓 |
| `avg_price` / `realized_pnl` | 成本与已实现 |
| `opened_asof` / `last_mark` | 开仓日 / 最近盯市 |

### B.4 `equity.json` / 日序列

| 字段 | 说明 |
|------|------|
| `asof` | 业务日 |
| `equity` / `cash` / `margin_used` / `available` | 净值结构 |
| `unrealized_pnl` | 浮盈 |

### B.5 `orders.jsonl`（可选 Phase 1）

| 字段 | 说明 |
|------|------|
| `order_id` / `status` | `pending` / `filled` / `cancelled` / `rejected` |
| `intent` | 信号意图 vs 成交结果分离 |
| `fill_policy` | 建议默认 `next_open`（与 paper 收盘刻意不同） |

### B.6 `diagnosis/<asof>.json`（Phase 2+）

| 字段 | 说明 |
|------|------|
| `symbol` / `stance` | 诊断立场 |
| `evidence` / `counter_evidence` | 列表 |
| `confidence` | 0–1 |
| `suggested_action` | **建议**，不自动改仓 |
| `data_flags` | `UNKNOWN_VOL` / `STALE_BARS` / `SEAT_CACHE_MISS` 等 |

---

## C. 口径对照（强制文档化）

| 维度 | paper_book | 正式 BT | VP（建议） |
|------|------------|---------|------------|
| 成交价 | 信号日收盘 | 次日开盘 | **次日开盘**（可配置，但默认对齐正式） |
| 手续费/滑点 | 无 | 有 | 有（自管表） |
| 写入路径 | `paper_book_latest` | BT 产物 | `data/virtual_portfolio/` |
| KPI | Desk 纸面 | 正式报告 | **独立**，禁止混用 paper 浮盈 |

---

## D. 未知 / 待确认字段源

| 需求 | 现状 |
|------|------|
| 保证金率 | 无仓库真源 → 静态配置表 |
| 平今 vs 平昨 | 无 |
| 涨跌停价 | 无 |
| 交易所节假日 | 无完整日历 |
| 夜盘 OHLC | 日更不含 |
