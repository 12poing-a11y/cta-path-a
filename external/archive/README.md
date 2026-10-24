# 验证归档（不进研究台）

不能**长期、稳定、自动**获取的外部 KPI / 研报摘录，退出研究台策略库与评分栏展示；**原始数据保留**，供后期对照验证本地代理 / Path-A 结果。

## 当前归档

| 来源 | 路径 | 原因 |
| --- | --- | --- |
| 东证金工周报 KPI | `../dzqh_weekly_latest.json`、`../strategies/dzqh_*.json`、`desk_specs/dzqh_*.json` | 依赖用户粘贴，无公开可编程接口 |

## 规则

- 研究台 `desk/strategies/extra/` **不加载** `desk_active: false` 或 `validation_archive` 标签的条目。
- 本地可复现的代理（`proxy_*`）与 Path-A 曲线仍留在台上。
- 需要对照时：直接读本目录 / `external/strategies/dzqh_*.json`，或临时把 `desk_specs` 拷回 `extra` 并设 `desk_active: true`（仅人工验证，勿提交为默认）。

`materialize_dzqh.py` 只写入本归档与 `external/strategies/`，不再激活研究台。
