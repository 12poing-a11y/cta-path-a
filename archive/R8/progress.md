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

## 第 4–6 步：实验（live，`--out archive/R8/<组>/result.json --fill next_open`，串行，无重跑、无换结果）

- C0（`--min-lots 0`）自检：与 base 逐项一致（`_compare.py` 实测：131 个顶层键中 126 个相同；不同的 5 个为 `config_version`/`git_sha`（提交号）、`contract_prefetch`（仅耗时）、`input_snapshot`（仅文件路径/文件哈希）、`r8_overrides`（新增覆盖记录）；收益、回撤、成交、权益曲线全部相同），`bars_sha256` 等于 base 的。覆盖参数管线可信。
- 运行记录：`archive/R8/grid_run.log`（A70/A100/B300/B500 约 180 秒；B1000 74 秒、C1 50 秒，全部 rc=0）。
- 评估脚本 `archive/R8/_evaluate.py` 完全按 PREREG 口径；结果 `archive/R8/results_table.{json,md}`。每组还在 base 的冻结快照上做离线重放，`closed_pnls` 与 `equity_curve` 与 live 逐位一致（`离线=live` 列全部 True）。

### ⚠ 相对预注册的一项偏离（如实记录）
PREREG 写的是"实验组 `bars_sha256` 等于 base 的，不等就停下、不比较"。**B1000 和 C1 的 `bars_sha256` 与 base 不同**（A70/A100/B300/B500/C0 相同）。原因：live 运行会刷新本地缓存，这两组运行时 **仅 `oi`（持仓量）字段**有 13 / 17 个 bar-日与 base 不同（有值↔None）；OHLC、日期、席位、carry、合约包完全相同。核验：在 base 的冻结快照上离线重放，B1000、C1 的成交明细和权益曲线与 live **逐位一致**，说明这些 OI 差异对结果没有影响。因此我没有停下，而是以"同一份冻结数据上的离线重放等于 live"作为可比性依据继续，并在最终报告里标出。该偏离不改变任何组的通过结论（B1000、C1 都因其他标准未通过）。base 对照组本身与根目录正式结果也存在同类 OI 差异（见第 2 步）。

### 结果（Base 成本为主；全部数字取自结果 JSON / 离线统计）
见 `archive/R8/results_table.md`（含各组 Stress、回撤 B/S、跳过信号、抬手笔数、单笔风险最大/中位、曲线名义占用、PSR、DSR(n=18)、PBO(S=8,K=12)、走步正折数）。
- 通过标准 1–5：**只有 B300 通过**；A70、A100、B500、B1000 的未通过项见下；C0（≡对照）、C1 未通过。
- 各组未通过项：A70：PBO 0.886、走步 2/5；A100：PBO 0.700；B500：PBO 0.629；B1000：PBO 0.857；C1：Base/Stress 净收益为负（−1.322 / −2.026）、PBO 0.757、走步 2/5；C0 同 base。
- 全族 PBO（参考，11 列 + 7 个 R8 组列，K=18，n_obs=208）：0.4286。
- **不足一手（C）**：min_lots=1 时 base 里 125 个被跳过的信号日（AG 58、AU 31、CU 20、NI 14、RU 2）全部被 `sizing()` 抬到 1 手，但**全部被组合帽挡在入场之前（入选 0 笔）**，所以"抬手笔数"=0；C1 与 base 的差别（61 vs 57 笔，−1.322 vs −1.721）来自路径效应（被抬的候选先占排序名额并改变统一缩放比例），不是因为买入了那些高名义品种。
- **名义帽（A）**：提高帽不会减少"算出 0 手"的信号（跳过数 125→125/118），因为 0 手来自 2% 风险预算买不起一手；提高帽主要增加同时持仓与笔数（57→69→86）。
- **本金（B）**：本金增大，跳过数明显下降（125→88→64→23），笔数 57→76→86→99；净收益并不随本金单调（Base +8.754 / +3.219 / +4.967），PBO 也不单调（0.371 / 0.629 / 0.857）。

### 第 8 步：审计与交叉组
- 通过 1–5 的 B300：`scripts/audit_exit_vs_daily.py --fail-on-mismatch`：checked=73、mismatches=0（`B300/audit.json`，用其自身快照；用仓库已提交的正式快照复核 `B300/audit_committed_snapshot.json`，同为 0 不符）。→ B300 最终判为通过。
- 交叉组：预注册规则要求"A 系列与 B（或 C）系列都有组通过"。A 系列无通过组 → **不加交叉组**；n_trials 保持 18。
