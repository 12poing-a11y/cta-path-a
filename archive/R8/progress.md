# R8（分支 `r8-equity-filter`，BASE `85b3486`）进度

规格：R8a 本金网格（诊断）→ R8b 在实际本金 1,000,000 下过滤极端风险。预注册：`PREREG.md`（commit `834e89f`），勘误：`PREREG_ERRATUM.md`。
`PYTHONUTF8=1`；不 push、不合入；未改 `execution_rules.json`、`universe.json`、`configs/formal_rule_lock.json`。

## 第 0 步（只读，commit `8dc9c9e`）

`static_sizing.md` / `.json`。要点：卡住开仓的是名义不是风险；BASE 下 AG/AL/AU/CU/NI/RU 每天 1 手名义 > 整个名义帽；100 万下 AU、CU 开不出来、AG 一开就接近占满帽；
F1 的风险半条在 `min_lots=0` 下恒被 `floor` 挡掉（0/980 触发），R4b 补不回 0 手（0/125）；BASE 跳过 960 信号日 = 0 手 125 + 名义帽缩 0 178 + 持仓数已满 31 + 板块已满 626；216 个交易日从未满仓。

## 第 1 步 PREREG（commit `834e89f`，单独提交）

7 个新增组（E100k/E300k/E500k/E1000k + F1/F2/F1F2），n_trials = 18（若停在 R8a 则 15），披露性读法 n = 21。

## 第 2 步 对照组复现（未改任何代码的 BASE 上）

- 命令：`python historical_backtest.py --fill next_open --out archive/R8/base/result.json`（rc=0，52 秒；`--out` 在现有实现里是文件路径）。
- 与根目录正式结果比对（`_compare.py`）：130 键中 123 逐位相同，含 KPI、`closed_pnls`、`equity_curve`、Stress 行；不同的 7 个键见 `PREREG_ERRATUM.md`。**结果层面逐项一致，继续。**
- ⚠ **更正**：上一轮进度写的"bars 差异仅为 `oi`、OHLC 完全一致"**不准确**。本次逐字段比对：除 801 个 bar-日的 `oi` 外，窗口最后一天（2026-11-25）还有 36 处盘后结算前后版本的字段差异（含 AU 的 close/high/low）。已写入 `PREREG_ERRATUM.md`，并在任何实验运行前提交。该更正同样适用于上一轮 `r8-gross-equity` 分支 `progress.md` 里的那句话（该分支未改动）。

## 第 3 步 代码（commit `823ed8a`）

- `historical_backtest.py`：`--equity YUAN`、`--filter-unit-risk`、`--filter-atr-spike`，**只在带 `--out` 时生效**；不带 → stderr 报错、退出码 2、在拉任何数据之前返回；`--equity` 缺值/非数字/≤0、与 `--compare/--hedge-grid/--rr-grid/--ctf/--roll-grid/--observe` 同用 → 退出码 2。生效值写入结果 `r8_overrides = {applied, formal_values}`；过滤开启时结果多一个 `entry_filters = {开关, 阈值, hits, log}`，**关闭时正式输出键集不变**。
- `research/execution/entry_filters.py`（新）：`unit_notional_exceeds`、`unit_risk_exceeds`、`long_atr`、`atr_spike`（均为严格大于；ATR100 不可得返回 None → 不触发）。`AdjustedSeries.atr_n(i, n)`（新增；`atr_n(i,14)==atr14(i)` 有测试）。`signal_core.py` / `position_rules.py` / `book_core.py` 未改。
- 风险半条（`risk_per_lot > day_risk`）在引擎里实现为内部开关 `filter_unit_risk_budget`，**无 CLI 入口、本轮不启用**（第 0b 步已证明 `min_lots=0` 下恒不触发）；有测试证明它在 `min_lots=1` 时会触发。
- `tests/test_r8b_filters.py` 25 项：不带 `--out` 拒绝（4 种写法 + 与其他模式互斥 + 坏值）；纯函数触发/不触发/边界；`atr_n`≡`atr14`；ATR100 不足 100 根返回 None；F1/F2 在构造数据上触发和不触发各一例（不触发时结果与关闭逐位相同；触发时被拦的候选没进 `candidate_log` 的候选列表；F2 的 ATR14/ATR100 用独立公式复算一致）；**不用 T 日之后的数据**（截断/替换 T 之后的 K 线，ATR 值不变；整份数据把第 120 根起的 K 线改写，之前的过滤日志逐条相同）。全量 `pytest`：554 passed（原 529）。
- 回归：用新代码重跑第 0 步离线重放，断言等于根目录正式结果，`static_sizing.json` 与已提交版本逐字节相同。

## 第 4–8 步 实验（live，`--out archive/R8/<组>/result.json --fill next_open`，串行，无重跑、无换结果；`_run_groups.ps1`）

- R8a：E100k / E300k / E500k / E1000k 全部 rc=0（各约 55 秒）。停止规则（四档 Base 均 ≤ 0）**未触发**（E300k/E500k/E1000k 为正）→ 继续 R8b。
- R8b：F1 / F2 / F1F2 全部 rc=0（各约 55 秒）。
- 所有组 `bars_sha256` 与本分支 `base` 相同（`same_bars_as_base=True`），离线重放（在 `base` 的冻结快照上）与 live 的 `closed_pnls` / `equity_curve` 逐位一致（`offline_equals_live=True`）；过滤命中次数离线 = live。
- 评估：`archive/R8/_evaluate.py`（口径全部取自 PREREG）→ `results_table.{md,json}`、`evaluate_run.log`。
- 与上一轮结果复现比对：E300k / E500k / E1000k 的 Base / Stress 净收益（8.754/1.604、3.219/2.136、4.967/3.479）与上一轮 B300 / B500 / B1000 **完全一致**。
- 审计：预注册只要求对"满足 1–6"的组做；**没有组满足**，因此无强制审计。信息性地对 E1000k、F2 跑了 `audit_exit_vs_daily.py --fail-on-mismatch`：checked 92 / 78，不符 0（`E1000k/audit.json`、`F2/audit.json`）。
- 事后描述性诊断 `_f_diag.py` → `f_diag.json`（**在结果已知之后写的，不参与任何通过标准**）：F2 相对对照的价格盈亏差额约 +58.3k 元，被直接过滤的 20 笔合计 −3.5k，其余是路径变化；新出现的 15 笔合计 +54.2k，其中 FU 2026-09-24 一笔 +40.3k。F1 的 37 个拦截信号日全部是 CU / AG / AU（36 个在前半年）。

### 对预注册的偏离与判断（如实）
1. 勘误（`PREREG_ERRATUM.md`）：第 2 步发现输入快照差异不止 `oi`，还有窗口末日的盘后版本字段；结果逐位一致，放宽条款后继续，勘误在任何实验运行前提交。上一轮 `r8-gross-equity` 进度里"仅 `oi`"的说法不准确（该分支未改动）。
2. 离线重放统一使用本分支 `base` 的冻结快照（`bt_input_20261125_ba11733f7443`），而不是勘误里写的正式快照 `016deed19684`：因为所有 live 组的 `bars_sha256` 都等于 `base` 的，`base` 快照才是 live 运行的精确输入；正式快照上的重放已在第 0 步与回归中验证等于正式结果。
3. "被过滤掉的交易"按 PREREG 主口径在**对照组 E1000k 自己的路径**上判定（F1 = 0 笔；F2 = 前半年 13 笔 −6,533 元、后半年 7 笔 +3,071 元）。F1 自己路径上有 37 个拦截信号日（CU 16 / AG 13 / AU 8；后半年只有 1 个，CU 2026-09-10，1 手名义 = 名义帽的 110%），这些候选在对照路径上同样出现但没有一笔成交，所以对照路径上"被过滤的交易"是 0 笔。F1 与对照仍有差异（对照有、F1 没有的 2 笔：I 2026-05-18 −2.0k、AG 2026-11-09 −6.3k；F1 新出现 3 笔合计 −0.6k；7 笔同入场日的交易手数或出场不同），属于路径变化，**具体传导机制我没有逐项核实**。这也是 PREREG 把"主口径（对照路径上判定）"和"路径口径"并列报告的原因。
