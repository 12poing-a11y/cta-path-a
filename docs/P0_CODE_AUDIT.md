# P0 代码级审计清单（研究可信度）

**日期**：2026-11-15  
**范围**：`historical_backtest.py` · `paper_book.py` · `research/execution/*` · `research/data_quality/*` · `daily_update.py` · `research/governance/*`  
**约束**：不改正式 Path-A 参数；本文件只列问题与修法。  
**状态**：清单已定；修复按 `PHASE2_AUDIT_DECISIONS.md` P0 顺序推进。

---

## 总览

| ID | 严重度 | 摘要 |
|----|--------|------|
| BT-01 | **P0-blocker** | 入场用合约开、止盈止损/盯市用连续 → 同日假止盈/止损与基差同号相关 |
| CP-01 | **P0-blocker** | `active_front_contract`=日历近月，≠连续跟随的 OI 主力 → 放大 BT-01 |
| PB-01 | **P0-blocker** | 同日二次 `refresh_paper_book`：新开仓可被当日盘前 15m 误平，权益仍累加 |
| PB-02 | P0 | 纸面开仓不相对已有持仓执行 Top3/板块/名义帽 |
| BT-02 | P0 | proxy 占比未进主 KPI / `cost_scenario_kpi` |
| BT-03 | P0 | 席位缺失 fail-open（「缺席位」仍可进） |
| DQ-01 | P0 | 涨跌停/连续不可成交/陈旧等闸门在真实数据上基本不触发 |
| GV-01 | P0 | `evaluate_strategy_gate` 无生产接线；布尔由调用方自报 |
| DU-01 | P0 | 日报几乎无陈旧熔断；`asof` 偏运行日而非 bar 日 |

---

## 四个审计问答（证据摘要）

1. **连续代理能否在主 KPI 里静默扭曲盈亏？**  
   **能，且已在发生。** 主 KPI 无 proxy 份额；`fill_series=mixed` 仅全局标签。大基差交易组与同日止盈/止损方向高度相关 → 正式 −7.6%/DD20.5% **暂不可单独解读**。

2. **`paper_book` 同日双跑是否幂等？**  
   **否。** 持仓去重与 ledger `trade_id` 有防护；入场日 15m 全段扫描 + 权益在 append 前累加 → 可误平并改权益。多写入点：daily / desk 按钮 / sync。

3. **Stress/Extreme 是否总挂在正式 scorecard？**  
   **否。** 仅默认 `main` 分支挂 Stress；Extreme 常未跑；`--rr-grid` 等仍可写正式文件；gate 未读产物。

4. **质量失败是拦开仓还是只打日志？**  
   **分流。** 回测：`classify_bar≠PASS` 拦单笔开仓；日报：`validate_signals` 硬熔断整份正式报告；大量旁路（席位不全、分钟、IV…）仅 warning。

---

## 修复顺序（禁止改策略参）

1. **BT-01 + CP-01 + BT-02** — 价格基础锁 + 主力映射 + proxy 进 KPI → 重跑 scorecard  
2. **PB-01…PB-05** — 幂等、入场日保护、组合帽、原子写、拒绝回退 asof  
3. **DU-01 / DU-03** — 陈旧熔断；live/回测席位可用日对齐  
4. **GV-01… + BT-04/07** — Gate 接线；扫参不得覆盖正式 KPI；登记试验次数  
5. **DQ-01** — 复活或删除惰性闸门（禁止「写了等于没写」）

---

## 分文件要点

### `historical_backtest.py`

- **BT-01**：按持仓锁定 `fill_price_basis`；合约仓只用合约 OHLC 管理；代理仓全程连续。  
- **BT-02**：`closed_pnls` 带 `fill_price_basis`；汇总 `proxy_entry_share`；超阈警告/扣留正式文件。  
- **BT-03**：输出 `seat_coverage_pct`；低于阈值标 degraded。  
- **BT-04…13**：跳空穿止损用 open 成交、缺 bar 盯市、扫参不写正式路径、复现 `--from-snapshot` 等见完整子代理报告（会话归档）。

### `paper_book.py`

- **PB-01**：`asof` 未变且报告指纹相同 → no-op；`entry_date==asof` 跳过当日 15m 止盈止损（或仅用入场后 bar）；权益仅在 ledger 真正 append 后变更。  
- **PB-02**：开仓前按 `kept` 重算 slots/bucket/gross。  
- **PB-03**：对齐 next_open + 成本 + `classify_bar`（与回测同口径）。  
- **PB-05**：`tmp` + `os.replace`；坏 JSON 失败而非重种子。

### `research/execution/`

- **CP-01**：按 OI/成交量或连续合约映射选主力；合约–连续超差 → 强制 proxy。  
- **CP-02**：`allow_continuous_fill` 反映真实决策；低覆盖勿「假 mixed」。

### `research/data_quality/`

- **DQ-01**：填涨跌停/陈旧；默认 `price_basis` 不可默认为可成交 contract。  
- **DQ-02**：聚合 `quality_score` 进产物。

### `daily_update.py`

- **DU-01**：每品种 `bar_date == expected session`。  
- **DU-03**：席位滞后与回测一致。

### `research/governance/`

- **GV-01**：scorecard 调用 gate，布尔从产物推导。  
- **GV-02**：「reported」≠「passed」；补阈值。  
- **GV-04**：`record_experiment` 尊重 `root`；正式回测必须登记。

---

## 静默降级一览（摘）

| 位置 | 行为 | 主 KPI 可见？ |
|------|------|----------------|
| overlay 失败 | 退回连续代理 | 弱 |
| `allow_continuous_fill` 恒 True | 连续闸门永不触发 | 否 |
| stress 加载失败 | fee_mult 可能仍为 1 | 否 |
| 缺席位 | 仍可开仓 | 仅统计 |
| 坏 paper JSON | 重种子清空流水 | 否 |

---

## 本轮已落地修复（2026-11-15）

### paper_book（PB-01）

- 同 asof + 同 `l1_fingerprint` → **refresh no-op**
- `entry_date == asof` → **跳过当日 15m 止盈止损**
- 权益仅在 ledger **真正 append** 后累加；原子写；拒回退 asof；坏 JSON 失败
- 测试：`tests/test_paper_book_idempotent.py`

### 混价锁死（BT-01 / CP-01 / BT-02）

- `manage_ohlc_bar`：合约成交只用 `contract_*` OHLC 管止盈止损/盯市；缺合约 OHLC **不回退连续**
- 合约仓 **不用** 连续 15m 管理（防假穿）
- overlay：`|合约收/连续收-1| > 3%` → 强制 `continuous_proxy`，清除 `contract_open`（`basis_rejected`）
- 主 KPI 增加 `proxy_entry_share` / `contract_entry_share` / `same_day_exit_n`；偏高时 conclusion 附加警告
- 测试：`tests/test_basis_lock.py`

其余 Gate 接线 / 日报陈旧熔断等按上表继续。
