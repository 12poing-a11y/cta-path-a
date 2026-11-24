<!-- KPI:BEGIN -->
正式 KPI（由 `scripts/render_readme_kpi.py` 从 `historical_backtest_latest.json` 生成，勿手改）：`schema_version=cta-backtest-v14-execfix`，seats / next_open，窗口 **2025-12-31→2026-11-24**（216 个交易日），`fill_series=mixed`，代码 `198642a`，execution_rules `4b4f06a632cb`。

| 成本 | 净收益 | 毛收益 | 最大回撤 | 成本(元) | 交易 |
|---|---|---|---|---|---|
| Base | -1.07% | 1.57% | 7.62% | 5286 | 56 |
| Stress | -1.67% | 2.66% | 7.03% | 8675 | 56 |

胜率 33.93%，期望 0.030R，出场 止盈 18 / 止损 34 / 信号 4，proxy 入场占比 44.6%，当日平仓占比 21.4%。验证（Research 诊断，不单独晋级）：PSR 0.460，DSR 0.043（n_trials=11），PBO 0.386。结论「继续L1」。
<!-- KPI:END -->
