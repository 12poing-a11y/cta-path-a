# VP Phase 1B-0 — 实施报告

**日期**：2026-11-23  
**状态**：**完成 · 停**（不自动进入 1B-1）  
**规格**：`VP_PHASE1B0_SPEC.md`（你明示「开 VP-1B-0」后落地）

---

## 1. 做了什么

| 项 | 说明 |
|----|------|
| 只读适配器 | `virtual_portfolio/adapters/l1.py` — 真源=`l1_report.json`（仓库根） |
| 收件箱 | `virtual_portfolio/signal_inbox.py` → `data/virtual_portfolio/signal_inbox/` |
| 权限拆分 | 新建 `SIGNAL_READ_ALLOWED`（默认 false）；**不**打开 `SIGNAL_INGEST` / `AUTO_*` |
| Desk | 「虚拟组合」页增加收件箱：开/关只读收信号、摄入 L1、按 asof 查看 |
| 测试 | `tests/test_vp_phase1b0.py`（T-RO-01…07） |

## 2. 验证

```text
pytest tests/test_vp_phase1b0.py tests/test_vp_phase1a.py -q
25 passed
```

## 3. 明确未做

- 不下单、不改账户 ledger/持仓/权益  
- 未改 paper_book / daily_update / F2 / PA-001  
- **未**进入 1B-1 / 1B-2  
- 未按权益自动调仓  

## 4. 使用

1. Desk → **虚拟组合**  
2. 「开启只读收信号」  
3. 「摄入今日 L1 → 收件箱」  
4. 按业务日查看行；无跟单按钮  

## 5. 建议下一刀

**停**；观察收件箱数日后再明示 **开 VP-1B-1**，或积样等 **F2**。
