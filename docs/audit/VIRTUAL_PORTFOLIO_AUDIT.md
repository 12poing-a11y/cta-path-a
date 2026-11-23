# CTA Virtual Portfolio 1.0 — Phase 0 审计报告

**规格来源**：ChatGPT Shared Content（CTA Virtual Portfolio 1.0 / Cursor 项目实施规格书 v1.0）  
**仓库**：`D:\AI\cta-path-a` · 轨 ID：**VP**  
**审计日期**：2026-11-23  
**性质**：**只读审计**；本阶段**未改**策略参数、信号引擎、`paper_book`、Notion、Actions、正式 BT、依赖版本。  
**验收**：本报告 + 三份附属文档齐备后 **停止**；未经确认不得进入 Phase 1。

---

## 0. 结论摘要

| # | 结论 |
|---|------|
| 1 | 正式纸面账本唯一写入点是 `paper_book.refresh_paper_book` → `paper_book_latest.json`（日更 / Desk 按钮 / sync）。VP **不得** import 该写入路径。 |
| 2 | `paper_book` 成交=信号日收盘、无手续费/滑点；正式 BT=`next_open`+成本。VP 必须自建成交与成本模型，**不能**复用 paper PnL 当 KPI。 |
| 3 | 仓库无账户/保证金/订单表/节假日日历抽象；这些是 Phase 1 硬缺口。 |
| 4 | `rule_lock.DIRTY_IGNORE_PREFIXES` 已含 `data/`。VP 状态应落在 `data/virtual_portfolio/`，避免挡正式周更/回测写盘。 |
| 5 | `member_rank.load_member_seats` **非只读**（缺缓存会联网并写 `.cache/member`）。VP 席位适配器须 **cache-only**。 |
| 6 | 诊断数据可用但口径不一：情绪影子新鲜、`sentiment_mds/latest` 冻结、`vol_engine` 仅 7 品种、席位缺数多为 fail-open。 |
| 7 | 最佳隔离先例：`research/options/paper/ledger.py`（物理隔离于 `paper_book`）。建议顶层包 `virtual_portfolio/`。 |
| 8 | 审计中观察到现有异常（见 §7），**本阶段不修**；不得把 `paper_book` 盯市当作 VP 验收真值。 |

---

## 1. 可直接复用（只读）

| 能力 | 路径 | 用法 |
|------|------|------|
| 日信号快照 | `l1_report.json` | JSON 只读；勿 import `daily_update`（import 有副作用） |
| 合约乘数/跳点/费率 | `universe.json` | `mult/tick/fee_*` |
| 成本公式 | `path_a_filters.fill_cost`、`research_cost.json` | 纯函数可复用逻辑，费用表自管 |
| 组合帽参考 | `position_rules.apply_portfolio_caps` | 仅作参考，VP 自定账户上限 |
| 质量掩码 | `research/data_quality/masks.py` | PASS/REJECT/STALE 等 |
| 交割规则 | `configs/calendar/delivery_rules.json` | |
| 日线缓存 | `.cache/sina/`、`.cache/history/` | **禁止**经 `fetch_history` 触发付费补洞 |
| 情绪影子 | `data/sentiment_mds/shadow/*.json` | 勿 import `sentiment_mds`（import 会 mkdir） |
| 波动引擎 | `data/vol_engine_latest.json` | 仅 7 个期权标的 |
| 诊断词表 | `desk/final_signal.resolve_final_action` | 复用「持有/建议平/观望」语义，或显式分叉 |

---

## 2. 需要适配器（只读封装）

| 适配器 | 原因 |
|--------|------|
| `adapters/l1.py` | 解析信号行；统一 `asof` / fingerprint |
| `adapters/bars.py` | 只读缓存；标明 continuous vs 交割月 |
| `adapters/seats_cache.py` | **禁止**调用会写缓存的 `load_member_seats` |
| `adapters/sentiment.py` | 优先 shadow 文件；缺失 → UNKNOWN |
| `adapters/vol.py` | 非 7 品种 → UNKNOWN |
| `adapters/cost.py` | 从 universe + research_cost 组装 VP 费用 |
| `adapters/paper_book_view.py` | 可选对照展示；永不写入 |

---

## 3. 必须独立开发

- 多账户 / 自定义起始资金 / 独立净值  
- 订单 → 成交（建议默认对齐正式口径 `next_open`，与 paper 收盘成交刻意分离并文档化）  
- 保证金与可用资金  
- 独立 JSONL 账本 + 幂等指纹  
- 手动开平仓与人工干预留痕（来源字段不可伪造为 `CTA_SIGNAL`）  
- 持仓诊断引擎（证据 / 反向证据 / 置信度）；**不得**直接改仓  
- Desk 独立页（只读展示优先）  

推荐布局：

```text
virtual_portfolio/          # 新顶层包
  guard.py                  # 只允许写 data/virtual_portfolio/**
  adapters/ …
  accounts.py / fills.py / ledger.py / diagnosis/ …
configs/virtual_portfolio/
data/virtual_portfolio/<account_id>/
desk/virtual_portfolio_panel.py
tests/test_vp_*.py
```

---

## 4. 当前缺失 / 暂不可实现

| 缺口 | 现状 | Phase 影响 |
|------|------|------------|
| 账户模型 | 无 | Phase 1 阻塞 |
| 订单/成交表 | 无（paper 只有开平事件） | Phase 1 |
| 保证金率 | 无 | Phase 1 可先静态表，真交易所保证金延后 |
| 平今费率 / 涨跌停 | 无 | Phase 1–3 |
| 交易所节假日日历 | 仅工作日启发式 | 诊断与成交时序风险 |
| 夜盘 | 日更不含夜盘 | 诊断须标注「日盘口径」 |
| Vol 全宇宙 | 仅 CF/SR/MA/TA/RU/AG/RB | 其余 UNKNOWN |
| DCE/东财席位长史 | 约自 2026-06 | 长窗席位诊断受限 |

---

## 5. 可能影响原系统的位置（严禁误触）

| 位置 | 风险 |
|------|------|
| `paper_book.refresh_paper_book` 及 Desk/sync 调用点 | 污染正式纸面账本 |
| `daily_update.py` 写 `l1_report*` / 触发 paper | 改信号或旁路 |
| `universe.json` / `execution_rules.json` / `formal_rule_lock.json` | 改正式参数 |
| `research/execution/rule_lock.py` | 放宽脏树规则会削弱正式写盘门禁 |
| `desk/strategies/extra/` | 被 KPI/评分扫描，模拟业绩混入对照 |
| `research/shadow_perf` | 若 schema 撞车会被当候选摄入 |
| `.github/workflows/daily.yml` pytest 全量门 | 脆弱 VP 测试会挡正式日更 |
| `member_rank` 写缓存 | 污染 CI 提交的 `.cache/member` |

---

## 6. 信号与执行时序（审计要点）

```text
日线源 → daily_update → l1_report
                ├─ quality_ok → refresh_paper_book（收盘成交、无成本）
                ├─ sentiment shadow / vol / tech / shadow_perf（soft）
                └─ 正式 BT/周更：next_open + 滑点手续费（rule_lock）
```

- 入场过滤：`entry_filter=seats`；缺席位多为放行（审计 BT-03）。  
- 可用性滞后：正式 BT 席位/升贴水 **1 会话**；paper 用当日。  
- VP 若跟信号开仓，必须显式选择：**跟 paper 收盘** 还是 **跟正式 next_open**（推荐后者 + 文档对比）。

---

## 7. 审计中发现的现有异常（不在本阶段修复）

1. **Palm 油 `P` 空单**：入场约 11-13、止盈目标约 8644；历史日线显示 11-18 低点曾刺穿目标，但 paper 仍持仓（后续价差 >5% 可能使分钟对齐失效、跳过日内止盈）。  
2. `equity_state.json` 未见写入点，权益与 paper 账面不一致。  
3. `sentiment_mds/latest.json` 冻结；日更只写 shadow。  
4. `.cache/history` 可能落后于 l1 asof（应用 sina 日缓存或刷新脚本）。  
5. `paper_book` 与正式 BT 成交口径长期分叉（P0 审计 PB-03）。

---

## 8. Phase 1 前需你确认的决策

1. VP 状态：仅本机 vs 独立 Actions 提交 `data/virtual_portfolio/`。  
2. 保证金：静态配置表 vs 外源。  
3. 仓位来源：仅 L1 自动信号 / 含手动单。  
4. 诊断词表：复用 `resolve_final_action` 还是独立集合。  
5. 与 **F2** 刀序关系：VP Phase 1 是否单独开刀、是否可与 F2 并行（当前仓库纪律：**一刀一开**）。

---

## 9. 交付清单

| 文档 | 路径 | 状态 |
|------|------|------|
| 本审计报告 | `docs/audit/VIRTUAL_PORTFOLIO_AUDIT.md` | 本文件 |
| 依赖图 | `docs/audit/VIRTUAL_PORTFOLIO_DEPENDENCY_MAP.md` | 已交付 |
| 数据字典 | `docs/audit/VIRTUAL_PORTFOLIO_DATA_DICTIONARY.md` | 已交付 |
| 风险登记册 | `docs/audit/VIRTUAL_PORTFOLIO_RISK_REGISTER.md` | 已交付 |

**下一步**：你审阅后确认 → 才可开放 **VP-Phase1**（账户与模拟交易）。在此之前 **不写业务代码**。
