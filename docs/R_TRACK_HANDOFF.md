# 轨 R 交接文档（写给新对话的 Quick 和 Cursor）

> **✅ 2026-11-24 20:13（北京时间）磊已签字**，接受 R7a 候选（v14）作为新的正式口径。R7b 定于 **2026-11-25 上午、15:30 日报 CI 之前**执行（等新浪发布 11-24 合约日线）。push 仍需另行明示。

> 更新时间：2026-11-24 20:10（北京时间）。由 AWS Quick 在 R7a 完成后整理。
> 用法：新开对话后，先让 Quick 读这份文件，再读 `archive/R7/R7_signoff_report.md`，然后继续。
> 本文件尚未提交，R7b 会把它一并提交。

---

## 0. 明早执行单（2026-11-25，给 Cursor 直接执行）

> 磊 11-24 晚已确认以下全部决定。Cursor 可以按本节从头执行到底，不需要再经过 Quick。只有遇到「停下」条件时才停，并向磊报告。
> 现状（11-24 20:34）：本地已 rebase 到 `origin/main` **19cd660**（11-24 日报 CI）；R7a 候选新哈希 **921ce7b**（旧 3847d3c 保留在 `backup/pre-rebase-R7a`）；rebase 后全量 pytest 529 项通过；未 push。
> 备份目录：`D:\AI\cta-path-a_untracked_backup_20261124\`（archive/R0–R3、本文件副本、hash_map.txt、pytest 日志）。

**通用约束**：`$env:PYTHONUTF8="1"`；长命令在后台跑、写日志，**约每 5 分钟** tail 一次，不要频繁轮询；每个子步骤更新 `archive/R7/progress.md`；`git add` 只用显式路径；不改 `execution_rules.json`、`universe.json`（`configs/formal_rule_lock.json` 只在第 8 步按报告第 8 节填写）；结果变好变差都照实报告，不调参；`git stash list` 里的 11 条不动；`lab/research/predictions/pred_20261124.json` 保留，不删也不提交；`archive/R0`–`R3` 保持未跟踪，不提交。

**S1 同步远端**
1. `git fetch origin`；`git log --oneline HEAD..origin/main`。
2. 如果远端比 19cd660 新：先做只读检查（远端新提交改了哪些文件、和本地有没有交集）。遇到下列情况就**停下**：远端改了 `*.py`、`tests/`、`docs/`、`archive/R*/`、`archive/snapshots/`、`configs/`、`execution_rules.json`、`.github/`、`universe.json`，或者有非 bot 的人工提交。都没有的话：`git restore -- .cache/`（只还原已跟踪文件），然后 `git rebase origin/main`。冲突按报告第 10 节处理：运行产物取 CI 一方（rebase 时 `--ours` 是 CI），代码、测试、docs、`archive/R*/`、`archive/snapshots/` 取本地。没把握就 `git rebase --abort` 并**停下**。rebase 后跑全量 pytest，并更新本文件里的 HEAD。
3. 远端没有新提交：跳过。

**S2 数据确认（R7b 第 0 步）**：确认新浪已发布 11-24 合约日线，即正式运行后 `main_map` 在 11-24 不能是全部品种 None。还是 None 就**停下**，过一段时间再试；15:30 之前一直不行，就**停下**报告。

**S3 移走本文件**：把 `docs/R_TRACK_HANDOFF.md` 移到 `D:\AI\cta-path-a_untracked_backup_20261124\R_TRACK_HANDOFF.staging.md`，移动前后核对哈希。然后确认 `dirty_paths(ROOT) == []`，不为空就**停下**。

**S4 执行第 5 节 R7b 指令草稿的第 1–10 步**（HEAD 以 S1 之后的为准）。
- 第 10 步提交之前：把 staging 文件移回 `docs/R_TRACK_HANDOFF.md`，在第 2 节表格加一行 R7b 正式结果（提交、净收益、回撤、笔数），把顶部状态改为「R7b 已完成，待 push」，再和 R7b 一起提交。
- pytest 改写的跟踪文件，提交前要还原。

**S5 第 11 步**：更新 `UPGRADE_ITERATIONS.md`（阶段 A 完成；§7 反馈 3–6 行）。可以并入 R7b 提交，或者单独一个 docs 提交。

**S6 停下等 push**：**不 push**。回复磊以下内容：正式 KPI（Base/Stress）、PSR/DSR/PBO、audit/replay、根账本摘要、dry-run、pytest、commit 哈希、和 v14 候选（−1.068% / 7.623%）的差异及原因。
- push 由磊明示后才执行。顺序：先 `git fetch`，如果远端有新提交就再 rebase 一次（规则同 S1）；然后 push。必须赶在 **15:30 日报 CI 之前**，或者先暂停 `daily.yml` / `historical_backtest.yml` 的定时运行。

**中途额度/时间用完**：没 push 就不影响 GitHub 上的 CI。不要手动提交半成品。下次用 `git restore` 回到 R7b 开始前的 HEAD，从 S1 重新开始。

---

## 1. 现在在哪

- 仓库：`D:\AI\cta-path-a`，分支 `main`，**HEAD = `921ce7b`**（R7a，rebase 前为 3847d3c）。本地比 `origin/main`（19cd660）多 20 个提交，**全部未 push**。
- 2026-11-24 晚已 rebase 到 origin/main 19cd660，旧 HEAD 3847d3c 保留在 backup/pre-rebase-R7a。新旧哈希对照在 `D:\AI\cta-path-a_untracked_backup_20261124\hash_map.txt`；下文表格里的提交哈希均为 rebase 前的旧哈希。
- 阶段 A（R0–R7，修回测引擎）：只差 **R7b**，需要磊签字。
- 签字依据：`archive/R7/R7_signoff_report.md`（候选正式成绩、验证指标、三方对比、R7b 写入清单、push 顺序）。
- Cursor 会话名：`@cta-r1`（agent `acp-cursor`，运行在电脑 Yl 上）。电脑离线时无法交互。

## 2. 每一刀的提交与结果（冻结 11-23 快照重放口径）

| 刀 | 提交 | 净收益 | 最大回撤 | 笔数 | 要点 |
|---|---|---|---|---|---|
| 旧正式 v13 | 0e83162 | +5.777% | 6.739% | 66 | 窗口到 11-20，引擎有错 |
| R0 冻结基线 | （tag `baseline-R0`） | 7.253% | 6.739% | 65 | 3B：远端无 11-20 快照，重新生成 |
| R1 假止损 | 09aff43 | 12.674% | 4.044% | 63 | 分钟线必须与同口径日线一致 |
| R2 夜盘归属 | ccdd3d9 | 13.414% | 4.044% | 64 | 夜盘 K 线归下一交易日 |
| R3 跳空止损 | 1c82590 | 10.026% | 6.904% | 65 | 开盘穿止损按开盘价；账本日历排除周末假 K |
| R6a/b（被取代） | b195c25 | 12.449% | 4.640% | 64 | 错误：开仓前平仓、日历合约当换月 |
| R6b-fix | 5ace2d3 | 12.244% | 5.923% | 66 | 真实主力映射 main_map |
| R6c | fcf0a1a | 12.744% | 4.124% | 64 | 信号/ATR 用 roll-free 序列；棉花止盈审计例外 |
| R4 组合帽 | aa65cb1 | −1.053% | 4.552% | 56 | 帽计入已有持仓（原来最高 113%） |
| R4b 补手 | 1cfe6fc | −0.769% | 7.469% | 56 | 缩手后补手，修取整误杀 |
| R5a 日报同口径 | 42cb2e9 | −0.769% | 7.469% | 56 | 日报和回测共用 `signal_core` |
| R5b 账本同引擎 | 7cb7b20 | −0.769% | 7.469% | 56 | `book_core`，T+1 成交，对账权益差 0 |
| R7a 准备 | f476d65 / 552eba8 / b28d3f8 / a238a3d | — | — | — | 运行产物快照、docs、冻结测试输入、daily.yml 缓存 |
| R7a-D | 6493f4e / 198642a | −0.769% | 7.469% | 56 | 上市日历候选、ContractStore、快照合约包；空缓存可复现 |
| **R7a 候选 v14** | **3847d3c** | **−1.068%** | **7.623%** | **56** | 数据到 11-24；Stress −1.674% |

候选验证指标：PSR 0.46、**DSR 0.043**（n_trials=11）、PBO 0.386（旧矩阵，R7b 重算）、走步 5 折最后一折 Sharpe −3.2。
**结论：引擎修好后，这套 Path-A 一年约打平，没有证据证明有正期望。**

## 3. 已定的决定（不要再改）

- R6 提前到 R4 之前做；R6b 按真实主力映射返工。
- 棉花 05-06 那类“开盘越过止盈、按止盈价成交”：引擎不改，审计例外放行（`gap_through_target_conservative`）。
- R4b：缩手后补手。
- 模拟账本修复用**方案 B**（按正式回测期末状态重置，旧账本归档到 `archive/R7/paper_book_legacy_pre_R7.json`）。
- 方案 D：main_map 候选按上市日历；合约数据经 ContractStore，快照自带合约包。
- R7 前：运行产物先提交成快照；冻结快照和基线进 Git；daily/weekly/historical 三个 workflow 加 `.cache/contracts` 缓存。

## 4. 待磊签字 / 决定的事（R7b）

1. ~~是否签字~~ → **已签字（2026-11-24 20:13）**，接受新的正式成绩（约 −1.07% / 7.6%，替换 README 里的 +5.0%/3.3% 旧口径）。
2. ~~R7b 运行时间~~ → **已定：2026-11-25 上午、15:30 日报 CI 之前**。开跑前先确认新浪已发布 11-24 合约日线（候选 main_map 在 11-24 应不再是 27 个 None）。
3. test_proxy 修改方案（报告第 9 节）：改为检查代理袖套 ID，不再检查 "proxy" 子串。必须和根账本替换在同一次提交。
4. push：按报告第 10 节顺序，由磊明示后执行。

## 5. R7b 指令草稿（签字后发给 Cursor）

```text
【R7b：写正式 v14 成绩 + 方案 B 账本】（磊已签字，2026-11-24）
仓库 D:\AI\cta-path-a，HEAD 应为 921ce7b（若明早又 rebase 过则以新 HEAD 为准）；$env:PYTHONUTF8="1"；长命令后台跑并写 archive/R7/progress.md。
0. 先确认新浪已发布最后一个交易日的合约日线：正式运行后 main_map 最后一天不得出现全部品种 None；若仍为 None，停下报告。
不改 execution_rules.json / universe.json；不 push（push 另行明示）。
1. dirty_paths(ROOT) 必须为 []（先还原测试改写的跟踪文件）。
2. 正式运行：python historical_backtest.py --fill next_open（走规则锁和干净树检查），写根目录 historical_backtest_latest.json 及附带产物。
3. audit --fail-on-mismatch 不符 0；把 .cache/contracts 移走做空缓存 replay，逐项与正式结果一致（只允许 curve_coverage 来源标签、ifind_slot 不同），再移回。
4. lab/scripts/run_formal_scorecard.py：重算 formal_scorecard_latest.json、pbo_path_a_latest.json（PBO 用 v14）。
5. 方案 B：用正式运行期末状态播种 R5b 引擎账本，写根目录 paper_book_latest.json。
6. 同一提交里改 tests/test_proxy_positions.py（报告第 9 节最小修改）。
7. README：把 KPI 段换成 <!-- KPI:BEGIN -->…<!-- KPI:END -->，运行 scripts/render_readme_kpi.py --readme README.md。
8. configs/formal_rule_lock.json：按报告第 8 节，填 signed_off、git_commit、end、input_snapshot_sha256。
9. daily_update --dry-run 用新根账本跑一次：selected == pending；根文件哈希不变。
10. 全量 pytest 全绿；提交 "R7b: formal v14 KPI + scheme-B paper book (signed off by 磊 2026-11-24)"，并提交 docs/R_TRACK_HANDOFF.md。
11. UPGRADE_ITERATIONS.md：阶段 A 完成；§7 反馈。然后停，等 push 明示。
回复：正式 KPI（Base/Stress）、PSR/DSR/PBO、audit/replay、根账本摘要、dry-run、pytest、commit 哈希。
```

## 6. 给 Cursor 的固定规则

- 一次一刀，做完写 §7 反馈（3–6 行）就停。
- 只用显式路径 `git add`；commit 前 `git diff --cached --name-only`；不 `git add -A`、不 `commit -a`；不 push。
- 不改 `execution_rules.json`、`universe.json`、`configs/formal_rule_lock.json`（R7b 例外），除非明示。
- 结果变好变差都照实报告，不为数字回退修复、不调参数。
- 长命令（全量 pytest、正式回测、replay、dry-run）后台运行 + 日志 + 定期 tail；每个子步骤更新 progress.md（两次断线教训）。
- pytest 会改写几个跟踪文件（`lab/research/predictions/*`、`lab/research/volatility/vol_engine_daily_latest.json`、`data/lsp/shadow/*`），提交前要还原。
- 运行前设 `$env:PYTHONUTF8 = "1"`。
- `git stash list` 里有 11 条旧条目（别的分支），不要 drop。

## 7. 已知遗留问题

- archive/R0–R3 从未提交，已备份到仓库外（`D:\AI\cta-path-a_untracked_backup_20261124\archive\`），待定；R7b 不提交它们。

- 分钟线只从 2026-09-11 左右开始，窗口前 8 个月的出场靠日线兜底。
- 席位历史短（约一半品种只有 ~115 天）。
- `roll_shifted`（连续口径持仓跨换月平移）从未在真实数据上触发，只有合成测试。
- lab_edge 只在日报里，回测里没有。
- 晚间运行时当天合约日线未发布 → 最后一天 adj_fallback。
- 三个 `scripts/shadow_*.py` 默认也会补手，旧影子结果不可直接比较。

## 8. 阶段 A 之后

- **阶段 B（降回撤，长样本闸门）**：R8 长样本入口 → R9 出场方案预注册 5 组（0.8ATR 止损太紧，平均持有 2.45 天、当日平仓 21%）→ R10 让风险预算真正生效（单笔实际风险中位 0.56%，设计 2%）→ R11 波动目标 + 回撤刹车 → R12 品种池。细则见 `docs/UPGRADE_R_TRACK.md`。
- **阶段 C（新收益来源）**：R13 席位长样本验证；R14 carry 袖套（`docs/CARRY_SLEEVE_R14.md`，K0–K7；K0–K2 可并行）。
- 依据：`docs/STRATEGY_EVIDENCE_REVIEW.md`。
- 思考强度：签字、正式重跑、逐笔核对时开「高」；日常「中」。
