# R7a 签字报告：v14 候选正式重跑（待磊签字 → R7b）

- 候选：`archive/R7/candidate_bt.json`（`historical_backtest.py --fill next_open --out …`，2026-11-24 19:25 起跑，数据到 2026-11-24）
- 代码：`198642a` + 本次 R7a 工作区改动（只改 schema、n_trials、日报打印、测试改名；引擎未动，结果里 `git_commit` 戳仍为 198642a）。R7a 提交后，R7b 在干净工作树上正式重跑
- 输入快照：`archive/snapshots/bt_input_20261124_6574c6a4dbcd.json`（15.7 MB，内嵌 611 个合约日线 `contract_bars`，sha256 `6574c6a4…`）
- 本报告没有写根目录的 formal latest、paper_book、README 或 validation latest（9 个受保护文件前后哈希相同，见 `root_hashes_before_step5.txt`）

## 1. 候选 KPI（Base / Stress）

| 指标 | Base（1 跳 · 手续费×1） | Stress（2 跳 · 手续费×1.25） |
|---|---|---|
| 净收益 | **−1.068%** | −1.674% |
| 毛收益 | 1.575% | 2.663% |
| 净最大回撤 | **7.623%** | 7.032% |
| 毛最大回撤 | 6.841% | 5.842% |
| 成本（元） | 5,286.24 | 8,675.31 |
| 平仓笔数 | 56 | 56 |
| 胜率 | 33.93% | 33.93% |
| 期望（R） | 0.030 | 0.030 |
| 平均持有（交易日） | 2.45（中位 2） | 2.45（中位 2） |
| 当日平仓 | 12 笔（21.4%） | 12 笔（21.4%） |
| proxy 入场 | 25 笔（44.6%）；合约 31 笔 | 25 笔（44.6%） |
| 出场 | 止盈 18 / 止损 34 / 信号 4 | 18 / 34 / 4 |
| 跳空止损（成交价劣于止损价） | 2：EG 08-26 −1.15R，MA 09-23 −1.05R | 同左 |
| 15m 分钟线止损 | 5 | 5 |
| 换月开盘跳空止损 / roll_shifted | 0 / 0 | 0 / 0 |
| 组合帽：入场日数 / 名义最大 / 风险最大 | 49 / 49.83% / 2.33% | 49 / 49.13% / 2.33% |
| 组合帽：缩手 / 补手手数 / 补回候选 / 漂移>55% 天数 | 64 / 114 / 29 / 0 | 64 / 112 / 28 / 0 |
| 单笔实际风险中位数（\|入场−止损\|×手数×乘数 ÷ 入场前权益） | 0.555% | 0.557% |
| 期末权益 | 197,863.04 | 196,651.12 |

- 两档成本下的 Stress 数字都已核对：用候选快照和合约包离线重跑，与正式 JSON 里的 stress 行逐项相同（`candidate_kpis.json`，`_candidate_offline.py`）。
- Stress 的毛收益比 Base 高，原因是权益路径不同导致手数不同（补手 112 对 114 手）：笔数和出场日一样，但个别笔的手数不同。这不是成本算错。
- 结论字段为「继续L1」。

## 2. 验证（Research 诊断，不单独晋级）

| 指标 | 值 |
|---|---|
| PSR（对 0） | 0.460（Sharpe −0.108，n=215，偏度 0.02，超额峰度 2.44） |
| DSR | **0.043**（n_trials=11，基准年化 SR 1.76） |
| n_trials 构成 | 已归档参数+当前 = 5；PBO 矩阵试验数 = 11（`pbo_path_a_latest.json`）；`archive/shadow_strategy_*.json` 行数 = 8（`shadow_strategy_opt_t1_20261111.json`）；取最大值 **11**（R0 时按 5） |
| PBO | 0.386（11 个试验，208 个观测，8 组，70 种组合） |
| Walk-forward 5 折 | 各折 Sharpe：2.121 / 0.123 / 0.896 / 0.040 / **−3.229**；正 Sharpe 折占比 0.8（最后一折约为 2026-09 之后，明显为负） |

PBO 读的是现有的矩阵文件 `pbo_path_a_latest.json`（R 轨修复前的引擎），没有用 v14 重算。R7b 的 `run_formal_scorecard.py` 会重跑 PBO。

## 3. 三方对比

| | 旧正式（根目录，v13） | 冻结快照重放（R5b / R7a-D 引擎） | **候选（v14）** |
|---|---|---|---|
| 代码 | 0e83162 | 7cb7b20 / 6493f4e | 198642a + R7a |
| 数据窗口 | 2025-12-30→2026-11-20 | 2025-12-31→2026-11-23（11-23 快照） | 2025-12-31→2026-11-24 |
| 净收益 | +5.777% | −0.769% | **−1.068%** |
| 毛收益 | 8.344% | 1.875% | 1.575% |
| 最大回撤 | 6.739% | 7.469% | **7.623%** |
| 成本 | 5,134.02 | 5,287.84 | 5,286.24 |
| 笔数 | 66 | 56 | 56 |
| 胜率 / 期望 | 43.94% / 0.245R | 33.93% / 0.030R | 33.93% / 0.030R |
| 出场 止盈/止损/信号 | 26 / 37 / 3 | 18 / 34 / 4 | 18 / 34 / 4 |
| proxy 入场占比 | 60.6% | 58.9% | 44.6% |

**差异来源**（净收益 +5.777 → −1.068，共 −6.85 个百分点）：

1. **新数据，旧引擎**：旧正式 → R0 重跑。同一套 R0 前代码，数据刷新到 11-23，窗口从 12-30→11-20 移到 12-31→11-23。结果 +5.777 → +7.253（+1.48pp，66 → 65 笔）。
2. **引擎修复，同一份冻结数据**：R0 → R5b 重放。+7.253 → −0.769（**−8.02pp**）。各刀见第 4 节；最大的一刀是 R4 组合帽计入已有持仓（R6c 12.744 → R4 −1.053），去掉了名义占用最高到 113% 的超限持仓。
3. **新数据加 D 的预取，同一引擎**：冻结重放 → 候选。−0.769 → −1.068（−0.30pp）。
   - 两者的 56 笔交易完全对应（品种、入场日、出场日、方向、手数、出场原因都相同）。
   - 其中 8 笔从连续合约代理成交（continuous_proxy）改为真实合约成交：CF 05-11、I 11-19、SA 07-15、SA 07-17、TA 01-12、V 03-13、V 03-17、V 06-11。原因是 D 的预取补齐了之前本地缺失的合约日线。成交价相差一个基差，R 值不变。
   - 截至 11-23，权益为 198,463.04，冻结重放为 198,461.44，只差 +1.60 元（来自按价格计的手续费）。
   - 多出的 11-24 一个交易日，P 空 1 手按 8311 盯市，亏 −600 元，收益从 −0.768% 降到 −1.068%；最大回撤 7.469 → 7.623 也来自这一天。

## 4. R0 → R7 累计（冻结快照重放，R7 行为候选）

| 刀 | 净收益 | 回撤 | 笔数 | 要点 |
|---|---|---|---|---|
| 旧正式 v13 | +5.777 | 6.739 | 66 | 窗口到 11-20 |
| R0 基线 | 7.253 | 6.739 | 65 | 冻结 11-23 快照 |
| R1 假止损 | 12.674 | 4.044 | 63 | 分钟线必须与日线一致 |
| R2 夜盘归属 | 13.414 | 4.044 | 64 | |
| R3 跳空止损按开盘成交 | 10.026 | 6.904 | 65 | |
| R6a/b（已被取代） | 12.449 | 4.640 | 64 | |
| R6b-fix 真实主力换月 | 12.244 | 5.923 | 66 | |
| R6c 信号和 ATR 不受换月影响 | 12.744 | 4.124 | 64 | |
| R4 组合帽计入持仓 | −1.053 | 4.552 | 56 | 去掉超限持仓 |
| R4b 缩手后补手 | −0.769 | 7.469 | 56 | |
| R5a 日报同口径 | −0.769 | 7.469 | 56 | 逐位相同 |
| R5b 账本共用引擎 | −0.769 | 7.469 | 56 | 逐位相同 |
| R7a-D 上市日历与合约包 | −0.769 | 7.469 | 56 | 逐位相同（空缓存也一样） |
| **R7a 候选 v14（数据到 11-24）** | **−1.068** | **7.623** | **56** | 新增 11-24 一天 + 8 笔改为合约成交 |

## 5. D 的影响

- **main_map 新旧算法对比**：在候选快照和预取后的完整缓存（615 个文件）上，旧算法（a238a3d）和新算法（上市日历候选）的逐日结果为 **0/7452 天不同**（`main_map_compare_candidate.json`）。两边都有 27 个 None，全部在 2026-11-24：跑的时候（19:25）新浪还没发布 11-24 的合约日线。用合约包和用缓存算出的 main_map 也是 0 天不同。D1 在 11-23 快照上的结果是 0/7425。
- **预取统计**（`contract_prefetch`）：
  - 窗口内上市日历候选合约 619 个，其中 247 个已在缓存且无需更新。
  - 请求 372 次，耗时 8.1 秒；成功 364 个，失败 8 个，都返回空数据：EG2711、EB2711、JD2711 交易所还没挂牌；AU2703/05/07/09/11 是 AU 尚未挂牌的单月。这些合约没有日线，所以不会成为候选，不影响 main_map。
  - 缓存从 353 个文件增加到 615 个。
- **快照合约包**：内嵌 611 个合约，snapshot 15.7 MB。把 `.cache/contracts` 改名移走后，replay 只用快照和合约包，与候选在 115 个字段中的 113 个上逐项相同。剩下两个字段：`curve_coverage` 只有来源标签不同（每个品种的 `carry_days` 都相同）；`ifind_slot` 是环境字段。用同一份快照离线重跑 Base 也逐项相同，结果、账本和 Stress 都在空缓存下生成。
- **候选是否受 D 影响**：
  - main_map：**不受影响**，新旧算法在同一份缓存上结果相同。
  - 合约成交：**受影响**。预取让候选拿到更全的合约日线，8 笔交易从 continuous_proxy 改为合约成交，proxy 入场占比从 58.9% 降到 44.6%，合约入场从 23 笔增到 31 笔。出场日、原因和 R 值都没变，对盈亏的影响是 +1.60 元。
  - 可复现性：正式结果不再依赖跑的那台机器缓存里碰巧有哪些合约，这正是 D 的目的。

## 6. 产物核验

- **出场审计**（`audit_candidate.json`，`--fail-on-mismatch`）：检查 52 笔，**不符 0**；`gap_through_target_conservative` = 1，单独计数（开盘已越过止盈价，引擎按止盈价保守成交）；另检查了 56 笔入场顺序、25 笔连续口径出场区间、1 笔换月日出场。
- **空缓存 replay**：结果见第 5 节。replay 结束后缓存已改回原名，共 615 个文件（≥353）。
- **方案 B 账本**（`paper_book_candidate.json`，取候选回测最后一天的状态）：
  - asof 2026-11-24，盯市权益 197,863.04，已实现 198,193.04。
  - 持仓：P 空 1 手，11-23 开盘 8278 入场，止损 8438.29，止盈 7957.43，盯市 8311；continuous_proxy，成交合约 P2612，持有合约 P2701。
  - pending 为空（回测 11-24 没有选中新单）。
  - 根目录旧账本已原样复制到 `paper_book_legacy_pre_R7.json`。
- **日报 dry-run**（`l1_report_dryrun.json`，`--paper-book archive/R7/paper_book_candidate.json --paper-out archive/R7/paper_book_candidate_dryrun.json`）：
  - selected = [] = 账本 pending []。账本 asof 已是当天，所以是 no-op，dry-run 输出的账本与种子相同。
  - 质量检查通过（27/27）；日报合约补拉 147 次请求，成功 145 个，失败 AU2703、AU2705（空数据）。
  - 根目录 9 个受保护文件哈希不变。
  - **发现并修复一个 bug**：第一次 dry-run 报 `KeyError: 'days_rolled'`（`l1_report_dryrun_crash1.err`）。当天刚播种的账本（没有 `base`，asof 等于当天）会走 `roll_engine_book` 的 no-op 分支，返回结果里没有 roll 计数，而 `daily_update.main` 的打印语句直接按键取值。修复：这三处改用 `.get`，打印里加 `noop=`。R7b 写入方案 B 账本后，当天的日报和 CI 同日重跑都会走这条路径。

## 7. 已知局限

1. 席位历史短：V/EG/M/EB/PP/L/JD/P/I/JM 只有约 115 天席位数据，其余品种 276 天；seats 过滤在窗口前半段的样本更少。
2. 本地 15m 分钟线最早到 2026-07-30，多数品种从 2026-09-11 才有。窗口前约 8 个月的出场只能按日线高低价兜底（`daily_exit_fallback_checks` = 173，15m 止损只有 5 笔）。
3. `roll_shifted` 在真实数据上从未触发过（= 0），continuous_proxy 持仓跨换月平移的逻辑只有合成测试覆盖。
4. lab_edge 依赖当天实验室面板，回测里没有，只在日报里起作用。
5. 只有 1 年样本（215 个日收益，56 笔交易）。PSR 0.46、DSR 0.04、最后一折 Sharpe −3.2，**不能证明有正期望**；结论只是「继续 L1 积样」。
6. 晚间跑的最后一天：19:25 时新浪还没发布当天的合约日线，导致 11-24 全部 27 个品种 main_map 为 None。回测和日报在这一天都用原始连续价算信号（`adj_fallback_days_in_window` = 27，日报 adj_fallback 也是 27 个），成交和盯市用连续价代理。建议 R7b 在次日合约日线发布后再跑正式，或者接受最后一天这样退回。
7. PBO 矩阵没有用 v14 重算（见第 2 节）。

## 8. R7b 要写的文件，以及 formal_rule_lock 的更新内容

R7b（签字后、在干净工作树上）要写：

| 文件 | 内容 |
|---|---|
| `historical_backtest_latest.json` | `historical_backtest.py --fill next_open`（正式路径，带规则锁和干净树检查），schema v14 |
| `archive/backtest_*.json`、`historical_equity_curve.svg`、`archive/snapshots/bt_input_<end>_*.json` | 正式运行附带的产物 |
| `paper_book_latest.json` | 方案 B：用正式运行最后一天的状态播种 R5b 账本（与 `paper_book_candidate.json` 同法）；旧账本已归档 |
| `README.md` | 第 29 行那段 KPI 文字换成 `<!-- KPI:BEGIN -->…<!-- KPI:END -->` 标记块，然后执行 `python scripts/render_readme_kpi.py --readme README.md` |
| `lab/research/validation/formal_scorecard_latest.json`、`pbo_path_a_latest.json`（以及 `shadow_attribution_latest.json`，若需刷新） | `lab/scripts/run_formal_scorecard.py`；`code_schema` 现在直接取自结果的 `schema_version` |
| `configs/formal_rule_lock.json` | 见下 |
| `tests/test_proxy_positions.py` | 第 9 节的最小修改。**必须与根账本替换同一次提交**，否则全量 pytest 会失败 |
| `docs/UPGRADE_ITERATIONS.md` | R7b 反馈 |

`configs/formal_rule_lock.json` 的建议内容。`execution_rules.json` 没有改，所以 sha 不变；`rule_lock.py` 只读 `execution_rules_sha256_lf` 和 `fill_series`，新增的键只作记录：

```json
{
  "note": "R7 v14 formal rule lock (execfix); change only with 磊 sign-off",
  "execution_rules_sha256_lf": "77999d44e490912762ee5d2ed035e2316963a52783805b3208a2748d87d8039c",
  "fill_series": "mixed",
  "stop_atr_mult": 0.8,
  "reward_rr": 2.0,
  "schema_version": "cta-backtest-v14-execfix",
  "signed_off": "R7b <日期> 磊",
  "formal_backtest": {"git_commit": "<R7b HEAD>", "end": "<窗口末>", "input_snapshot_sha256": "<…>"}
}
```

## 9. test_proxy_positions 方案（只写方案，不改代码）

- **它原本防什么**：`test_repo_proxy_artifacts_have_own_holdings_and_paper_book_untouched`（PR #21，9fe59b6）。PR #21 给桌面三个代理策略（`PROXY_IDS` = `proxy_cwft`、`proxy_long_short_cwft`、`proxy_frontnext_st`）各自生成模拟持仓。最后一行断言根目录 `paper_book_latest.json` 的 `positions`/`open_positions` 里没有 "proxy" 字样，防止这些代理袖套的持仓混进路径 A 的账本。
- **冲突**：R5b 引擎账本的持仓带 `"fill_price_basis": "continuous_proxy"`（价格口径，与代理袖套无关）。R7b 一写入方案 B 账本，这条断言就会误报。
- **最小修改**：只改最后一行，从查子串 "proxy" 改成查代理袖套的 ID：

```python
blob = json.dumps({k: book.get(k) for k in ("positions", "open_positions")}, ensure_ascii=False)
assert not any(pid in blob for pid in PROXY_IDS)
```

  防护意图不变（代理袖套的 ID 或来源不能出现在路径 A 账本），只是不再把价格口径字段当成代理袖套。`PROXY_IDS` 在该测试文件里已经导入。

## 10. push 注意事项（本次不 push）

- 本地 `main` 比上次 fetch 到的 `origin/main`（d108a27，11-23 21:42）多 19 个提交（从 6672007 起，含 f476d65）；R7a 提交后是 20 个。远端在这期间大概率又有 CI 自动提交：`daily.yml` 每天提交 `paper_book_latest.json`、`l1_report*.json`、`archive/*.json`、`data/…`、`lab/research/…`；`historical_backtest.yml` 提交 `historical_backtest_latest.json`、`historical_equity_curve.svg`、`archive/*.json`、`universe.json`。
- 建议顺序：
  1. `git fetch origin`，查看 `git log HEAD..origin/main`。
  2. `git rebase origin/main`，不用 merge，保持 R0–R7a 的线性历史。
  3. 冲突处理：
     - **运行产物取 CI 一方**：根目录的 `*_latest.json`、`paper_book_latest.json`、`l1_report*.json`、`archive/*.json`、`data/…`、`lab/research/…/latest*`、`.cache/…`。注意 rebase 时 `--ours` 才是 upstream，即 CI 那一方。
     - **代码、测试、`docs/`、`archive/R*/`、`archive/snapshots/` 取本地**。
     - `universe.json` 若 CI 改过，逐行核对（本地 R 轨没有改过它）。
  4. rebase 后重跑全量 pytest。
  5. push 前暂停 `daily.yml` / `historical_backtest.yml` 的定时运行，或者选在两次 CI 之间，避免 push 后立刻被 CI 自动提交覆盖 R7b 的根文件。
  6. push R7a；R7b（根文件替换）作为单独一次提交，紧接着跑、紧接着 push。
- 根目录 `paper_book_latest.json` 在 R7b 之前仍是旧格式，CI 日报会继续走旧的 refresh 路径，这是预期行为。

## 11. 本次 R7a 文件

- 代码：
  - `historical_backtest.py`：`SCHEMA_VERSION = "cta-backtest-v14-execfix"`；`n_trials_census`；结果里加 `n_trials_breakdown`。
  - `lab/validation/report.py`：验证包里带上 `n_trials_breakdown`。
  - `lab/scripts/run_formal_scorecard.py`：`code_schema` 取自结果。
  - `daily_update.py`：no-op 打印修复。
  - `scripts/render_readme_kpi.py`：新增。
- 测试：
  - `tests/test_freeze_fix_gates.py` 改名为 `test_legacy_path_kpi_lock_and_fix_has_no_cross_delivery`，注释同步，断言不变。
  - `tests/test_formal_write_dirty_exit2.py`：自 R7a-D 起，`main()` 在 simulate 之前先拉行情包并预取合约，这个测试的驱动脚本只替换了 `_simulate_cfg`，于是会真实联网（每次跑几分钟）。现在把 `hb._fetch_pack`（换成快照 pack）和 `ensure_listed_contract_bars` 也换掉，恢复文件说明里写的离线行为，耗时 13 秒，断言不变。
- 产物：`archive/R7/` 下的候选结果、日志、审计、replay、账本、dry-run、KPI 预览和本报告，以及 `archive/snapshots/bt_input_20261124_6574c6a4dbcd.json`。
