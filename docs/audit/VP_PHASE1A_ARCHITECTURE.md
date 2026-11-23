# VP Phase 1A — 架构说明

**授权**：ChatGPT 会话「CTA模拟仓可行性分析」批准 Conditional GO（2026-11-23）  
**范围**：独立虚拟账户与账本基础设施；**不接**自动 L1；不改 `paper_book` / F2 / universe 原始字段。

---

## 1. 目标

证明：多账户资金与持仓可隔离核算、手工成交可留痕、缺保证金可标记、正式层不被污染。

## 2. 包布局

```text
virtual_portfolio/           # 新顶层包（对标 options paper 隔离模式）
  guard.py                   # 写入路径白名单：仅 data/virtual_portfolio/**
  paths.py                   # 账户目录解析
  instruments.py             # 版本化品种参数（保证金/乘数/手续费）
  accounts.py                # 开户 / 列表
  ledger.py                  # 追加-only JSONL + 幂等
  engine.py                  # 入金、开平仓、盯市、从账本重建
  __init__.py

configs/virtual_portfolio/
  instruments_v1.json        # 品种参数表（不写回 universe.json）
  schema_versions.json       # schema 版本登记

data/virtual_portfolio/<account_id>/
  account.json               # 投影（可由 ledger 重建）
  ledger.jsonl               # 唯一真相源（追加）
  positions.json             # 投影
  equity.json                # 投影

desk/virtual_portfolio_panel.py   # 查询 + 手工操作（非正式 KPI）
tests/test_vp_phase1a.py
```

## 3. 真相源与投影

- **真相源**：`ledger.jsonl`（事件驱动；禁止静默改余额字段）。  
- **投影**：`account.json` / `positions.json` / `equity.json` 由 `rebuild_account` 从 ledger 导出。  
- **订正**：只追加补偿事件（`adjust` / `correct`），不改写历史行。

## 4. 写入围栏

`guard.assert_vp_write_path(path, root)`：路径必须落在 `data/virtual_portfolio/` 下。  
包内**禁止** import `paper_book.refresh_paper_book` / `daily_update`。

## 5. 保证金分层

instruments 表分列：`margin_rate_*_exchange` / `_broker` / `_stress`。  
核算默认用 **broker** 层；三层皆空 → 事件打 `MARGIN_DATA_MISSING`，`margin_complete=false`，**不**静默填默认值。  
乘数/跳点缺失 → **拒绝**开仓。

## 6. 成交（1A）

- 仅 `source ∈ {MANUAL, SYSTEM_TEST}`。  
- `fill_policy=next_open`：由操作者提供已核对的次日开盘价（本阶段不自动拉行情下单）。  
- 成本：滑点 ticks（默认对齐 research_cost Base）+ 开/平手续费；平今若缺则 `close_today_fee=UNKNOWN` 并回退 close 费率且打 flag。

## 7. Desk

独立页「虚拟组合」：账户列表、权益、持仓、ledger 尾部、手工入金/开平。  
**不**挂 `strategies/extra`，不进正式 scoreboard。

## 8. 明确不做（本刀）

自动跟 L1、诊断、改 paper/信号/universe 字段、解锁 F2、修 PA-001。
