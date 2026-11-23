# VP Phase 1A — 变更清单

**日期**：2026-11-23

## 新增

| 路径 | 说明 |
|------|------|
| `virtual_portfolio/` | 账户/账本/成交引擎 + 写入围栏 |
| `configs/virtual_portfolio/instruments_v1.json` | 版本化品种参数（不写回 universe） |
| `configs/virtual_portfolio/schema_versions.json` | schema 登记 |
| `desk/virtual_portfolio_panel.py` | Desk「虚拟组合」页 |
| `tests/test_vp_phase1a.py` | 10 项验收/污染测试 |
| `docs/audit/VP_PHASE1A_*.md` | 架构/迁移/污染报告/用户说明/本清单 |

## 修改

| 路径 | 说明 |
|------|------|
| `desk/app.py` | 导航增加「虚拟组合」并挂载面板 |
| `docs/UPGRADE_ITERATIONS.md` | VP-Phase1A 完成态 |
| `docs/options/ROADMAP.md` | 旁轨一句同步 |
| `docs/audit/VP_PHASE1_GO_NO_GO.md` | 标注 1A 已执行（若同步） |

## 未改（硬围栏）

- `paper_book.py` / `paper_book_latest.json`  
- `daily_update.py` / `l1_report*`  
- `universe.json` 字段  
- `research/options/upgrade_gate.py` / F2  
- `PAPER_ANOMALY_TRACKER` 修复  
