# R7a progress

- HEAD at start: 7cb7b20 (confirmed)
- Step 1: commit 1 `f476d65` "chore: snapshot run artifacts before R7" — 110 files (l1_report.json, l1_report_risk15.json,
  archive/l1_report_20261123.json, data/ 37, lab/research/ 71, external/strategies/proxy_supertrend.json); no *.py / *.yml /
  *.toml / configs / execution_rules.json / universe.json / requirements / .gitignore staged.
- dirty_paths(ROOT) after commit 1 = ['docs/CURSOR_PROMPTS_R0_R1.md'] → stopped; per instruction committed alone:
  `552eba8` "docs: R1 prompt supplement after R0". dirty_paths(ROOT) = [].
- Step 2: sizes bt_input_20261123_da9c8de64ab4.json 3,612,319 B + fresh_bt.json 160,706 B = 3.77 MB (< 30 MB).
  Commit `b28d3f8` "test inputs: freeze R0 snapshot and baseline bt for offline consistency tests".
- Clean worktree (`git worktree add --detach`, b28d3f8), tests/test_daily_vs_backtest_signals.py +
  tests/test_paper_vs_backtest_reconcile.py: 0 skipped, **5 failed / 15 passed**.
  - Failing: test_daily_vs_backtest_signals[repo_cache] (r20/candidates/plans) and reconcile trades/pending.
  - Root cause: clean checkout has no `.cache/contracts` (gitignored). `build_main_map` then takes candidates only from
    snapshot `contract_*` stamps over the WHOLE hist (+ tracked `.cache/sina` rows) → the full-window backtest knows
    contracts that are stamped only later; the per-day truncated daily run does not → main_map / adjusted series differ.
  - Same worktree with `.cache/contracts` junctioned to the local 353-file cache, unpatched: 20 passed, 0 skipped.
  - Trial causal patch (archive/R7/main_map_causal_candidates.diff: stamped contracts become candidates only from the
    first day they are seen): clean worktree 20 passed. On the frozen replay headline unchanged (−0.769 / 7.469 / 56)
    but internals change even with the full cache: main_map none_days 0→93, adj_fallback_days 0→108,
    signal_candidates 1611→1612, 升水极端禁开多 67→68, AL/CU roll days. => engine behaviour change, not applied.
  - Worktree removed (junction unlinked first; local .cache/contracts still 353 files).
- Step 3: daily.yml `actions/cache@v6` (latest major; v7 does not exist) for `.cache/contracts`, inserted after
  setup-python so it restores before both the unit-test step and daily_update.py. YAML parse OK.
  Commit `a238a3d` "ci(daily): persist .cache/contracts across runs via actions/cache".
## R7a-D (option D; resumed after disconnect 2026-11-24 18:53)
- Status at resume: HEAD a238a3d; D1–D3 code uncommitted in the working tree.
- Done: D1 listing-calendar candidates (union of public_curve.MONTHS and delivery_rules months; strict MONTHS gave
  66 diff days / 64 None) → 0 diff / 7425 days, none 0→0 (main_map_compare_D1.json); D2 ContractStore wired into
  main_map/rolls/adjusted/book_core/contract_pack/contract_cache/simulate/daily_update/paper_book/replay; D3 11-23
  bundle 10,810,234 B (527 contracts), bundle replay with .cache/contracts renamed away == full cache == pre-D R5b
  replay, every field (−0.769/7.469/56). R6 fake-contract tests patched to list their fakes.
- Not yet done: run the two bundle-based consistency tests (edits are in the files); D4 prefetch check, workflow caches,
  clean worktree full pytest, new D tests; D5 commits; R7a steps 4–7.

## Earlier stop (superseded by option D)
- STOPPED before step 4: CI risk — daily.yml runs `pytest tests/` before daily_update.py; with the frozen inputs now
  committed, the consistency tests no longer skip in CI, and on the first run (empty cache) they would fail → daily
  never runs → cache never saved. Needs 磊's decision (causal main_map patch / tests require cache / other) before the
  candidate formal run, since a main_map change would alter the candidate.
- D3 tests: bundle-based R5a consistency + R5b reconcile 20 passed (calendar memo added: 211s -> ~60s); new tests/test_contract_store_main_map.py 4 passed.
- D4 workflows: actions/cache@v6 for .cache/contracts added to historical_backtest.yml (key hist-contracts-*) and
  weekly.yml (key weekly-contracts-*); yaml.safe_load OK for daily/weekly/historical_backtest.
- D4 tests: + test_formal_prefetch_covers_listing_candidates (fake fetcher). Local full pytest: 529 passed.
- Clean worktree D:\AI\cta-wt-r7d (a238a3d + D files copied, no caches) round 1: 528 passed, 1 failed:
  test_legacy_reproduces_ee4476b... got 4.619/4.617/42 vs lock 4.189/4.294/42. Same failure with D stashed (pre-D).
  Not the contract cache (local passes with .cache/contracts renamed away); it is the minute cache: local
  .cache/akshare/minute (50 tracked files, newer than committed 24c9fef) makes it pass. Lock set by R3 (1c82590,
  4.362/4.184 -> 4.189/4.294) on that local minute data => attributed to this track (R3).
  Fix: archive/R7/_capture_freeze_fix_minute_fixture.py -> tests/fixtures/freeze_fix_1113_minute.json (189,074 B,
  200 calls; reproduces 4.189/4.294/42 legacy, 6.265/8.001/62 fixed); the test serves minutes from it.
  tests/test_freeze_fix_gates.py: 9 passed locally and in the clean worktree (committed minute files).
- Side effect seen: pytest rewrites tracked lab/research/predictions/*.json, lab/research/volatility/
  vol_engine_daily_latest.json, data/lsp/shadow/*.json (pre-existing test behaviour); restore before commits.
- Disconnected during clean-worktree full pytest round 2 (resumed 19:15; long commands now run in background).
- Clean worktree round 2 (background, archive/R7/pytest_clean.log): 529 passed, 0 failed, 0 skipped in 171 s.
- D5 commits: 6493f4e "R7a-D: listing-calendar main_map candidates; contract store; snapshot contract bundle" (21 files);
  198642a bundle alone (archive/snapshots/bt_input_20261123_da9c8de64ab4.contracts.json). Snapshot blob unchanged (d4f4f9a).
- Worktree D:\AI\cta-wt-r7d removed; .cache/contracts 353 files; dirty_paths(ROOT) = []; stash list unchanged (11 old entries).
- archive/R7 D artifacts (compare/bundle/fixture scripts, main_map_compare_D1.json, replay_D3_bundle_empty_cache.json,
  pytest_clean.log, progress.md) left untracked for the R7a report commit.
- STOP after D5 as instructed; R7a steps 4–7 wait for the next message.
## R7a steps 4-7 (HEAD 198642a)
- Step 4: SCHEMA_VERSION v14-execfix; n_trials_census (5 / 11 / 8 -> 11) + n_trials_breakdown in result and validation bundle; scorecard code_schema from result; legacy test renamed.
- Step 4: scripts/render_readme_kpi.py (markers <!-- KPI:BEGIN/END -->, preview after candidate); test_proxy proposal drafted (goes in signoff report, no code change).
- Step 5: root hashes recorded in archive/R7/root_hashes_before_step5.txt; candidate run starting (log archive/R7/candidate_bt.log).
- Step 5a done: candidate_bt.json (v14, 2025-12-31..2026-11-24, 216d): net -1.068 / gross +1.575 / DD 7.623 / 56 trades; stress -1.674/7.032; prefetch requests=372 8.1s fetched=364 failed=8 (empty: EG/EB/JD2711, AU2703-2711); cache 353->615; snapshot bt_input_20261124_6574c6a4dbcd.json (contract_bars_n=611).
- Step 5b done: audit_candidate.json checked=52 mismatches=0 gap_through_target_conservative=1 (entry_order 56, continuous_range 25, roll_day 1).
- Step 5c: .cache/contracts renamed to .cache/contracts_R7_away for empty-cache replay (RESTORE if interrupted!).
- Step 5c: empty-cache replay (BundleContractStore 611) == candidate on 113/115 result fields; only curve_coverage source labels (carry_days identical) and ifind_slot differ. Running _candidate_offline.py with cache still away.
- Step 5c/d done: offline base re-sim == candidate, stress re-sim == formal stress row; scheme B book archive/R7/paper_book_candidate.json (asof 11-24, equity_mtm 197863.04, P short 1 @8278, pending []); legacy copy archive/R7/paper_book_legacy_pre_R7.json. Cache restored.
- D impact measured: main_map old(a238a3d) vs new on candidate snapshot + 615-file cache: 0/7452 diff days, 27 None (all 2026-11-24: Sina contract dailies for 11-24 not yet published at 19:25). Bundle vs cache main_map identical. Frozen replay vs candidate: same 56 trades; 8 trades proxy->contract fill (prefetched contracts); equity @11-23 198463.04 vs 198461.44 (+1.60); 11-24 session -600 (P short) -> -1.068.
- Step 5e: dry-run running (log archive/R7/l1_report_dryrun.log).
- Step 5e: first dry-run crashed (KeyError days_rolled: seeded book asof==today takes roll_engine_book no-op path without roll counters; print in daily_update main indexed them). Fixed print with .get; rerunning.
- Step 5e done: dry-run OK (exit after report write): selected=[] == book pending=[] (seeded book same day -> noop, book unchanged: P held, equity_mtm 197863.04); daily contract ensure requests=147 fetched=145 failed=2 (AU2703/AU2705 empty); quality ok 27/27; adj_fallback 27/27 (11-24 contract dailies not published; candidate adj_fallback_days_in_window=27 too); 9 root files hash-unchanged; dirty_paths = code edits only.
- Step 5 complete. README KPI preview written. Step 7 pytest started (archive/R7/pytest_R7a.log).
- Step 6: R7_signoff_report.md written; docs §2/§7 updated.
- Step 7: first full pytest stopped at ~30%: test_formal_write_dirty_exit2 driver went to network since D (main() fetches pack + prefetch before simulate). Stubbed hb._fetch_pack + ensure_listed_contract_bars in the driver (13 s, passes). Full pytest restarted (archive/R7/pytest_R7a.log).
- Step 7: full pytest 529 passed / 0 failed / 0 skipped (174.8 s); restored lab/research/predictions/latest.json, pred_20261123.json, lab/research/volatility/vol_engine_daily_latest.json; dirty_paths = intended edits only. Committing R7a.

## 2026-11-24 晚：rebase 到 origin/main（不 push）
- 20:30 只读检查：远端新增 3 个 bot 提交（a8d6141, 129f91d, 19cd660），只改 .cache/data/lab/archive 根目录/根目录运行产物，无代码/测试/配置。
- 备份：backup/pre-rebase-R7a = 3847d3c；archive/R0–R3 与 docs/R_TRACK_HANDOFF.md 已复制到 D:\AI\cta-path-a_untracked_backup_20261124。git restore -- .cache/ 后已跟踪文件无改动。
- git rebase origin/main(19cd660)：20 个提交全部重放，仅 c7f76c0（chore: snapshot run artifacts before R7）及其后一个提交处有 16 个运行产物冲突，全部取 CI 一方（--ours）；无代码/测试/docs 冲突。非运行产物路径与旧 HEAD 的树差异为 0。R7a 新哈希 921ce7b。
- 全量 pytest 已在后台启动（日志在仓库外 D:\AI\cta-path-a_untracked_backup_20261124\pytest_post_rebase.log）。
- 全量 pytest（rebase 后）：529 passed / 0 failed / 0 skipped（180.9 s）。已还原 pytest 改写的 lab/research/predictions/latest.json、lab/research/volatility/vol_engine_daily_latest.json。docs/R_TRACK_HANDOFF.md 已更新 HEAD=921ce7b 与备注（未提交）。
