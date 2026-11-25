# R8 候选冻结（CANDIDATE_LOCK）

分支 `r8-equity-filter`；冻结提交 = 加入本文件的那个提交（tag `r8-cand-freeze` 指向它）。纯研究，不动正式层。

## 0. 冻结声明

- **候选 A（E1000k）**：冻结的研究基线。
- **候选 B（A + F2）**：只作对照。
- **候选 C（A + 按资金体量过滤品种）**：新增，规则全文见 §3。
- 三者都进入样本外验证（见 `PREREG_OOS.md`）。**不采用 F1**。正式层不动。
- 冻结之后：**不在 216 天窗口（2026-01-05 → 2026-11-25）上再加组、调参；也不在这个窗口上跑 C**（连冒烟测试也不跑；C 的代码只用构造数据做单元测试）。
- 两个 R8 分支（`r8-equity-filter`、`r8-gross-equity`）都不合入 main、都不 push；`r8-gross-equity` 原样保留。

## 1. 冻结参数

共同参数（A、B、C 全部相同，除下面逐条写明的差别）：

| 项 | 值 | 来源 |
|---|---|---|
| 本金 | **1,000,000 元** | `--equity 1000000`（研究覆盖，需带 `--out`） |
| 入场过滤模式 | `entry_filter = seats`（216 天窗口内的验证配置） | `universe.json` |
| 成交 | `--fill next_open`（T 日收盘出信号，T+1 开盘成交） | `universe.json` backtest |
| risk_pct | 2.0 | `universe.json` |
| max_positions | 3 | `universe.json` |
| 名义帽（max_gross_exposure_pct） | 50 | `universe.json` |
| 组合风险帽（max_portfolio_risk_pct） | 8 | `universe.json` |
| max_per_bucket | 1 | `universe.json` |
| min_r20_pct / min_r60_pct | 4 / 6 | `universe.json` |
| min_lots | 0 | 引擎默认 |
| equity_compound | true | `universe.json` |
| carry_bypass | enabled，升贴水绝对值 ≥ 1% 时升水禁开多、贴水禁开空 | `universe.json` |
| vol_bypass | enabled，action=observe（5/20/60，短÷长≥1.6 观望） | `universe.json` |
| lab_edge_bypass | enabled，action=observe（20%） | `universe.json` |
| 滑点 | 1 个最小变动价位 / 边 | `universe.json` |
| 手续费 | 各品种 `fee_yuan` / `fee_rate`（as-of 2026-09-02） | `universe.json` |
| Base / Stress | Base = 滑点×1、手续费×1；Stress = 滑点×2、手续费×1.25 | `research_cost.json` / `research/execution/cost_model.py` |

**A**：以上参数，不加任何过滤。参考运行：`python historical_backtest.py --fill next_open --equity 1000000 --out archive/R8/E1000k/result.json`（`archive/R8/E1000k/`）。

**B = A + F2**：加 `--filter-atr-spike`。F2 参数（`research/execution/entry_filters.py`，固定、不扫）：

- 判定：`ATR14 / ATR100 > 1.5`（严格大于）时，该候选不入场；
- 用 R6c 的 roll-free 调整序列（`AdjustedSeries.atr14` / `atr_n(i, 100)`），无调整序列时用原始连续序列；
- 只读 T 日及以前的数据，T 日收盘判定、T+1 成交；
- ATR100 不可得（前面不足 100 根 bar）→ 放行（不拦）；
- 被拦的候选不进入候选列表（不占板块、不占名额）。

参考运行：`archive/R8/F2/`。

**C = A + 月度品种池**：规则全文见 §3。**C 在冻结时点没有实现**，实现要等 `PREREG_OOS.md` 提交、并且长样本数据覆盖报告被磊确认之后；实现必须逐条符合 §3 的文字，并且只用构造数据做单元测试。

### 216 天窗口内的参考数字（仅供对照，不是验收标准；A、B 为已看过结果）

| 组 | Base 净收益 | Stress 净收益 | 最大回撤 Base/Stress | 笔数 |
|---|---|---|---|---|
| A = E1000k | +4.967% | +3.479% | 5.248% / 5.599% | 99 |
| B = F2 | +10.942% | +9.032% | 3.072% / 3.215% | 82 |

B 的收益有大头来自一笔交易（FU 2026-09-24，约 +40.3k / 总增益 +58.3k）；R8 的 PBO、DSR 不支持把这两个数字当成结论（E1000k：PBO 0.857，DSR(18) 0.098，走步 3/5）。C 从未在这个窗口上跑过。

## 2. 哈希与来源

| 项 | 值 |
|---|---|
| 评估代码提交（A/B 的运行结果里记录的 `git_sha`） | `823ed8aa6aa606616e358eb45fae6623b81c5611` |
| 冻结时分支 HEAD（本文件的父提交） | `1839c7f2a2d9d5d782ed3dcf00fa23f52a270ab4` |
| `universe.json` SHA-256 | `7422CA4A79DD8FB9C9DF715373E67AEC72D124EDAEF438ABB659F89BBF0F9E05` |
| `execution_rules.json` SHA-256 | `4B4F06A632CB356BA9195542EC8D23CA83E4ED887E32B93535597322DE86C0EA` |
| `configs/formal_rule_lock.json`（规则锁）SHA-256 | `788C24C51D6FAB0511DBE449A4EFB151DE965A5A0FC48766160FBD6A60A56375` |
| `research_cost.json` SHA-256 | `B0E27F3EF6233A042B0B4AD97AC7D737CD2943A19BECD092F81FF427423461F1` |
| 数据快照（A 的输入） | `archive/snapshots/bt_input_20261125_05dade0b049c.json` |
| 数据快照 SHA-256 | `05DADE0B049C2C51875787695B10F928C9200C24F27D924A8CD5F3BA16704408` |
| `bars_sha256` | `fdc1c84d190f7e0fb2cf7c614a1435e4c041919fdc13de416d39be3f5f4b8f2c` |
| `member_sha256` / `seats_sha256` | `542575943d10f5e454b16b719ea320434655a9b6f33039d0f1c228fa11b6c3e1` |
| `carry_sha256` | `c115566afc4ac295e19949f2ccde89e1b4eef9af4bc0ee14407b54b1a03c9c73` |
| `contract_bars_sha256`（611 个合约） | `eefa9040137b165d9d105ec241dfd8348485242bd6fbb2cad6bb7e13c0a22868` |

说明：该快照是 A/B 的**输入**；快照文件随本提交一并入库，使上面的数据哈希可以复核。快照数据日期止于 2026-11-25；其中 2026-11-25 一天的非 `oi` 字段与基线快照有差异，已在 `PREREG_ERRATUM.md` 记录，不影响本冻结。

## 3. 候选 C 的规则全文

1. **母池**：母池固定为当前 `universe.json` 的 27 个品种，不增不减。
2. **月度品种池**：每个自然月的第一个交易日，用**上月末权益 E** 和**上月末结算价**，算出每个品种 1 手的名义 `N_i`（`N_i` = 上月末结算价 × 合约乘数 `mult`，`mult` 取自 `universe.json`）。当月品种池 = { i : `N_i` ≤ E × 25% }。
   - 25% 就是 F1 预注册过的"名义帽一半"（名义帽 50% × 1/2），**不引入新参数**。
   - 比较用"小于等于"（`N_i` 恰好等于 E × 25% 时，该品种在池内）。
3. **月内不变**：品种池在整个自然月内固定，月内权益或价格再怎么变都不重算。
4. **其余规则**：信号、仓位（`floor` 取整）、名义帽、持仓数、板块上限都与 A 相同。
5. **不补位**：被排除的板块不找替代品种；不从 27 个之外加品种，不放宽板块上限。
6. **按实际权益计算**：E 用账户实际权益（上月最后一个交易日收盘后的逐日盯市权益，已扣成本、含未平仓浮动盈亏），不按固定档位；回测第一个月用初始本金。

本冻结对 C 的补充澄清（均在运行前写定，不依赖任何结果）：

- **按信号日归属月份**：T 日产生的候选，用 T 日所在自然月的品种池判定（即使 T+1 成交落在下个月）。
- **已持仓不强平**：品种被排除只拦新入场；已持有的仓位照常止损、止盈、离场。
- **结算价缺失**：本规则要求"结算价"。上月末那一根 bar 没有 `settle`（空或 0）时，处理方式属于长样本数据缺口处理，由 `PREREG_OOS.md` §9 默认值和磊的确认决定（默认：该品种当月不入池，不用收盘价代替、不插补）。

## 4. 不动的部分

- 正式层、规则锁、`universe.json`、`execution_rules.json`、`configs/formal_rule_lock.json`：不改（哈希见上）。
- `historical_backtest.yml`：继续暂停。
- 正式 `paper_book`、正式 BT 晋升、席位：不写。
