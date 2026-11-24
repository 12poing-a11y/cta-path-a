# R5a · Step 0 — daily_update 信号链 vs simulate 候选构造（逐项）

读码对象：`daily_update.py`（R5a 之前的 `_fetch_snapshot` / `_signal` / main 里 seats、carry、lab_edge、observe min_lots、`_apply_caps`）与 `historical_backtest.simulate`（1cfe6fc）。
最后一列是 R5a 之后的状态；"共享"= 日报与回测调用同一段代码（`signal_core.path_a_candidate`），"保留差异"= 不能统一，原因写明。

| # | 项目 | 日报（R5a 前） | 回测 simulate | R5a 后 |
|---|---|---|---|---|
| 1 | 历史长度 | `fetch_history(n=120)`，120 根；60 日收益 + 14 日 ATR 够用，但无法做换月复权/seat 覆盖窗 | 全窗约 275 根（`LOOKBACK_DAYS=260` + 预热） | **共享**：日报 `fetch_history(n=LOOKBACK_DAYS)`，实测 275 根 |
| 2 | r20 / r60 / ATR 序列 | 原始连续价 `ret_n` / `atr14`（含换月价差，跨月假涨跌） | R6c 无价差序列：`main_map` + `AdjustedSeries.ret_n / atr14`；缺主力/合约价时按品种回退原始序列 | **共享**：`path_a_candidate` 内 `adj.ret_n/atr14`；日报先 `ensure_contract_bars` 补合约日线，再建 `main_map`/`AdjustedSeries`；缺口回退并打 `adj_fallback` |
| 3 | 动量门槛 | 候选先不过门槛：任意同向都跑 seats/carry 过滤并写 block，门槛只在 `_apply_caps` 里（weak_filtered） | 门槛（\|r20\|≥4、\|r60\|≥6、同号）在过滤之前；不过门槛不进候选、不计过滤命中 | **共享**：门槛在 core 内先判。弱信号不再带 seats/carry block 文案，仍显示未过滤的手数，由 `_apply_caps` 标 weak（选中结果不变） |
| 4 | 席位（seats）数据滞后 | 当天 bar_date 的席位簿，**不滞后** | `lag_member`：T 日只看 ≤T−1 个交易日的簿（可得性滞后 `DEFAULT_AVAILABILITY_LAG=1`） | **共享**：窗口全日期载入席位簿，`lag_member` 后再查；行为变化：日报席位现在也是前一交易日口径 |
| 5 | 席位覆盖闸 | 无 | 滞后后 as-of-T 席位日数 < `min_seat_days=60` 的品种跳过席位过滤（`seat_short`） | **共享**（`min_seat_days` 传入 core） |
| 6 | 升贴水（carry）旁路 | 当天 `curves[code]["carry"][day]`，不滞后 | `lag_curves_carry` 后查 | **共享**：同 `lag_curves_carry`，同 `carry_bypass_decision` |
| 7 | vol_bypass | 信号阶段没有 | `vol_entry_block(adj.vol_hist())`，action=observe 不拦（计数/标注） | **共享**：core 内同调用（`_vol_bypass()` 读 universe.json 同一配置）；日报写 `vol_block`（observe 下恒为空，与回测一致） |
| 8 | 止损/止盈距离 | `stop_dist = 2.0×round(ATR,2)` | `stop_dist = stop_atr_mult×ATR`（不取整） | **共享**：`sizing()`；报告 `atr` 仍展示 2 位小数，另写 `stop_dist/target_dist` 全精度 |
| 9 | 手数公式 | `floor(risk_budget/(stop_dist×mult))` | 同公式，`day_risk` 随复利权益 | **共享**：`sizing()`；日报 `risk_budget` 用日报权益，回测 `day_risk` 用回测权益（输入不同，公式相同） |
| 10 | carry 缩手与 min_lots 先后 | 先算手数，observe 袖套 min_lots 抬手，carry 缩手（floor）在后；缩到 0 再被"后抬"覆盖 | 先 carry 缩手，再 min_lots 抬手（全局，replay 配置 `min_lots=0`） | **共享**：`sizing()` 先缩后抬（回测顺序）。日报旧的"缩手后再抬"补丁只留在 `--signal-path legacy` |
| 11 | observe 袖套 min_lots | 仅 `sleeve=="observe"` 且 ATR<25%×收盘 才抬到 `OBSERVE_MIN_LOTS` | 全局 `min_lots`，无 ATR 护栏（replay 配置为 0） | **保留差异**：这是日报独有的账本规则（高保证金品种观察袖套）；`compute_signals` 把它作为参数传入 core（`min_lots` + `min_lots_guard_frac=0.25`），回测配置为 0 时两边一致；测试单独验证它只动 observe 袖套 |
| 12 | lab_edge（实验室 edge 标注/可选 block） | 有 | 无 | **保留差异（不可统一）**：依赖当日 live 实验室面板（`refresh_lab_signals`），历史上无逐日可复算的序列，回测无法调用；默认 action 只标注不改手数，设 `block` 时才影响日报 |
| 13 | 组合帽 | `_apply_caps`（R4：`held`、`existing_buckets`、top-up） | `apply_portfolio_caps` 同函数 + `_book_usage` | **共享**（R4/R4b 已统一）。余差：持仓估值，日报用报告 `close`（连续价）和 2 位 ATR，回测用持仓合约真实收盘与未取整复权 ATR；40 个测试日选中结果一致 |
| 14 | 数据源 / 品种集 | Sina→TqSdk→iFinD；27 品种 | 同上抓取后冻结快照 | 不变（相同 `fetch_history`） |
| 15 | 日期轴 | 每品种最后一根 | 覆盖 ≥max(3,n//3) 个品种的交易日 | **共享** `covered_dates`（不足 `WARMUP+5` 时回退末 `LOOKBACK_DAYS` 日） |

## 影响面（读码结论）
- r60 受换月价差影响最大：旧日报 r60 与 roll-free 的差在个别品种可到 10+ 个百分点甚至变号（MA 3.85→17.06、EG −7.75→+7.17、FU −2.63→+11.35、BU −6.57→+10.61、EB −6.24→+6.12、JD −17.16→−5.64）。
- 席位/升贴水由"当日簿"改为"前一交易日簿"，block 文案与旧日报会有出入。
- 报告 schema 只增字段（`stop_dist`、`target_dist`、`adj_fallback`、`adj_note`、`signal_path`、`core_status`、顶层 `contract_cache` / `adj_fallback_codes`），旧字段名与含义不变。
