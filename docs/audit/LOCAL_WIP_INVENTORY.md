# 本地 WIP / 文件记录（2026-11-23）

**目的**：记录「已在本机、尚未（或不应）进 GitHub main」的产物，避免与权威刀序混淆。  
**工作分支**：本地当前在 `main`（与 `origin/main` @ `98d9790` 对齐）。  
**权威刀序**：`docs/UPGRADE_ITERATIONS.md`。

---

## 1. 已上 GitHub main（可查）

| 项 | 证据 |
|----|------|
| VP Phase 1A + 1A-Fix | PR [#30](https://github.com/12poing-a11y/cta-path-a/pull/30) → `d61ec7c` |
| VP 后续计划文档 | PR [#31](https://github.com/12poing-a11y/cta-path-a/pull/31) → `98d9790` |
| 1B-0 **规格** | `docs/audit/VP_PHASE1B0_SPEC.md`（**无**实现代码） |
| 日更 20261123 seats/cache | 已随 main 合入 |

---

## 2. 本地保留 · 重要 · **未进 GitHub**（勿当「已归档」）

文档曾写 **Vol-V1.4 完成**，但下列路径在清理 stash 时确认：**不在 `origin/main` 树中**。  
状态改为：**本机研究完成 / Shadow only / 待单独开刀入库**。

| 路径 | 说明 |
|------|------|
| `research/options/volatility/` | IV 面 / Greeks / Shadow / 日报告模块 |
| `docs/VOLATILITY_ENGINE_SPEC.md` | Vol-V1.4 规格 |
| `lab/research/run_vol_engine_daily.py` | 日跑入口 |
| `lab/research/volatility/vol_engine_daily_latest.json` | 本地产物快照 |
| `tests/test_vol_engine_v14.py` | V1.4 单测 |
| `research/options/pricing/black76.py`（本地改） | 新增 `black76_theta` |
| `research/options/pricing/__init__.py`（本地改） | 导出 theta |
| `research/options/backtest/engine.py`（本地改） | `prefer_bid_ask` |
| `scripts/run_options_credit_bt.py`（本地改） | `--settle-only` |

**入库条件**：你明示「提交 Vol-V1.4 / 开 PR」；不得与 VP-1B-0 或 F2 混刀。

---

## 3. 已丢弃（不重要）

| 项 | 原因 |
|----|------|
| stash `wip-before-vp-1a-merge` | 200+ `.cache`/`data`/`lab` 日更噪音；main 已有更新版 |
| `research/options/volatility/__pycache__/` | 编译缓存 |

---

## 4. 当前姿态摘要

- **VP**：1A 已上 main；1B-0 规格已备、实现待明示；1B-1/1B-2 冻结。  
- **期权**：锁定 F2；gate `ready=false`（CF bidask≈1/10，SR/MA≈0/5）。  
- **Vol-V1.4**：本机可跑，**GitHub 未归档** — 见 §2。  
- **硬围栏**：不写正式 `paper_book` / seats / 正式 BT；不修 PA-001，除非明示。
