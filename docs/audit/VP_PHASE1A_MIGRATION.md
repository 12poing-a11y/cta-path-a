# VP Phase 1A — 数据迁移 / Schema 计划

**原则**：增量添加；**不删除、不重写**现有 Path-A / options / paper 数据表或 JSON。  
本仓 VP 使用 **文件系统 JSON/JSONL**（非 SQL）；「迁移」= schema 版本登记 + 目录约定。

---

## 1. 新增命名空间

| 路径 | 作用 | 既有数据影响 |
|------|------|--------------|
| `configs/virtual_portfolio/` | 品种参数与 schema 版本 | 无 |
| `data/virtual_portfolio/` | 账户状态与账本 | 无（`rule_lock` 已忽略 `data/`） |
| `virtual_portfolio/`（Python） | 引擎 | 无 |

## 2. Schema 版本

`configs/virtual_portfolio/schema_versions.json`：

| schema_id | 版本 | 说明 |
|-----------|------|------|
| `cta-vp-account-v1` | 1 | account.json |
| `cta-vp-ledger-v1` | 1 | ledger.jsonl 事件 |
| `cta-vp-instruments-v1` | 1 | instruments_v1.json |

未来破坏性变更：新增 `instruments_v2.json` 并在 schema_versions 登记；旧账户继续读 v1，直至显式迁移脚本（本刀不写破坏性迁移）。

## 3. 增量规则

1. 只 **创建** VP 目录与文件；不 touch `paper_book_latest.json`、`l1_report*.json`、`universe.json` 字段。  
2. instruments 从 universe **只读复制** mult/tick/fee 到 VP 配置；保证金列为 research 估计或 null。  
3. 账户删除 = `status=archived` + 停止新事件；ledger **保留**。

## 4. 回滚

删除或移走 `data/virtual_portfolio/` 与 `configs/virtual_portfolio/` 即可回滚 VP；正式层无耦合。  
代码回滚：移除 `virtual_portfolio/` 包与 Desk 挂载即可。
