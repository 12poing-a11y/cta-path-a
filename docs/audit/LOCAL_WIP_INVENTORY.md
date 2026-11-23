# 本地 WIP / 文件记录（2026-11-23）

**目的**：区分「已进 GitHub」与「仍仅本机」。  
**工作分支**：`main`（与 origin 对齐）。  
**权威刀序**：`docs/UPGRADE_ITERATIONS.md`。

---

## 1. 已上 GitHub main

| 项 | 证据 |
|----|------|
| VP Phase 1A + 1A-Fix | PR [#30](https://github.com/12poing-a11y/cta-path-a/pull/30) |
| VP 后续计划 | PR [#31](https://github.com/12poing-a11y/cta-path-a/pull/31) |
| 1B-0 **规格** | `docs/audit/VP_PHASE1B0_SPEC.md`（无实现） |
| **Vol-V1.4 轻量归档** | `research/options/volatility/` + 规格/测试/定价小改；**Shadow only · 结果弱 · 不晋级** |

---

## 2. 仍可能脏在本机（日更噪音 · 勿误提交）

`.cache/**`、`data/**` 日更、`l1_report*.json`、`lab/research/lsp/**` 等 — **不**随 Vol 归档提交。

---

## 3. 姿态摘要

- **VP**：1A 已上 main；1B-0 规格已备、实现待明示。  
- **Vol-V1.4**：已轻量入库；反馈弱 → **禁止晋级**；下一 Vol 刀须明示。  
- **期权**：锁定 F2；gate `ready=false`。  
