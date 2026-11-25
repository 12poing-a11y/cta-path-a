# R8 预注册（纯研究；不动正式口径）

- 日期：2026-11-25。BASE = `85b3486`，分支 `r8-gross-equity`。
- **本文件在任何 R8 实验运行之前提交。跑完之后不加组、不改标准、不改口径。** 结果好坏照实报告，不给"改正式口径"的建议。
- 红线：不改 `execution_rules.json`、`universe.json`、`configs/formal_rule_lock.json`；覆盖参数只在带 `--out` 时生效；所有运行输出到 `archive/R8/<组名>/`。

## 1. 对照组（control）

BASE 根目录正式结果（v14，窗口 2026-01-05→2026-11-25，seats / next_open，本金 20 万，名义帽 50，min_lots 0）：

| | 净收益 | 最大回撤 | 笔数 |
|---|---|---|---|
| Base 成本 | −1.721% | 8.232% | 57 |
| Stress 成本 | −2.339% | 7.66% | 57 |

第 2 步在写任何实验代码之前，用 `historical_backtest.py --fill next_open --out archive/R8/base/` 复现，必须与根目录正式结果逐项一致（KPI、`closed_pnls`、`equity_curve`、Stress 行）；不一致就停下报告。
所有实验组的输入必须与对照组相同：`input_snapshot.bars_sha256`、`member_sha256`、`carry_sha256`、`contract_bars_sha256` 必须等于 `archive/R8/base/` 的；不等就停下，不比较。

## 2. 网格（共 7 组，固定）

默认值：本金 200,000；名义帽 50；min_lots 0；其他参数全部不变（含 ATR 风险帽 8%、max_positions 3、risk_pct 2%、bucket 1）。

| 组名 | 变动 | 命令行覆盖 |
|---|---|---|
| A70 | 名义帽 70 | `--max-gross 70` |
| A100 | 名义帽 100 | `--max-gross 100` |
| B300 | 本金 30 万 | `--equity 300000` |
| B500 | 本金 50 万 | `--equity 500000` |
| B1000 | 本金 100 万 | `--equity 1000000` |
| C0 | 不足一手直接跳过 | `--min-lots 0` |
| C1 | 不足一手抬到 1 手 | `--min-lots 1` |

- C0 在数值上应等同对照组（正式口径本来就是 min_lots=0），**用作覆盖参数管线的自检**：C0 必须与 base 逐项一致，否则停下。C0 仍计入试验数（保守）。
- 交叉组：**最多 1 个**，仅当"两边都有组通过"时才加，规则写死，不看结果挑：
  - "通过的组里最好"= Stress 净收益最高者；并列取最大回撤较小者。
  - 若 A 系列和 B 系列都有通过的组：交叉组 = A 最好 × B 最好（`--max-gross` 与 `--equity` 同时给）。
  - 否则若 A 系列和 C 系列（只有 C1 可能通过）都有通过的组：交叉组 = A 最好 × C1。
  - 否则不加交叉组。
  - 交叉组用上面同一套标准判定，不再扩展。
- **n_trials（DSR 用）**：基线 11 + 7 组 = **18**；加了交叉组则 **19**。该数在跑之前固定，不随结果改变。

## 3. 指标定义（全部取自各组 `--out` 的结果 JSON，Base 成本为主、Stress 成本并列）

- **净收益**：结果 `ret_pct`；Stress 取 `cost_scenario_contrast.rows.stress.ret_pct`（每组都跑，除非带 `--no-cost-stress`，R8 不带）。
- **最大回撤**：Base 的 `max_dd_pct`；Stress 取其行的 `max_dd_pct`。
- **单笔实际风险**（占权益%）：`|entry − stop| × lots × 合约乘数 ÷ 入场前一个交易日收盘权益`，对 Base 成本的全部已平仓交易计算，取最大值与中位数。（与 `_candidate_offline.py::kpis` 同口径。）
- **跳过信号数**：`path_a_candidate` 返回 `status="lots0"` 的 (品种, 日) 个数（同一信号连续几天按天计）。
- **抬手笔数**：入选并被 `min_lots` 抬高的候选数（`sizing()` 抬手 + `apply_portfolio_caps` 第 6 步抬手，两者之和去重）；另报其中对应的已平仓交易数及其实际风险。
- **最高名义占用**：权益曲线 `gross_pct` 的最大值（盯市口径），并列报入场时 `caps_entry_gross_max`。
- **PSR**：Base 日收益（权益曲线）对 0 基准的 PSR。
- **DSR**：`lab.validation.dsr.deflated_sharpe_ratio(Base 日收益, n_trials=18 或 19, mean_abs_corr=0.0)`（与 BT 内验证块同约定）。**只如实报告，不作通过条件。** 各组结果 JSON 里自带的 `validation.dsr`（n_trials=11）不用于 R8 结论。
- **PBO（每组）**：CSCV，`n_groups=8`（S=8，C(8,4)=70 个组合，与现有口径相同）；矩阵 = BASE 的 `lab/research/validation/pbo_path_a_matrix.json` 中 11 个参数试验列 + 该组 Base 日收益列（同 215 个日期，T×12）。另报**全族 PBO**（11 列 + 全部 R8 组列，K = 11 + 实际跑的组数）作参考，**不作通过条件**。各组结果 JSON 自带的 `validation.pbo` 是正式矩阵的 PBO（0.729），不用于 R8 结论。
- **走步**：`lab.validation.walk_forward.walk_forward_segments(Base 日收益, n_folds=5)`（5 个等长不重叠折）；数 Sharpe > 0 的折数。

## 4. 通过标准（全部满足才算通过）

1. Base 净收益 > 0，且 > 对照组 Base（−1.721%）；Stress 净收益 > 0，且 > 对照组 Stress（−2.339%）。
2. Base 与 Stress 的最大回撤都 ≤ 10%。
3. 单笔实际风险最大值 ≤ 3% 权益（Base 成本，全部已平仓交易）。
4. 该组 PBO（S=8，K=12）≤ 0.5。
5. 走步 5 折中至少 3 折 Sharpe > 0。
6. 对满足 1–5 的组做 `scripts/audit_exit_vs_daily.py --fail-on-mismatch`：有不符 → 该组**判为未通过**（审计失败），并如实写明。
- DSR（n_trials = 18/19）只报告，不设阈值。
- 未带 `--out` 时覆盖参数必须报错退出（有测试）；任何一组运行失败按失败如实报告，不静默重跑换结果（环境性失败可重跑，需在 progress.md 记录）。

## 5. 报告格式（回复磊）

一张表：组名 / 本金 / 名义帽 / min_lots / 净收益 Base / 净收益 Stress / 最大回撤 / 笔数 / 跳过信号 / 抬手笔数 / 单笔最大风险 / 最高名义占用 / PSR / DSR / PBO / 走步正折数 / 是否通过。
另附：对照组、全族 PBO、审计结果、C0 自检、数据一致性（bars sha）。不含改正式口径的建议。
