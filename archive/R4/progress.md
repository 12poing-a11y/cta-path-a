# R4 progress

- HEAD at start: fcf0a1a (R6c).
- Step 0 DONE: `_step0_prefix.py` -> `prefix_R6c_caps.json` (17 gross>50% entry days, max 113.52%; 0 risk>8% days)
- Steps 1-3 DONE: historical_backtest `_book_usage`/caps; position_rules `existing_buckets`, `book_usage_from_positions`; daily_update `_apply_caps(held=)`; paper_book `caps_book_check` + `skip_reason=caps_book`
- Step 4 DONE: tests/test_caps_include_book.py (9 tests)
- Step 5 DONE: pytest 493 passed; replay_after_R4.json; audit_after_R4.json (checked 52, mismatches 0); `_build_compare_R4.py` -> `R6c_vs_R4.json`; `_floor_artifact_diag.py` -> `floor_artifact_diag.json`
- Step 6: docs updated; commit pending/after this note.

## R4b
- Done: position_rules top-up (topup=True default), simulate caps_topup_lots/revived, tests (499 passed), replay_after_R4b/audit_after_R4b (0 mismatches), diag rerun = 0, R4_vs_R4b.json, docs. Commit: R4b.
