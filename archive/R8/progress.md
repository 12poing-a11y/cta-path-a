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
