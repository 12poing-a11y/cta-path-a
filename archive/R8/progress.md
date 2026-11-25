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

## 第 2 步：对照组复现（`--out archive/R8/base/result.json --fill next_open`，live，180 秒）

- 说明：现有 `--out` 把参数当**文件**路径（传目录会生成名为 `base` 的无扩展名文件，并与后建的目录冲突），所以每组统一用 `--out archive/R8/<组名>/result.json`，产物仍在各组目录下。
- 与根目录正式结果 `historical_backtest_latest.json` 逐键比较（`archive/R8/_compare.py`，全部 130 个顶层键）：**123 个完全一致**，含 `ret_pct`、`gross_ret_pct`、`max_dd_pct`、`cost_yuan`、`closed_trades`、`closed_pnls`（57 笔）、`equity_curve`、`exits`、`equity_end`、`cost_scenario_contrast`（Stress 行）、`caps_*`、`contract_pack`。
- 7 个键不同：`git_sha` / `config_version.git_commit`（代码提交不同，预期）、`contract_prefetch.seconds`（耗时）、`input_snapshot.path` / `sha256`（argv 不同，预期）、`sources`（chart_cache 路径与 free_n 计数）、`input_snapshot.bars_sha256`、`adj_roll_days*`（AU 差 1）。
- **输入数据的真实差异（需要如实记录）**：`bars_sha256` 不同是因为 10 个品种（AG AL AU CU I MA NI PP SS TA）从 2026-07-29 起共 80 天的 **`oi`（持仓量）字段**一边有值一边为 None（数据源补填变化；merge 进来的 CI 缓存与上次本机运行不同）。**OHLC、日期、席位、carry、合约包完全一致**；`adj_roll_days` 的 AU 差 1 是 OI 口径的信息性计数。所有成交相关输出逐位相同，因此判定对照组复现成立，继续。后续每个实验组都核对 `bars_sha256` 等于本次 base 的（预注册规则），不等就停。

## 第 3 步：代码最小改动

- `historical_backtest.py`：新增 `--max-gross PCT`、`--equity YUAN`、`--min-lots N`（解析函数 `r8_overrides_from_argv`）。**只在带 `--out` 时生效**；不带 → stderr 报错、退出码 2、在拉任何数据之前返回。缺值、非法值（≤0 / 非数字 / min-lots 为负或小数）、与 `--compare/--hedge-grid/--rr-grid/--ctf/--roll-grid/--observe` 同用 → 退出码 2。生效值写进结果 `r8_overrides = {applied, formal_values}`；Stress 行沿用同一份 `p`，自然带覆盖值。不带这三个旗标时行为不变（C0 自检会再验证）。
- `tests/test_r8_overrides.py`：15 项（不带 `--out` 必须拒绝、`=` 形式、缺值/非法值、与其他模式互斥、合法组合进入运行头且不写文件、无旗标解析为空、仅 `--out` 不受影响）。
- 相关既有测试（rule_lock / audit / freeze_fix_gates / r8）37 passed。
