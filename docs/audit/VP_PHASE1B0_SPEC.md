# VP Phase 1B-0 — 实施规格（信号只读 / 独立收件箱 / 权限隔离）

**日期**：2026-11-23  
**性质**：**规格 only**；本文件**不授权**写业务代码，直至你明示开刀。  
**上游裁决**：GPT 对 `feature/vp-phase1a-fix` 复核 → 1A = PASS(RESEARCH_ONLY)；1B-0 = **CONDITIONAL GO**。  
**依据**：`VIRTUAL_PORTFOLIO_DEPENDENCY_MAP.md`、`VP_PHASE1_GO_NO_GO.md` Q1、`permissions.py`、`daily_update.py` / `paper_book.py` 实路径。

---

## 0. 一句话

**可以让 VP 观察 CTA 信号，还不能让 VP 按信号交易。**  
1B-0 只做：只读解析 L1 → 校验/去重 → 写入 VP 独立收件箱 → Desk 查询。  
**禁止**：订单、成交、改资金/持仓、写 Paper Book、改正式信号、动 F2 / PA-001。

---

## 1. CTA 信号读取接口（代码核实，禁止猜测）

### 1.1 真源路径（以代码为准）

| 产物 | **实路径**（仓库根） | 写入方 | VP 权限 |
|------|----------------------|--------|---------|
| 日信号快照 | `l1_report.json` | `daily_update.build_l1_report` | **只读** |
| 风险档副本 | `l1_report_risk15.json` | 同上 | 只读（可选对照，非主源） |
| 归档 | `archive/l1_report_<asof>.json` | 同上 | 只读（历史回放） |
| Paper 消费同一主源 | `paper_book.L1_PATH = ROOT / "l1_report.json"` | `refresh_paper_book` | **禁止调用** |

**纠偏**：Phase 0 文档多处写 `data/l1_report.json`；**当前正式出口在仓库根** `l1_report.json`（`daily_update.py` L918、`paper_book.py` L21/L502、`desk/strategies/registry.py` path_a）。1B-0 适配器必须以实路径为准；若日后迁到 `data/`，只改适配器配置，不改正式写盘方。

`l1_report_fingerprint.json`：守卫名单已登记；**现树可能缺失**。1B-0 以 `asof` + 文件内容哈希为变更检测；指纹文件若存在则一并归档，缺失不挡只读。

### 1.2 禁止的读取方式

| 禁止 | 原因 |
|------|------|
| `import daily_update` | import 有副作用，可能触发写盘 |
| 调用 `paper_book.refresh_paper_book` | 正式纸面唯一写入口 |
| 写 `l1_report*` / `paper_book_latest.json` / `universe.json` | 污染正式层 |
| 猜测「第二信号源」或读 Desk 组装结果当真源 | 偏离依赖图 |

### 1.3 建议模块

```text
virtual_portfolio/adapters/l1.py   # 纯函数：读 JSON → 规范化行；无写正式路径
virtual_portfolio/signal_inbox.py  # 去重、落盘、查询；写路径仅 data/virtual_portfolio/**
```

适配器 API（草案）：

```text
load_l1_snapshot(root) -> dict | None
  # Path: root / "l1_report.json"；缺文件 / skipped → None；不抛写副作用

iter_signal_rows(snapshot) -> Iterable[NormalizedSignal]
  # 遍历 snapshot["signals"]（list）；字段映射见 §1.4

content_hash(snapshot_or_bytes) -> str
  # SHA-256；用于 inbox 幂等键
```

### 1.4 规范化字段（来自实文件 `signals[]`）

| 规范化键 | L1 源字段 | 说明 |
|----------|-----------|------|
| `signal_asof` | 报告 `asof` | 幂等主键之一 |
| `symbol` / `code` | `code` | 品种代码 |
| `ticker` | `ticker` | 交易所代码 |
| `direction_raw` | `direction` | 含「多/空/空仓」等 |
| `selected` | `selected` | paper 开仓过滤同口径 |
| `lots_l1` | `lots_l1` | |
| `sleeve` / `bucket` | `sleeve` / `bucket` | |
| `bar_date` | `bar_date` / `date` | |
| `close` / `atr` | `close` / `atr` | 仅归档，1B-0 **不**定价成交 |
| `action` / `align` | `action` / `align` | 诊断展示 |
| `source_path` | 常量 | `"l1_report.json"` |
| `source_hash` | 计算 | 整包或行级哈希 |
| `received_at` | VP 时钟 | ISO8601 |

**不在 1B-0 做**：把「空仓」转成订单、按 `selected` 自动开仓、重算 stop/target（那是 1B-1+）。

---

## 2. 独立收件箱

### 2.1 目录

```text
data/virtual_portfolio/signal_inbox/
  latest.json                 # 最近一次成功摄入摘要（可选）
  by_asof/<asof>.json         # 该 asof 规范化快照 + 元数据
  events.jsonl                # 追加：接收/拒绝/重复
  rejects.jsonl               # 校验失败明细（可选拆分）
```

所有写路径必须经 `assert_vp_write_path`；**不得**写到账户 ledger / positions（1B-0 与账户账本解耦）。

### 2.2 幂等键

```text
idempotency_key = sha256(signal_asof + "|" + code + "|" + direction_raw + "|" + source_hash_prefix)
```

同一键再次摄入 → `DUPLICATE`，不追加第二份业务行；可记 events 审计。

### 2.3 校验（失败入 rejects，不改账户）

1. 文件可读且 JSON 对象；非 `skipped`  
2. `asof` 非空  
3. `signals` 为 list  
4. 行级：`code` 非空  
5. 可选：`quality_ok is False` → 仍可归档，但标记 `QUALITY_WARN`（**不**触发交易）  
6. 合约映射：`code` 须能在 `configs/virtual_portfolio/instruments_v1.json`（或只读 universe 副本）解析；未知代码 → `UNMAPPED` 标记，仍可存原始行

### 2.4 Desk

只读面板：按 asof 列出收件箱行、重复/拒绝计数、源哈希。  
**无**「一键跟单」按钮。

---

## 3. 权限隔离（相对 1A 的硬改动）

### 3.1 现状问题

`assert_auto_open_allowed` **同时**要求 `AUTO_OPEN_ALLOWED` **与** `SIGNAL_INGEST_ALLOWED`。  
若为 1B-0 把 `SIGNAL_INGEST_ALLOWED=true`，等于为未来自动开仓松了一颗螺栓。

### 3.2 目标标志（fail-closed）

| 标志 | 默认 | 1B-0 目标 | 含义 |
|------|------|-----------|------|
| `ACCOUNT_MODE` | `RESEARCH_ONLY` | 保持 | 模式标签 |
| `SIGNAL_READ_ALLOWED` | **false** | 显式 **true** 才可读 L1→inbox | **新建**；只读+收件箱 |
| `SIGNAL_INGEST_ALLOWED` | false | **保持 false** | 留给 1B-1+「信号进入下单管线」 |
| `AUTO_OPEN_ALLOWED` | false | **false** | 自动开仓 |
| `AUTO_CLOSE_ALLOWED` | false | **false** | 自动平仓 |
| `MARGIN_STATUS` | `UNVERIFIED` | 不变 | 自动开仓仍要求 VERIFIED |

### 3.3 断言矩阵

| 操作 | 所需 |
|------|------|
| 读 L1 + 写 `signal_inbox/**` | `SIGNAL_READ_ALLOWED` |
| 手工开平仓（1A 已有） | `assert_manual_ops_allowed`（不变） |
| 自动开仓（未开放） | `AUTO_OPEN` + `MARGIN=VERIFIED` + `SIGNAL_INGEST`（**不要**用 READ 替代） |
| 写 paper / l1 / F2 | **永远禁止** |

实现时：`assert_signal_read_allowed`；**不得**让 `assert_auto_open_allowed` 因 READ=true 而放行。

### 3.4 配置落点

账户 `meta` / `configs/virtual_portfolio/` 运行时块；缺字段 → false（与 1A 一致）。

---

## 4. 硬门槛测试（开刀后必须全绿）

| ID | 断言 |
|----|------|
| T-RO-01 | 摄入前后 `l1_report.json` / `paper_book_latest.json` / upgrade_gate 字节不变 |
| T-RO-02 | 适配器路径下 **无** `import daily_update`、**无**调用 `refresh_paper_book`（静态或 monkeypatch 哨兵） |
| T-RO-03 | `SIGNAL_READ_ALLOWED=false` → 摄入抛 `VpPermissionError` |
| T-RO-04 | `SIGNAL_READ_ALLOWED=true` 且 `SIGNAL_INGEST/AUTO_*=false` → inbox 可写，**账户 ledger 不变** |
| T-RO-05 | 同一 asof 重复摄入 → DUPLICATE，events 可增、业务行不翻倍 |
| T-RO-06 | 写路径逃逸（指向 `paper_book_latest.json`）被 `VpGuardError` 拒绝 |
| T-RO-07 | 缺文件 / 坏 JSON → reject，不写账户 |

污染哨兵沿用 1A 套件；1B-0 测试文件建议 `tests/test_vp_phase1b0.py`，独立 tmp root。

---

## 5. 明确不在 1B-0

- 模拟订单 / 成交 / 改权益与持仓  
- L1 行情流、席位 loader 联网  
- 修改 `paper_book`、正式信号、F2、PA-001  
- 自动进入 **1B-1**（订单意图）或 **1B-2**（模拟成交）  
- 为省事把 `SIGNAL_INGEST_ALLOWED=true`

---

## 6. 开刀检查清单（人工）

1. 本规格已审阅；路径以根目录 `l1_report.json` 为准已确认  
2. 权限拆分方案同意（`SIGNAL_READ_ALLOWED` 新建）  
3. 你明示：「开 VP-1B-0」  
4. 落地后：本文件 + FIX/验收报告；**停**，等待 1B-1 单独审批  

---

## 7. 与 GitHub / 1A 关系

- 1A 代码合入 main **不**等于 1B-0 已开工  
- 本规格可随 1A PR 入库（文档）；实现另开分支 `feature/vp-phase1b0-signal-inbox`
