# R8 进度（放宽名义帽 + 本金规模 / 不足一手处理，纯研究）

- BASE = `85b3486`（R7b 已 push 后的 main）；分支 `r8-gross-equity`；不 push、不合入 main。
- 红线：不改 `execution_rules.json`、`universe.json`、`configs/formal_rule_lock.json`；所有运行带 `--out archive/R8/<名字>/`。
- 环境：`$env:PYTHONUTF8="1"`。

## 第 0 步：只读报告（BASE，冻结快照 `bt_input_20261125_016deed19684` 离线重放，`archive/R8/step0_base/`）

重放结果与根目录正式结果一致：Base −1.721% / 毛 +0.938% / 回撤 8.232% / 57 笔 / 期末权益 196,557.68。

### universe.json 当前值
| 项 | 值 |
|---|---|
| equity | 200000 |
| risk_pct | 2.0（%）；l1_mult 1.0；equity_compound true |
| min_lots（顶层） | **未配置 → 0** |
| max_positions | 3 |
| max_gross_exposure_pct | 50 |
| max_portfolio_risk_pct（ATR 风险帽） | 8 |
| max_per_bucket | 1 |
| min_r20 / min_r60 | 4 / 6 |
| entry_filter | seats；slippage_ticks 1 |
| observe 段 | equity 1,000,000；**min_lots 1**；symbols AU CU AL NI I JM SS；option_hedge enabled（premium_atr_mult 0.6, strike_atr_mult 0.0）。只在 `--observe`（回测）或日报观察袖套生效，正式口径不读 |

### min_lots>0 时引擎怎么处理（代码阅读，未改代码）
正式口径 `min_lots = int(cfg.get("min_lots") or 0) = 0`；`--observe` 才取 observe 的 1。min_lots>0 时有**两处**抬手：
1. `signal_core.sizing()`：算出 `lots < min_lots` 就**直接抬到 min_lots**（回测未传 `min_lots_guard_frac`，即无 ATR/价格守卫；日报观察袖套才传 0.25）。候选以抬后的手数进入组合帽。
2. `position_rules.apply_portfolio_caps` 第 6 步：名义缩放/风险缩放/补位/补手之后，仍 `< min_lots` 的入选候选**试抬到 floor，仅当抬后名义 ≤ 名义帽且 ATR 风险 ≤ 风险帽才保留，否则这一笔被丢弃**（不是强行抬）。
- 抬手**只查组合级名义帽和 ATR 风险帽（8%）**，没有"单笔风险 ≤ X%"检查，所以单笔实际风险可以远高于 2% 风险预算。
- `historical_backtest.py` 第 1769 行附近的 roll 分支（`mode == "roll"` 才跑）：`lots <= 0` 就 `continue`，**忽略 min_lots、不抬**；BASE 用 `seats`，该分支不执行。
- 算出 0 手的信号：`path_a_candidate` 返回 `status="lots0"`，主循环对 `status != "ok"` 直接 `continue`，即**跳过**。

### BASE 对照组统计
- **因算出 0 手被跳过的信号**：**125 个信号日**（(品种, 日) 评估通过动量/席位/carry/波动后算出 0 手；同一信号连续几天按天计）。分布 AG 58 / AU 31 / CU 20 / NI 14 / RU 2——都是高名义金属，2% 风险预算（¥4,000）买不起一手。
- **被抬到 min_lots 的笔数**：**0**（正式口径 min_lots=0，没有抬手）。
- **被抬手笔数的实际风险**：不适用（0 笔）。作为反事实：这 125 个信号若抬到 1 手，单笔风险占权益 **最小 2.01% / 中位 5.81% / 最大 25.26%**；其中 ≤3% 的 28 个、>3% 的 97 个。
- BASE 实际入场的 57 笔单笔实际风险：**最大 1.86% / 中位 0.557%**，0 笔 >3%。
- 参考：`caps_entry_gross_max` 49.83、`caps_entry_risk_max` 2.33、`caps_scaled_n` 64、曲线 gross_pct 最大 50.77（盯市漂移）。

产物：`archive/R8/_r8_stats.py`（离线重放 + 包装器统计，不改仓库代码）、`archive/R8/step0_base/stats_offline.json`、`run.log`。
