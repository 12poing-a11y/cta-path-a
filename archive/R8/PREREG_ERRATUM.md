# PREREG 勘误（第 2 步发现；在任何实验组运行之前提交）

对象：`archive/R8/PREREG.md` §7 第 1 条"差异是 `input_snapshot.bars_sha256` 里的持仓量 `oi` 字段（OHLC、日期、…完全一致）才继续"。

## 事实（`archive/R8/_bars_diff.py`、`_bars_diff2.py` 实测）

对照组复现 `archive/R8/base/result.json`（输入快照 `bt_input_20261125_ba11733f7443`）与根目录正式结果（快照 `bt_input_20261125_016deed19684`）：

- 130 个顶层键中 123 个逐位相同，包括 `ret_pct`、`gross_ret_pct`、`max_dd_pct`、`cost_yuan`、`closed_trades`、`closed_pnls`、`equity_curve`、`exits`、`cost_scenario_contrast`（Stress 行）、`caps_entry_gross_max`、`contract_pack`。
- 7 个不同的键：`git_sha` / `config_version.git_commit`（代码提交不同）、`contract_prefetch.seconds`（耗时）、`input_snapshot.{path,sha256,bars_sha256}`、`sources`（缓存路径与 `free_n` 计数）、`adj_roll_days` 与 `adj_roll_days_in_window`（仅 AU 差 1）。
- `bars` 差异的**真实构成**（这与 PREREG 原文和上一轮进度里"仅 `oi`"的说法**不一致**，如实更正）：
  - `oi` 字段：801 个 bar-日（有值 ↔ None），分布在 19 个品种的历史里；
  - **非 `oi` 的差异全部落在窗口最后一天 2026-11-25（第 276 根 bar）**，共 36 处：10 个品种该日的 `open`（数值略有不同，例如 AL 21200 vs 21240、AU 782.0 vs 784.6、CU 91800 vs 91790）、`settle` / `open_interest`（有值 ↔ None）、`volume`（AL、AU），以及 AU 该日的 `close`（755.4 vs 757.4）、`high`、`low`、`basis_rel`。这是数据源在盘后结算前后给出的两个版本，不是历史被改写。
  - 没有任何长度不一致，没有 11-25 之前的 OHLC 差异。

## 为什么仍可继续

1. 最后一天（T = 2026-11-25）产生的信号没有 T+1 成交日，不可能入场；该日只参与持仓的收盘盯市与止损/止盈触发判断。所有成交相关输出（`closed_pnls`、`equity_curve`、KPI、Stress 行）已被证明逐位相同，说明这些差异在本样本里没有改变任何一笔成交或任何一个权益点。
2. 磊对第 2 步的硬性要求是"结果必须和根目录正式结果逐项一致，不一致就停下"。结果层面逐项一致，该条件满足。
3. PREREG §7 对输入哈希的限定是我写的保守条款，写的时候没有核对差异的真实构成。此处**按真实构成放宽为**：允许差异 = ① `oi` 字段；② 最后一个交易日（窗口终点）那一根 bar 的盘后结算前后两版字段。**只要出现窗口终点之前的 OHLC / 日期 / 席位 / carry / 合约包差异，仍然停下。** 这条在实验组上同样适用，且离线重放与 live 的逐位比对仍然是必要条件。

## 对"各实验组 `bars_sha256` 应等于 base"的影响

live 运行会刷新本地缓存，各实验组的 `bars_sha256` 可能与 `base` 不同。处理方式不变：以"在冻结快照上的离线重放，`closed_pnls` 与 `equity_curve` 与 live 逐位一致"为可比性依据，并报告 `bars_sha256` 是否相同。离线重放统一用**正式冻结快照 `016deed19684`**（根目录正式结果自己的输入），而不是本次 `base` 的快照。

本勘误不改变任何分组、阈值、通过标准或 n_trials。
