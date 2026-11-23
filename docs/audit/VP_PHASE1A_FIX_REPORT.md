# VP Phase 1A-Fix — 缺陷修复报告

**日期**：2026-11-23  
**依据**：`VP_PHASE1A_ACCEPTANCE_AUDIT.md` PARTIAL PASS + GPT「VP-Phase 1A-Fix」指令  
**范围**：仅 ACC-01 / ACC-02 + 补测；**未**进入 1B-0。

---

## 1. 修复前状态

- 验收：**PARTIAL PASS**
- ACC-01：`load_account_state` → `rebuild_account`，查询重写投影
- ACC-02：无显式 `ACCOUNT_MODE` / `AUTO_*` / `SIGNAL_INGEST_*`（fail-closed）
- 测试：10 项；缺空头平仓、平今、tick、失败回滚、查询只读

## 2. 修复内容

| ID | 改动 |
|----|------|
| ACC-01 | 新增 `compute_account_state`（纯内存）；`load_account_state` **只读**磁盘投影；`rebuild_account` 为显式写盘 + `rebuild_audit.jsonl` |
| ACC-02 | `permissions.py`：默认 `RESEARCH_ONLY`、`MARGIN_STATUS=UNVERIFIED`、`AUTO_OPEN/CLOSE=false`、`SIGNAL_INGEST=false`；后端 `check_auto_permissions` / `_check_source` fail-closed |
| 补测 | 查询 mtime 不变、空头平仓、部分平仓、平今费、tick 拒绝、失败开仓不写 ledger、rebuild=compute |
| Desk | 查询走只读 load；增加「重建投影」按钮；展示运行状态字段 |
| 其它 | 开平仓增加 tick 对齐校验 |

## 3. 测试结果

```text
pytest tests/test_vp_phase1a.py -q
17 passed
```

原 10 项保留并通过；新增 7 项通过。污染哨兵仍在套件内。

## 4. 未解决问题

| ID | 说明 | 建议 |
|----|------|------|
| ACC-05 | instruments 版本哈希未强绑定到每笔成交（仅 schema 名） | 1B-1 前 |
| ACC-06 | ledger 无密封/签名 | 延后 |
| ACC-07 | 需 GitHub 分支归档（本刀执行） | 独立分支，不直推 main |
| — | 无真正 DB 事务；文件失败回滚测覆盖「拒单不写账」 | 可接受于 JSONL 模型 |
| — | 并发文件锁仍无 | 1B 前评估 |

## 5. Phase 1A 最终验收结论

**PASS（带 RESEARCH_ONLY 约束）**

- 查询只读、显式重建、权限 fail-closed、补测与污染测通过。  
- **不得**自动进入 1B-0；须人工复核后再开只读信号接入。

## 6. 变更文件（预期）

- `virtual_portfolio/**`
- `configs/virtual_portfolio/**`
- `desk/virtual_portfolio_panel.py` / `desk/app.py`
- `tests/test_vp_phase1a.py`
- `docs/audit/VP_PHASE1A_*.md` / `UPGRADE_ITERATIONS.md` / `ROADMAP.md`
