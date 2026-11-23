# CTA Virtual Portfolio — Phase 0 依赖图

**配套**：`VIRTUAL_PORTFOLIO_AUDIT.md`  
**日期**：2026-11-23  
**约定**：`→` = 只读消费；`⇏` = 禁止写入/触发写路径。

---

## 1. 现有正式链路（不得改）

```text
日线源 (.cache/sina|history|tq)
    → daily_update.build_l1_report
        → data/l1_report.json  (+ asof / fingerprint)
        → [quality_ok] paper_book.refresh_paper_book
              ⇏ data/paper_book_latest.json
        → sentiment shadow / vol_engine / tech / shadow_perf (soft)
正式 BT / 周更
    → next_open 成交 + research_cost + rule_lock 脏树门禁
Desk
    → 读 l1 / paper；按钮可再调 refresh_paper_book
```

---

## 2. 建议 VP 目标拓扑

```text
                    ┌─────────────────────────────────────┐
                    │  正式世界（只读边界）                  │
                    │  l1_report / universe / cost configs │
                    │  .cache/* / sentiment shadow / vol   │
                    │  paper_book_latest (对照，可选)      │
                    └──────────────────┬──────────────────┘
                                       │ adapters/* (RO)
                                       ▼
┌──────────────────────────────────────────────────────────┐
│  virtual_portfolio/                                      │
│    signals → orders → fills → ledger → equity            │
│    diagnosis (只产出建议，不直接改仓)                      │
│  写入域：仅 data/virtual_portfolio/<account_id>/**        │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
              desk/virtual_portfolio_panel (展示)
```

---

## 3. 模块级依赖（Phase 1+ 设计约束）

| VP 模块 | 可读 | 禁止 |
|---------|------|------|
| `adapters/l1` | `data/l1_report*.json` | import `daily_update` |
| `adapters/bars` | `.cache/sina`、`.cache/history` | `fetch_history` 付费补洞 |
| `adapters/seats` | `.cache/member` 已有文件 | `member_rank.load_member_seats` |
| `adapters/sentiment` | `data/sentiment_mds/shadow/*.json` | import `sentiment_mds` 写盘 |
| `adapters/vol` | `data/vol_engine_latest.json` | 改 vol 引擎参数 |
| `adapters/cost` | `universe.json`、`research_cost.json`、`fill_cost` 逻辑 | 改正式费用表 |
| `adapters/paper_view` | `paper_book_latest.json` | `refresh_paper_book` |
| `ledger` / `fills` | 仅自有状态 | 任何 `data/paper_*`、`l1_report*` |
| `diagnosis` | 上列 + 自有仓位 | 直接下单写 ledger（须经人工/策略闸门） |
| `desk` 面板 | VP 状态 + 只读正式快照 | 调用 paper 刷新 / 改信号 |

---

## 4. 与 options paper 的类比

| | Options paper | CTA VP（目标） |
|--|---------------|----------------|
| 包 | `research/options/paper/` | `virtual_portfolio/` |
| 状态 | `data/options/paper/` | `data/virtual_portfolio/` |
| 与 `paper_book` | 物理隔离 | **同样隔离** |
| 正式信号 | 不碰 Path-A L1 | 只读 L1 |

---

## 5. CI / 规则锁交互

```text
rule_lock.DIRTY_IGNORE_PREFIXES ⊇ data/
  → data/virtual_portfolio/** 写入不挡正式周更/回测（与其它 data 一致）

daily.yml pytest
  → VP 测试须稳健或标记可选，避免挡正式日更

git / Actions
  → Phase 1 前确认：VP JSON 是否入库提交
```

---

## 6. 刀序关系（仓库纪律）

```text
当前锁定下一刀（期权轨）：F2（内容闸，未开）
VP 轨：Phase 0 审计完成 → Phase 1 待确认开刀
一刀一开：未确认前不写 VP 业务代码，也不自动开 F2
```
