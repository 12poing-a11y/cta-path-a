# 套利波动率托管升级（Shadow V1）

**分支**：`feature/arbitrage-volatility-shadow-v1`  
**基线**：`main` @ `10aefe49e67336e942ba49d0424bb2e89a62b5ca`  
**定位**：研究/影子模块；不写 `paper_book`，不改变 Path-A 正式参数，不产生下单指令。

## 1. 代码审计结论

当前仓库已经有：
- `vol_factor_combo.py`：短/中/长窗收益波动率比，作为 Path-A 观望旁路；
- `desk/hmm_regime.py`：三状态 HMM，当前实现注释明确参数全样本估计，因此不能直接将其标签视作严格样本外实时状态；
- `desk/arb_panel.py`：跨期近次月 gap Z-score、跨品种 A/B 价格比 Z-score，属于观察面板；
- `lab/scripts/run_portfolio_risk.py` 与 `portfolio/*`：策略净值层面的相关性、MRC、CVaR 和简化压力情景。

尚未发现完整打通的：
- 对每一组套利腿单独估计价差波动率；
- 严格滞后一根的滚动对冲比率；
- 相关性/对冲系数断裂时 fail-closed 风险闸门；
- 将价差风险预算换算为双腿合约手数；
- 双腿成本、保证金、跳空、成交不同步后的组合级压力验证。

因此，现有“套利观察”不能等同于套利风险托管。

## 2. 本分支首批实现

新增 `research/arbitrage_volatility.py`：
- `rolling_spread`：用历史窗口估计 OLS 对冲系数；估计截至 t-1，应用于 t；不前填缺失行情。
- `spread_volatility`：对价差变化计算短/长窗标准差、EWMA、价差 Z-score 与波动扩张比。
- `pair_correlation`：同步双腿收益相关性。
- `evaluate_risk_gate`：关键数据缺失、相关性断裂、对冲系数异常或价差波动极端时禁止新增风险。
- `size_pair_position`：将价差波动风险预算换算为 A/B 双腿手数估算；必须先通过风险闸门。

新增 `tests/test_arbitrage_volatility.py` 覆盖无前视、缺失数据、波动率、相关性、fail-closed 和仓位换算。

## 3. 重要口径与限制

1. 当前 V1 用滚动 OLS 价差作为研究代理，不宣称已完成协整检验。上线交易前须增加 Engle-Granger/ADF 稳定性检验、滚动残差半衰期和结构突变检测。
2. OLS 的 `beta` 是价格单位对冲比率，不是可直接下单手数；合约乘数换算后还需整数手约束、最小变动价位和实际净敞口核验。
3. V1 的风险金额仅为单标准差价差变动近似，不是 VaR/ES，也未包含手续费、滑点、保证金、跳空、涨跌停、流动性和腿部不同步。
4. `pair_correlation` 是风险诊断项；相关性高不证明价差平稳，相关性低也不单独证明套利失效。
5. HMM 当前全样本估参实现存在前视风险；在改为 expanding/rolling fit + forward filter 并通过 no-lookahead 测试前，不接入风险闸门。

## 4. 下一阶段实施顺序

### V1.1 — 数据与价差有效性
- 统一合约映射、交易日历、双腿同频对齐；禁止静默前填。
- 加入合约乘数、tick、手续费、保证金、涨跌停和成交量/OI字段。
- 加入滚动协整检验、ADF、半衰期、残差结构突变诊断。

### V1.2 — 风险托管与回测
- 组合层风险预算：按相关性聚类/边际风险贡献分配预算，不使用等权假设替代真实风险。
- 价差 ATR/波动率目标、EWMA、历史分位数、尾部 ES 并列。
- 双腿同步成交模型：T 日信号、T+1 可成交价格；腿部部分成交/滑点/涨跌停压力。
- 对照组：固定手数、单腿 ATR、价差波动率、价差波动率+风险闸门、组合风险预算。

### V1.3 — 影子监控与人工 Gate
- 只输出建议手数、风险状态、阻断原因和数据质量；不自动改仓。
- 连续 20 个交易日无数据质量阻断误报，且滚动 OOS 样本充足后再评审。
- 晋级要求：费后 OOS 风险调整收益改善，最大回撤/ES 不恶化，参数敏感性可接受，压力测试通过；最终人工批准。

## 5. 验收标准

- [ ] 新模块只依赖标准库，不增加运行时依赖。
- [ ] no-lookahead 单元测试通过。
- [ ] 缺失关键字段时风险闸门 fail-closed。
- [ ] 现有 Path-A / paper_book / execution_rules 无改动。
- [ ] 新增代码通过本地 pytest 与 CI。
- [ ] 有真实双腿历史数据后才运行绩效回测；无数据时只验收数学函数，不报告策略收益。

## 6. 研究依据

- Kang & Kwon (2021), *Volatility-managed commodity futures portfolios*, Journal of Futures Markets. 其样本外结果提示波动率管理并非商品期货普遍有效，必须做 OOS 验证。
- Xu & Wang (2021), *Managing volatility in commodity momentum*, Journal of Futures Markets. 中国商品期货动量研究报告了波动率管理的改善，但不能直接外推到价差套利。
- Fan & Zhang (2024), *Commodity premia and risk management*, Journal of Futures Markets. 结果强调止损、信号质量、波动率自相关与交易成本需要共同评估。

## 7. 运行方式

```powershell
python -m pytest tests/test_arbitrage_volatility.py -q
```

本阶段尚未将新模块接入 Streamlit 页面、Path-A、正式回测或任何交易账本。
