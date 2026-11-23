# VP Phase 1A — 污染防护测试报告

**日期**：2026-11-23  
**命令**：`python -m pytest tests/test_vp_phase1a.py -q`  
**结果**：**10 passed**

---

## 覆盖项

| 验收项 | 测试 | 结果 |
|--------|------|------|
| 多账户隔离 | `test_multi_account_isolation` | PASS |
| 开/加/减/平权益一致 | `test_open_add_reduce_close_equity_consistent` | PASS |
| 保证金缺失标记 | `test_margin_missing_flagged` | PASS |
| 拒绝负手数 / 重复成交 | `test_reject_negative_and_duplicate` | PASS |
| 持仓批次 | `test_lots_batches` | PASS |
| 禁止 CTA_SIGNAL（1A） | `test_cta_signal_source_forbidden` | PASS |
| 持久化重建 | `test_persistence_rebuild` | PASS |
| Paper / L1 / F2 字节不变 | `test_pollution_paper_l1_f2_unchanged` | PASS |
| 账本不可静默覆盖 | `test_history_not_silently_rewritten` | PASS |
| 写入围栏 | `test_guard_rejects_outside_namespace` | PASS |

## 污染断言细节

在临时根目录放置哨兵文件：

- `paper_book_latest.json`
- `data/l1_report.json`
- `data/options/upgrade_gate_latest.json`（`ready=false`, `next_upgrade_id=F2`）

执行开户、入金、开仓、平仓后，三文件 **SHA-256 不变**；F2 字段仍为锁定态。

## 源码围栏

`virtual_portfolio/` 内无 `paper_book` / `daily_update` / `refresh_paper_book` 引用（grep 确认）。
