# Plan A · 日频因子实验室（D: 盘）

与 Path-A **并行**：不改 `universe.entry_filter` / 止损止盈 SSOT。目标是可长期维护的商品日频因子库 + 固定样本外验证，磁盘预算 **5–20 GB**（本机 D: 当前空闲通常 ≫ 此数）。

## 目录

```
lab/
  config/          品种池、OOS 切分、因子注册表、存储预算
  data/raw/        原始摘录（可选）
  data/bars/       标准化日线（连续主力优先）
  data/factors/    日频因子面板（按日或按批）
  research/ic/     IC / 分层产物
  research/oos/    样本外净值与对照
  research/runs/   一次运行的元数据（参数哈希、截止日期）
  scripts/         引导、磁盘检查、从 Path-A 缓存灌日线/因子
```

## 快速开始

在仓库根目录 `D:\AI\cta-path-a`：

```powershell
python lab/scripts/check_storage.py
python lab/scripts/bootstrap_lab.py
python lab/scripts/ingest_bars_from_path_a.py
# 可选：补席位历史（SHFE/CZCE → .cache/member，默认 2018+）
python lab/scripts/backfill_member_cache.py --start 2018-01-01
python lab/scripts/build_factor_panel.py
python lab/scripts/run_oos_smoke.py
# P0 正式初筛
python lab/scripts/run_ic_groups.py
python lab/scripts/run_oos_vs_path_a.py
# 趋势R2 与 Path-A seats 开仓同向/逆向纸面对照
python lab/scripts/run_r2_align_paper.py
```

产物：

- `research/ic/ic_groups_latest.json` — IS/OOS RankIC、ICIR、五分组多空  
- `research/oos/oos_vs_path_a_latest.json` — OOS 合成截面（费后近似）vs 本地 Path-A 代理 + 官方短窗重叠  
- `research/runs/oos_*` — 带 panel 哈希的运行快照  

## 与研究台闭环（只读）

1. 改因子 / 重跑 `run_ic_groups.py` + `run_oos_vs_path_a.py`  
2. 打开研究台 → **决策**页或 **状态评分 → 综合评估**，看「因子实验室 · Gate」  
3. Gate 未过 → 保持 `entry_filter=seats`；过了 → 再人工讨论是否改旁路/入场  

研究台模块：`desk/lab_panel.py`（不写仓、不改 SSOT）。

## 规则

- 样本内 / 样本外日期以 `config/oos_split.json` 为准；禁止用全样本调参后再报 OOS。
- 仓单等缺失因子在面板里显式 `null` + `missing` 标记，不编造。
- 研究台决策旁路（升贴水 / 多维波动）可继续用；本实验室输出进 `research/oos`，默认不自动改日报开仓。
- **策略台讨论门槛**（过线仍需人工确认，不自动改 `entry_filter`）：OOS 对齐窗相对 `path_a_proxy_tsmom` 满足 (A) 回撤更低且收益不差，或 (B) 收益不差且 ret/DD≥2 并优于代理、回撤不过度恶化；且官方短窗重叠不显著更差。
- **IS 入选（合成成员）**：`n_ic_days≥120` 且 `|ICIR|≥0.2` 且按 `sign(IC)` 交易后的五分组 IS 收益>0；权重 ∝ `|ICIR|`。OOS 只做验收与 leave-one-out 贡献，不回写权重。
- **可交易软信号**：`python lab_signal.py` → `research/signals/latest.json`；`universe.lab_edge_bypass` 开启时，截面分位与拟开仓方向严重逆向 → 决策观望（缺数放行），**不改** `entry_filter=seats`。
