# R5a progress
- Step 0 DONE: signal_path_diff.md
- Step 1 DONE: signal_core.path_a_candidate; simulate pure refactor (replay_after_R5a.json == replay_after_R4b.json ex git_sha/config_version; _bitwise_refactor_check.py ALL_IDENTICAL vs 1cfe6fc incl. adjusted_signals=False)
- Step 2 DONE: daily fetch_history(LOOKBACK_DAYS); research/data_quality/contract_cache.py; adj_fallback fields; contract_fetch_cold.json (cold 191 req / 19.1 s; warm 0)
- Step 3 DONE: seats / carry / vol_bypass unified via core (lagged books); lab_edge + observe min_lots stay daily-only (see signal_path_diff.md)
- Step 4 DONE: tests/test_daily_vs_backtest_signals.py, tests/test_contract_cache.py
- Step 5 DONE: pytest 518 passed; replay bit-identical; dry-run core + legacy -> dryrun_old_vs_new.json
- Step 6: docs + commit (see git log)
