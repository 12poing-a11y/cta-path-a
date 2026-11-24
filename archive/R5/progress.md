# R5a progress
- Step 0 DONE: signal_path_diff.md
- Step 1 DONE: signal_core.path_a_candidate; simulate pure refactor (replay_after_R5a.json == replay_after_R4b.json ex git_sha/config_version; _bitwise_refactor_check.py ALL_IDENTICAL vs 1cfe6fc incl. adjusted_signals=False)
- Step 2 DONE: daily fetch_history(LOOKBACK_DAYS); research/data_quality/contract_cache.py; adj_fallback fields; contract_fetch_cold.json (cold 191 req / 19.1 s; warm 0)
- Step 3 DONE: seats / carry / vol_bypass unified via core (lagged books); lab_edge + observe min_lots stay daily-only (see signal_path_diff.md)
- Step 4 DONE: tests/test_daily_vs_backtest_signals.py, tests/test_contract_cache.py
- Step 5 DONE: pytest 518 passed; replay bit-identical; dry-run core + legacy -> dryrun_old_vs_new.json
- Step 6: docs + commit (see git log)

# R5b progress
- Step 0 DONE: paper_path_diff.md (difference table, downstream readers, incompatibilities)
- Step 1 DONE: book_core.PositionEngine (manage + fill_selected); simulate refactor; _bitwise_refactor_check.py vs 42cb2e9 ALL_IDENTICAL (4 configs); replay_after_R5b.json == replay_after_R5a.json ex git_sha/config_version
- Step 2 DONE: paper_book R5b engine book (roll_book / plan_entries / roll_engine_book / attach_pending / advance_engine_book; base + fingerprint no-op); daily_update engine path (--paper-book / --paper-out), legacy root book unchanged
- Step 3 DONE: tests/test_paper_vs_backtest_reconcile.py (12 trades identical; 40 days pending == sim selection; same-basis equity diff 0, raw 2.94e-4)
- Step 4 DONE: paper_book.py --rebuild-preview -> paper_rebuild_preview.json (+ _bookA / _bookB)
- Verify DONE: pytest 524 passed; legacy gold unchanged; dry-run on book A: root hashes unchanged, selected == pending (l1_report_dryrun_R5b.json, paper_book_dryrun_R5b.json)
- Docs + commit: see git log
