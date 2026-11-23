# Cursor 执行指令：R0 冻结基线 + R1 修复假止损

> **用法**：一次只粘贴一段给 Cursor。R0 做完、你看过反馈以后，再粘贴 R1。
> **授权**：粘贴 R1 就算你明示开 R1（🔒 刀）。R1 只改代码和重放结果，不写正式 KPI；正式重跑和签字在 R7。
> **依据**：`docs/UPGRADE_R_TRACK.md` 的 R0、R1 两节（2026-11-23 修订版）。

---

## 指令 1：R0 冻结基线

```text
【开刀 R0：冻结基线】（轨 R · 审计升级 · 非 🔒）

先读：
- docs/UPGRADE_ITERATIONS.md §1.0
- docs/UPGRADE_R_TRACK.md 的 R0、R1 两节

背景：
后面每一刀都要和同一个起点比较，而且要用同一份输入快照离线重放，不能受新抓数据影响。
已核实的现状：
- 正式结果 historical_backtest_latest.json 的 input_snapshot.path 是 archive/snapshots/bt_input_20261120_53d47ac78c7b.json，但这个文件本地不存在；本地 archive/snapshots/ 只有 3 份 bt_input_20261113_*.json。
- lab/shadow/replay.py 在模块顶层把快照写死成 bt_input_20261113_d246813d911a.json，并在导入时就读文件。
- 正式写入有规则锁：historical_backtest.main() 写根目录 latest 前会检查 rule lock 和干净工作区（research/execution/rule_lock.py）；archive/ 不计入 dirty 检查。

范围：
- 可以改：lab/shadow/replay.py；historical_backtest.py 的 main()（只允许加 --out 参数，见步骤 3B，不许动 simulate 及其他函数）；新增 scripts/audit_exit_vs_daily.py、tests/test_audit_exit_vs_daily.py；写 archive/R0/ 下的产物；docs/UPGRADE_ITERATIONS.md 的状态和反馈
- 禁止：改 simulate / paper_book.py / minute_data.py / wyckoff_pullback.py / position_rules.py / execution_rules.json / universe.json / configs/formal_rule_lock.json / .gitignore；写根目录的 historical_backtest_latest.json 或 paper_book_latest.json；git push

步骤：
1. 运行 git status。预期只有这些改动：
   新增 docs/UPGRADE_R_TRACK.md、docs/UPGRADE_R_TRACK_equity.png、docs/CARRY_SLEEVE_R14.md、docs/STRATEGY_EVIDENCE_REVIEW.md、docs/CURSOR_PROMPTS_R0_R1.md；修改 docs/UPGRADE_ITERATIONS.md。
   允许并存的运行产物（日报 / Desk / 研究脚本生成的缓存和结果，不提交、不还原、不清理）：
   .cache/、data/、lab/research/、archive/、external/strategies/、根目录 l1_report.json、l1_report_risk15.json。
   只有出现**代码或配置**改动（*.py、*.yml、*.toml、execution_rules.json、universe.json、configs/、requirements*.txt、.gitignore 等）才停下，把清单列给我，不要提交。
   （2026-11-24 修订：原文“出现其他改动就停下”过严，运行产物不影响 R0。）

2. 只提交这些文档（本地，不 push）：
   git add docs/UPGRADE_R_TRACK.md docs/UPGRADE_R_TRACK_equity.png docs/CARRY_SLEEVE_R14.md docs/STRATEGY_EVIDENCE_REVIEW.md docs/CURSOR_PROMPTS_R0_R1.md docs/UPGRADE_ITERATIONS.md
   git commit -m "docs: register audit track R (R0-R16), carry sleeve K0-K7, evidence review"

3. 找回基线快照：
   3A. 先试远端：
       git fetch
       git ls-tree -r --name-only origin/main -- archive/snapshots/ | Select-String 20261120
       有的话：git restore --source origin/main -- archive/snapshots/bt_input_20261120_53d47ac78c7b.json
       恢复后核对文件的 sha256 与 historical_backtest_latest.json 里 input_snapshot.sha256 一致（53d47ac7...）。
   3B. 远端也没有，才做这一步：给 historical_backtest.py 的 main() 加 --out PATH 参数：
       - 给了 --out 时：结果写到 PATH，图表写到 PATH 同目录；仍然调用 write_input_snapshot；不触发规则锁；不写 archive/backtest_*.json；
       - PATH 解析后如果等于根目录的 historical_backtest_latest.json，直接报错退出；
       - 不给 --out 时，行为与现在完全一样。
       然后运行：python historical_backtest.py --fill next_open --out archive/R0/fresh_bt.json
       以 archive/R0/fresh_bt.json 和它的 input_snapshot.path 作为后续基线。
   在反馈里写清楚走的是 3A 还是 3B。

4. 改造 lab/shadow/replay.py：
   - 去掉模块顶层的 SNAP / snap / formal 读取，改成函数 load_inputs(snap_path, bt_path)；
   - 命令行参数：
     --bt   提供 contract_pack 的结果 JSON（默认根目录 historical_backtest_latest.json；走 3B 时传 archive/R0/fresh_bt.json）
     --snap 输入快照（默认取 --bt 里的 input_snapshot.path）
     --out  把 run() 的完整结果写成 JSON（不给就只打印）
   - monkeypatch 逻辑保持不变：prepare_pack_for_execution 返回 --bt 里的 contract_pack；member/carry 用快照里已经滞后过的数据；
   - 打印字段在原有基础上加 minute_stop_exits、daily_exit_fallback_checks。

5. 新增 scripts/audit_exit_vs_daily.py：
   - 参数：--bt（默认根目录 historical_backtest_latest.json）、--snap（默认取 --bt 里的 input_snapshot.path）、--out（可选，写 JSON）、--fail-on-mismatch（有不符时退出码 1）；
   - 取日线：快照存在就用快照的 bars[code]；快照不存在时回退：连续口径读 .cache/history/{CODE}0.json，合约口径读 .cache/contracts/{fill_contract}.json；两处都取不到记 skipped_no_bar；
   - 对 closed_pnls 里 reason 为 stop 或 target 的每一笔，取 date == 平仓日的那根日线：
     · fill_price_basis == "continuous_proxy"：用 open/high/low/close；
     · fill_price_basis == "contract"：用快照 bar 时，只有 bar.contract == fill_contract 才用 contract_open/high/low/close，否则记 skipped_proxied，不算不符；用 .cache/contracts 回退时直接用该合约日线；
   - 判定（tick 取 universe.json；容差 tol = 1 跳）：
     · 多单 stop：low <= stop + tol；多单 target：high >= target − tol；
     · 空单 stop：high >= stop − tol；空单 target：low <= target + tol；
   - 输出：不符交易表（平仓日、品种、方向、手数、reason、stop、target、日线 open/high/low/close、口径、日线来源），以及 checked / mismatches / skipped_proxied / skipped_no_bar 计数。

6. 新增 tests/test_audit_exit_vs_daily.py：用人造的 2 笔交易和 2 根日线，覆盖“记为 stop 但日线没碰到止损 → 报不符”和“记为 target 且日线碰到止盈 → 不报”，不依赖真实快照和缓存。

7. 生成基线（PowerShell，在仓库根目录）：
   New-Item -ItemType Directory -Force archive\R0 | Out-Null
   Copy-Item historical_backtest_latest.json archive\R0\formal_bt.json
   Copy-Item paper_book_latest.json archive\R0\formal_paper.json
   Copy-Item weekly_backtest_latest.json archive\R0\formal_weekly.json
   python scripts/audit_exit_vs_daily.py --bt archive/R0/formal_bt.json --out archive/R0/audit_formal.json
   走 3A：
     python lab/shadow/replay.py --out archive/R0/baseline_replay.json
   走 3B：
     python lab/shadow/replay.py --bt archive/R0/fresh_bt.json --out archive/R0/baseline_replay.json
   python scripts/audit_exit_vs_daily.py --bt archive/R0/baseline_replay.json --snap <基线快照路径> --out archive/R0/audit_replay.json

8. python -m pytest tests/ -q 全绿后，提交工具改动并打 tag（本地，不 push）：
   git add lab/shadow/replay.py scripts/audit_exit_vs_daily.py tests/test_audit_exit_vs_daily.py
   （走 3B 时再加 historical_backtest.py）
   git commit -m "R0: snapshot replay CLI + exit-vs-daily audit"
   git tag baseline-R0
   archive/R0/ 下的产物是否入库，按现有 .gitignore 处理，不要改 .gitignore。

验收：
- audit_formal.json：连续口径正好 3 笔不符——FU 2026-09-28（多，stop）、PP 2026-10-20（多，stop）、P 2026-11-13（空，stop）。合约口径如果也有不符，照实列出，不在 R0 处理。
- 重放复现基线：走 3A 时，baseline_replay 与 formal_bt 的 closed_trades 都是 66，ret_pct、max_dd_pct 差 ≤ 0.05 个百分点；走 3B 时，baseline_replay 与 fresh_bt 做同样比较。复现不了就把差异写进反馈，以 baseline_replay.json 作为 R1 的比较基线，不在 R0 修。
- audit_replay.json 的不符笔数照实报告（走 3A 时应同样是那 3 笔）。
- git tag 里有 baseline-R0；git diff -- historical_backtest_latest.json paper_book_latest.json 为空。

完成后：
- docs/UPGRADE_ITERATIONS.md §2「R0–R7（阶段 A）」行的开放列改为：R0 完成 · 下一刀候选 R1（待明示）；
- §7 顶部追加反馈（3–6 行）：做了什么 / 产物 / 验证 / 风险与未做 / 建议下一刀或停；
- 然后停，不要自动开 R1。
```

---

## 指令 2：R1 修复分钟线合约错配导致的假止损

```text
【开刀 R1：修复分钟线合约错配导致的假止损】（轨 R · 🔒 · 磊已明示开刀）

先读：
- docs/UPGRADE_R_TRACK.md 的 R1 节（2026-11-23 修订版：改用“同口径日线校验”；不再“只读 CODE0 分钟线”；不收紧 aligned_with_entry）
- R0 的反馈和 archive/R0/ 下的基线产物（记下基线快照路径，下面记作 <SNAP>，对应结果 JSON 记作 <BT>）

问题：
本地 .cache/akshare/minute/ 下的 15 分钟线全是月份合约（例如 FU2701_15_sina.json），没有任何 {CODE}0_15 文件。simulate 对 continuous_proxy 仓位用这些分钟线判止损止盈；当这个月份合约不是当天的主连时，价差可达 10%，就会出假止损。
例：FU 2026-09-23 多单，入场 4120、止损 3951.8、止盈 4456.5。2026-09-28 主连日线低 4293 / 高 4463 / 收 4418（没碰止损，碰到了止盈），但 FU2701 当天 09:15 最低 3916，于是被记成止损 −1R。minute_bars_aligned_with_entry 的 5% 容差没挡住（FU2701 分钟中位价约 3995，和 4120 只差 3.0%）。

修复规则（已用本地 8 个品种、361 个交易日实测：当天就是主连的月份合约 100% 通过，不是主连的 100% 被拒）：
(a) 分钟线最高、最低价落在同口径日线 [low, high] ± 2 跳内；
(b) 15:00 及以前最后一根分钟线的收盘价与日线收盘价相差 ≤ 2 跳。
两条都要满足。

范围：
- 可以改：minute_data.py（只新增函数）、wyckoff_pullback.py（只新增函数）、historical_backtest.py 的 simulate 持仓管理段和结果字段、paper_book.py 的 _intraday_stop_exit（以及新增的小 helper）；新增 tests/test_minute_daily_match.py；写 archive/R1/ 下的产物；docs/UPGRADE_ITERATIONS.md 的状态和反馈
- 禁止：改 load_minute_bars_on_date / load_minute_bars_series 的默认行为（图表板也在用）；改 minute_bars_aligned_with_entry 的阈值；改 execution_rules.json / universe.json / configs/formal_rule_lock.json；改 scripts/shadow_pullback_abc.py；写根目录的 historical_backtest_latest.json 或 paper_book_latest.json；git push

步骤：
1. minute_data.py 新增：

   def day_session_bars(bars):
       """去掉 >=20:00 的夜盘 K 线：它们属于下一个交易日（完整的交易日归属在 R2 处理）。
       只有日期、没有时间的 bar 原样保留。"""
       out = []
       for b in bars or []:
           hm = str(b.get("datetime") or "")[11:16]
           if hm and hm >= "20:00":
               continue
           out.append(b)
       return out

2. wyckoff_pullback.py 在 minute_bars_aligned_with_entry 后面新增：

   def minute_bars_match_daily(minute_bars, day_bar, *, tick, tol_ticks=2) -> bool:
       """分钟线必须和同口径日线是同一个合约：
       (a) 分钟线高低点落在日线 [low, high] ± tol 内；
       (b) 15:00 及以前最后一根分钟线的收盘价与日线收盘价相差 <= tol。
       两条都要：实测有月份合约的包络碰巧落在主连区间内、但收盘对不上的情况。"""
       if not minute_bars or not day_bar:
           return False
       try:
           tol = float(tol_ticks) * float(tick or 0)
           hi = max(float(b["high"]) for b in minute_bars)
           lo = min(float(b["low"]) for b in minute_bars)
           if hi > float(day_bar["high"]) + tol or lo < float(day_bar["low"]) - tol:
               return False
           day = [b for b in minute_bars if str(b.get("datetime") or "")[11:16] <= "15:00"]
           if not day:
               return False
           last = max(day, key=lambda b: str(b.get("datetime") or ""))
           return abs(float(last["close"]) - float(day_bar["close"])) <= tol
       except (KeyError, TypeError, ValueError):
           return False

3. historical_backtest.simulate 持仓管理段（load_minute_bars_on_date 调用处，约 1336–1360 行）：
   - 在入场日 cutoff 过滤之后、minute_bars_aligned_with_entry 检查之前，加：
       m_bars = day_session_bars(m_bars)
       if m_bars and not minute_bars_match_daily(
           m_bars, mbar, tick=float(series[code]["meta"].get("tick") or 0)
       ):
           minute_rejected_mismatch += 1
           m_bars = []
   - 这里的 mbar 就是 continuous_proxy 口径的日线（这段只在 fill_basis != "contract" 时执行），不要换成别的 bar；
   - 在 simulate 里和 minute_exit_n 一起初始化 minute_rejected_mismatch = 0，并在返回结果里加 "minute_rejected_mismatch" 字段，和 minute_stop_exits 放在一起；
   - day_session_bars 跟 load_minute_bars_on_date 放在同一个 try 里导入；minute_bars_match_daily 加到文件顶部现有的 wyckoff_pullback 导入里。

4. paper_book._intraday_stop_exit：
   - 拿到 bars 后先 bars = day_session_bars(bars)；
   - 新增 helper _local_daily_bar(root, code, asof_iso)：读 .cache/history/{CODE}0.json（list[dict]，含 date/open/high/low/close），返回 date == asof_iso 的那根；读不到返回 None；
   - tick 从 universe.json 的 symbols 里取（仿照现有 _mult_map 写一个 _tick_map）；
   - 日线为 None，或者 minute_bars_match_daily 不通过 → return None, None（日线兜底平仓在 R5 做，本刀不做）；
   - 保留现有的 minute_bars_aligned_with_entry 检查；
   - 核实并在反馈里写明：daily.yml / daily_update.py 里，.cache/history/{CODE}0.json 是不是在 refresh_paper_book 之前就已经更新到当天（它由 market_data.save_chart_history 写入，historical_backtest.fetch_history 会调用它）。如果不是，只报告，不改流程。

5. 新增 tests/test_minute_daily_match.py，至少包括：
   - test_fu2701_rejected_against_fu0：
     日线 {"open": 4363.0, "high": 4463.0, "low": 4293.0, "close": 4418.0}，tick=1；
     分钟线 [{"datetime": "2026-09-28 09:15:00", "open": 3990.0, "high": 3994.0, "low": 3916.0, "close": 3951.0},
             {"datetime": "2026-09-28 15:00:00", "open": 3997.0, "high": 3999.0, "low": 3967.0, "close": 3972.0}]
     → False
   - test_dominant_month_contract_accepted：分钟线高低点在日线范围内、15:00 收盘等于日线收盘 → True
   - test_close_mismatch_rejected：高低点在日线范围内，但 15:00 收盘与日线收盘差 3 跳 → False
   - test_day_session_bars_drops_night：21:15 那根被去掉，14:45 那根保留，只有日期没有时间的 bar 保留
   - test_old_path_would_false_stop：apply_stop_target_intraday("多", 4120.0, 3951.77, 4456.46, 上面的 FU2701 分钟线)[0] == "stop"（记录旧 bug；修复后 simulate 不会再走到这条路径）
   现有 tests/test_intraday_exits.py 不改，必须继续通过。

6. 验证（PowerShell，在仓库根目录）：
   python -m pytest tests/ -q
   New-Item -ItemType Directory -Force archive\R1 | Out-Null
   python lab/shadow/replay.py --bt <BT> --snap <SNAP> --out archive/R1/replay_after_R1.json
   python scripts/audit_exit_vs_daily.py --bt archive/R1/replay_after_R1.json --snap <SNAP> --out archive/R1/audit_after_R1.json --fail-on-mismatch

7. 产出对比表 archive/R1/R0_vs_R1.json，并在反馈里贴出 R0 / R1 两列：
   ret_pct、gross_ret_pct、max_dd_pct、closed_trades、exits（stop/target/signal）、minute_stop_exits、minute_rejected_mismatch、daily_exit_fallback_checks；
   另外单独列出 FU 2026-09-23 入场那笔在 R1 下的出场日、原因和 R 值。

8. 测试和审计都通过后，本地提交（不 push）：
   git add minute_data.py wyckoff_pullback.py historical_backtest.py paper_book.py tests/test_minute_daily_match.py
   git commit -m "R1: reject minute bars that do not match same-basis daily bar (false stops)"

验收：
- pytest 全绿；
- audit_after_R1.json 的不符笔数为 0；
- FU 2026-09-23 那笔不再在 2026-09-28 记为止损；
- minute_rejected_mismatch > 0，minute_stop_exits 比 R0 少；
- git diff -- historical_backtest_latest.json paper_book_latest.json 为空。

注意：
- 一笔平仓结果变了，后面的持仓和交易都会跟着变（路径依赖），所以不要求其余交易和 R0 一样，只要求审计 0 不符；
- 总收益可能上升，也可能下降，照实报告。不许为了数字回退修复，也不许顺手调参数；
- 模拟账本里 P、I 两笔已经越过止盈/止损的持仓，本刀不处理（R5）。

完成后：
- docs/UPGRADE_ITERATIONS.md §2「R0–R7（阶段 A）」行的开放列改为：R1 完成 · 下一刀候选 R2（待明示）；
- §7 顶部追加反馈（3–6 行）；
- 然后停，不要自动开 R2。
```
