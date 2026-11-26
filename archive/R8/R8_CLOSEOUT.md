# R8 收尾（R8_CLOSEOUT）

分支 `r8-equity-filter`（本文件写于合入前）。R8 = 磊指定的研究项：先测本金（R8a），再在实际本金下过滤极端风险（R8b），随后冻结候选、样本外预注册、长样本与 30 万诊断。**纯研究，正式层不变。**

## 1. 正式层不变

- 受保护文件与 `main` 的 diff 为空：`universe.json`、`execution_rules.json`、`configs/formal_rule_lock.json`、`.github/workflows/historical_backtest.yml`（继续暂停）。
- 未写正式 `paper_book`、未做正式 BT 晋升、未写席位；未启动 shadow。
- 代码改动全部默认关闭：`--equity` / `--filter-unit-risk` / `--filter-atr-spike` 仅带 `--out` 生效；长样本入口与官方数据路径只能由 `archive/R8/long_sample.py` 显式调用（`_simulate_cfg(long_sample=…)`，默认 `None`）；C 的品种池是 `long_sample` 内的可选钩子。216 天窗口在本地数据上逐位复现冻结结果（`tests/test_r8_long_sample.py`：E1000k、F2 的 `closed_pnls` 与 `equity_curve` 逐位相同，且补丁过的 `hb` 全局被还原）。
- 正式层数据源不切换，继续用现有本地数据。

## 2. 216 天窗口的结论（R8a / R8b，`results_table.md`、`PREREG.md`、`PREREG_ERRATUM.md`）

- **R8a（本金网格，诊断用）**：Base/Stress：E100k −2.16/−3.46、E300k +8.75/+1.60、E500k +3.22/+2.14、**E1000k（实际本金）+4.97/+3.48**；不随本金单调；E1000k 的 PBO 0.857、走步 3/5、DSR(18) 0.098。
- **R8b（实际本金 100 万下的极端风险过滤）**：F1（名义）/ F2（ATR 突增）/ F1F2 **均未通过预注册标准**。F2、F1F2 满足第 1–5 条（Base +10.94/+11.00、Stress +9.03/+9.43、回撤 ≈3.1%、PBO 0.386、走步 5/5），第 6 条不满足（被过滤交易前半年 −6.5k 元、后半年 +3.1k 元）；DSR(18) 0.34。F1 只碰 CU/AG/AU，对结果几乎无影响。
- 候选冻结：A = E1000k，B = A + F2（只作对照），C = A + 月度品种池（`CANDIDATE_LOCK.md`，tag `r8-cand-freeze`）；**C 从未在 216 天窗口上运行**。

## 3. 长样本结论（`OOS_VERDICT.md`）

- 2016-01-04 → 2025-12-31，官方逐合约数据 + 5% 成交量守卫，基础模式，9 组（A/B/C × 80/100/120 万）× Base/Stress，一次跑完，重放一致性通过。
- **A、B、C 都没有通过 §7；B 不优于 A，C 不优于 A。** 100 万档 Base/Stress 收益：A −20.4/−26.7、B −30.2/−45.0、C −16.8/−52.0；最大回撤 Base 40–48%、Stress 43–59%（标准 ≤10%）；走步正折 A 4/10、B 3/10、C 0/10；DSR(30) ≤ 0.007（只报告）。
- C 的三档 Stress 极差（10.9pp）小于 A（25.6pp），但 C 本身不通过，100 万档比 A 低约 25pp。B 的被过滤交易为负的年份 6/10（需 ≥7）。降级规则未触发。
- 说明：这是**基础模式**的长窗口，不含席位 / 升贴水 / R6c 层；这些层只能由前向 shadow 检验（`PREREG_OOS.md` §9）。

## 4. 30 万诊断结果（`DIAG300K_REPORT.md`，只报告）

- A300k / B300k / C300k：Base 收益 −23.1 / −15.7 / −43.8 %，Stress −43.2 / −54.6 / −64.3 %；Stress 最大回撤 46 / 58 / 66 %；标签均为「**30 万不适用**」。
- C300k：池 9–18 个品种、覆盖 2–4 个板块；**有色板块（AG/AU/CU/AL/NI）全部不在池内的月数 76/117**（2019-08 起）；settle→close 兜底 0 条；总净盈亏 ≤ 0，最大单笔占比不适用。
- 标签只作背景，不触发任何调整，不计入 DSR。

## 5. 偏离与勘误索引

| 项 | 内容 | 位置 |
|---|---|---|
| 预注册（216 天）勘误 | 输入差异不止 `oi`，还有窗口末日 36 处盘后版本字段 | `PREREG_ERRATUM.md` |
| 本地数据来源更正 | 本地存储还读 `.cache/sina`（1122 个官方合约、最早 2018-01，与官方 volume/OHLC 偏差大）；"本地 bar 只有 2024-09 以后"只对 `.cache/contracts` 成立 | `APPENDIX_1.md` §2.4 |
| 9 个共同日期更正 | "≥5 个品种"的只有 7 个，9 个日期对应"≥4 个品种" | `APPENDIX_1.md` §2.4、§2.3 |
| 换月事件基线 | 1256 → 1255（多出的 1 次在晚上市品种预热期内） | `APPENDIX_1.md` §3；`MAIN_RECOMPUTE_REPORT.md` |
| 成交量守卫（对引擎主力规则的偏离） | 仅官方路径、5% 写死；未识别品种日 135 → 171，守卫新增 36 个 | `APPENDIX_1.md` §2.1、§2.2；`GUARD_SENSITIVITY_REPORT.md` |
| 135 个未识别品种日沿用前一日主力 | 字面标准在官方数据上不成立；4 段换月被推迟 | `APPENDIX_1.md` §2.2 |
| 停止条件措辞的读法澄清 | "被拦下的换月"按正常换月读；**看过数据后的澄清**，磊已确认 | `APPENDIX_1.md` §3 |
| 6 条正常换月未复现 | 3 个两跳链，到达日期不变，三档差 0 | `APPENDIX_1.md` §3 |
| 35 次同量级来回换月 | 守卫不处理；每手成本 Base 4,386 元合计 / Stress 7,433 元 | `APPENDIX_1.md` §4；`reversal_cost_35.json` |
| 预热在窗口内消耗 | 与 `PREREG_OOS.md` §2 不同；2016 折不足一年 | `APPENDIX_1.md` §2.5 |
| 成交合约取主力 | 长样本取主力开盘价，216 天用日历前月合约 | `APPENDIX_1.md` §2.6；`WINDOW_GAP_REPORT.md` |
| C 的 settle 取法与兜底数 | 兜底数预期由"4"更正为 0，实际 0 | `APPENDIX_1.md` §2.7；`OOS_VERDICT.md` §7 |
| 零成交 bar / FU 起点 | FU 起点 2018-10-16 | `APPENDIX_1.md` §2.8；`LONG_FEASIBILITY_REPORT.md` |
| 乘数证据与 CF 2022-08-03 | 官方 CF2209 当日成交额字段异常，不是乘数变更 | `APPENDIX_1.md` §5 |
| 216 天窗口缺口检查 | 22 个差异判为本地覆盖缺口；A/B 冻结交易不受影响；shadow 最新一天的结构性风险 | `WINDOW_GAP_REPORT.md` |
| 本地存储缺当日最大成交合约 | 2024-09 起 22 个快照日外差异的原因 | `GUARD_SENSITIVITY_REPORT.md` |
| 技术性事项 | DCE 批量抓取被限流（39 天空返回）→ 串行重抓补齐；浅层预运行（截断窗口，非结果）仅用于流水线/记账核对，100 万档截至 2017-06-30、30 万档截至 2017-12-31，不计 DSR、不计入任何结果 | 本文件 |
| 测试污染修复 | `lab.shadow.replay` 导入时的副作用会改 `hb` 全局，导致 `test_tradability_bt` 在全量 pytest 中失败；已在入口里先保存再导入 | `archive/R8/long_sample.py`（`run_local_216`） |
| DSR 试验数 | 30 = 18（R8）+ 3（上一轮）+ 9（本轮）；30 万诊断与各项只读检查不计入 | `PREREG_OOS.md` §5 |
| 216 天 PBO 口径 | 修复前 0.386 与 v14 0.729 不可直接比较 | `docs/UPGRADE_ITERATIONS.md` |

## 6. 后续（不在本次收尾内）

- shadow：`PREREG_SHADOW_300K.md` 已提交；启动需官方数据管道连续 5 个交易日正常（任务 4）。
- 官方数据是否替换正式层数据源：另行决定。
- 分支：`r8-equity-filter` 合入 `main` 须在合入前列出与 `r8-gross-equity` 的差异并由磊确认；`r8-gross-equity` 打 tag `r8-gross-equity-archive` 后不合入。
