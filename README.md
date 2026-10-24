# cta-path-a

中国商品期货 **CTA 路径A** 自动验证台（纸面记账，不下单）。

属于 [@12poing-a11y](https://github.com/12poing-a11y) 的量化研究档案。

## 策略规则（L1）

1. **信号**：主力合约近 20 日收益与近 60 日收益同向 → 顺势；否则空仓  
2. **仓位**：`lots = floor(风险预算 / (ATR14 × 合约乘数))`  
3. **组合上限**：最多 **3** 个品种；总名义敞口 `Σ|lots|×close×mult` ≤ 权益的 **50%**（`position_rules.apply_portfolio_caps`）  
4. **参数**：见 `universe.json`（Equity ¥20万 / 风险% / `max_positions` / `max_gross_exposure_pct`）  
5. **路径A**：只记账、不自动下单；用于规则与执行纪律验证

## 行情来源

日线先拉**新浪**和**腾讯**，按交易日合并：同一天新浪覆盖腾讯，腾讯只补缺口。下面任一情况才调用 iFinD 主力连续，重叠日期仍以免费源为准：

- 合并后不足 80 根
- 最后一根或最近 80 根缺收盘、最高、最低
- 最后交易日早于今天 12 个自然日

新浪接口是 `InnerFuturesNewService.getDailyKLine`，代码为 `{品种}0`（例如 `M0`、`MA0`）。`IndexService.getInnerFuturesDailyKLine` 停在 2024-07，不使用。腾讯公开 K 线目前对 `nf_M0` 这类期货代码返回参数错误，请求仍会发出，一旦返回日线会自动并入。`hq.sinajs.cn` 的实时字段和日线 OHLC 对不齐，不用它改写日线。

换月和近月/次月用新浪具体合约日 K（如 `RB2601`）。会员持仓**统一走东财 → 新浪补缺**（写入 `.cache/member/em-*.json`，大商所切片同步 `dce-*.json`）；上期所/郑商所 txt 与 DCE zip 仅作辅、不挡观察门禁。K 线仍是新浪+腾讯（腾讯无持仓龙虎榜接口）。上面仍不够才对那个品种补一次 iFinD。

2025-11-26 至 2026-10-20 的对照里，20/60 现版净收益 +6.75%、净最大回撤 5.50%。换月窗口加 ATR 超过收盘 8% 之后，净收益 −3.84%、净最大回撤 8.22%。升贴水、持仓量、会员持仓、高潮日与板块都没有同时超过现版的净收益和回撤。日报因此用 `entry_filter=base`。回测仍按每边 1 跳滑点，手续费用申银万国 2026-09-02 客户公示价，同时给出毛收益和净收益。

日报已补进席位级联，`entry_filter=seats`。顺序是：跟随机构（中信期货、国泰君安、华泰期货、永安期货、东证期货/东证融汇），其次跟随外资（摩根大通、摩根士丹利、瑞银、高盛），再次站在家人对面（东方财富、平安、方正中期、徽商、中信建投）。公开排名写「中信建投」，按这个名字计入中建投。席位只确认或拦住 20/60 的方向，单边行情不开反向单。大商所无 dce 缓存时放行。2025-11-27 至 2026-10-20，seats 净收益 +6.22%、净最大回撤 5.04%；同窗 base +6.77%、5.50%。这一年五家机构净持仓每天都有方向，开仓决定落在机构一侧；外资和家人留在机构净持仓为 0 时使用。

## iFinD Key（primary / backup）

仅在新浪和腾讯不够用时作为补缺。

启动时**始终优先 primary**。额度/鉴权失败时进程内切到 backup；**默认不写回** `mcp_config.json`（避免粘在 backup）。

| 变量 | 作用 |
|------|------|
| `IFIND_AUTH_TOKEN` | primary Key |
| `IFIND_AUTH_TOKEN_BACKUP` | backup Key（可选） |
| `IFIND_ACTIVE_SLOT` | 默认 `primary`；仅调试时设 `backup` |
| `IFIND_PERSIST_FAILOVER` | 设为 `1` 才把 failover 写入本地 `mcp_config.json` |

## 手机无电脑自动验证

可以。流程跑在 **GitHub Actions**，不依赖你电脑开机。  
**先配 Secrets**，否则会失败 —— 见 [`MOBILE.md`](./MOBILE.md)。

## 自动化

| Workflow | Cron (UTC) | 北京时间 |
|----------|------------|----------|
| `CTA Daily 15:30 CST` | `30 7 * * 1-5` | 工作日 15:30 |
| `CTA Weekly Backtest` | `0 1 * * 0` | 周日 09:00 |
| `CTA Historical Backtest` | `0 13 * * 0` + 手动 | 周日 21:00 / 随时 Run |

手机：GitHub App → **Actions** → **Run workflow**。

可选写入 Notion（需 `NOTION_TOKEN`）。

## 本地 / CI

```bash
pip install -r requirements.txt
# 本地：复制 mcp_config.example.json → mcp_config.json 并填入 iFinD token
# CI：使用 Secrets IFIND_AUTH_TOKEN / IFIND_AUTH_TOKEN_BACKUP / NOTION_TOKEN
python daily_update.py
python weekly_backtest.py
python notion_sync.py signals   # 可选：日信号台账
python notion_sync.py trades    # 建平仓流水 + 规则/统计页（需 NOTION_TOKEN）
python notion_sync.py annual    # 一年回测报告/曲线，并自动跑 trades
```

建平仓原因与回测统计写入 Notion 库 **CTA Path-A·建平仓流水**，规则说明页见主台账下「建平仓规则与回测统计」。平仓原因码：`target` 止盈 / `stop` 止损 / `signal` 趋势失效。

## 本地研究台（Streamlit）

只读看板：多策略净值对比、日信号、图表（日/周/月本地连续 + 15m/60m 分钟量价 + MA/ATR + PathA/事件标记）、策略注册表、保护期权纸面机会。不接实盘。图表页日线读 `.cache/sina`；分钟线优先新浪 `futures_zh_minute_sina`，东方财富 push2his 作备选与交叉验证（`minute_data.py`），量价判断见 `volume_price.py`，不下单。

```bash
pip install -r requirements-desk.txt
streamlit run desk/app.py
```

依赖单独放在 `requirements-desk.txt`（`streamlit` / `plotly` / `pandas`），不并入 CI 的 `requirements.txt`。

### 15:30 日报与本地同步

GitHub Actions（工作日 **15:30 北京时间**）批量拉取并提交：

- `l1_report.json` / `archive/`
- 席位全量缓存：`.cache/member/`（`shfe-*.txt` / `czce-*.txt` / `dce-*.json` / `em-*.json`）
- 连续日线：`.cache/sina/<日>/{CODE}0.json`（仅连续合约，不含月份）
- 小周期：`.cache/akshare/minute/`（**15m / 60m**，全品种）

本地研究台 **只读磁盘**；侧栏 **「同步日报」**（`git pull`）即可拿到上述落库，无需本机常驻爬虫。

1. 默认勾选「同步 git 报告」→ 日报 / archive / 席位 / 分钟 / CODE0
2. 可选「刷新本地缓存」→ `python daily_update.py`（本机重拉，较慢、需网络）
3. 同步后自动滚 `paper_book_latest.json`；或 `python paper_book.py`
4. 侧栏对照：日信号 asof · 模拟仓 asof · 回测期末 · `equity_state` mtime

执行参数单一真相：`execution_rules.json` + `universe.json → selection`（现行止损 **1.2×ATR** / 止盈 **1.5R**）。`notion_sync.py trades` 对「持仓中」先归档再写入，平仓按键去重。

若本机不是 git 仓库、或没有 remote，勾选「刷新本地缓存」从免费源重建日报与缓存。

### 如何挂新策略

1. 引擎产出一份含 `equity_curve`（及可选 KPI）的 JSON  
2. 在 `desk/strategies/extra/<id>.json` 写入，例如：

```json
{"id": "my_custom", "name": "自定义", "curve_file": "path/to/backtest.json", "tags": ["extra"]}
```

3. 重启 Streamlit，侧栏多选即可叠加  

内置：`path_a`、`benchmark`、`path_a_opt_hedge`、`wyckoff`（无 JSON 时为占位）、`param_sweep`（`param_sweep_latest.json`）。`benchmark_latest.json` 若尚无 `equity_curve`，概览页对该策略仅展示 KPI 并灰显提示。

扫参：`python param_sweep.py`（stop×RR）；加 `--thresh` 再扫动量门槛；`--from-archive` 只从 `archive/rr_grid.json` 重建桌面 JSON。

### 东证周报（验证归档）+ 本地代理

研报（东证金工）KPI **不能长期稳定自动获取**（依赖粘贴），也**不能**在本仓库完整复刻。研究台**不再展示**「东证·…」条目；历史摘录保留供后期验证：

1. 数据：`external/dzqh_weekly_latest.json`、`external/strategies/dzqh_*.json`、`external/archive/`（见该目录 README）  
2. 刷新归档：`python external/materialize_dzqh.py`（只写归档，不激活研究台）  
3. 本地可复现近似仍上台：`python proxy_cta.py` → 「本地代理·CWFT」等  

国债日频择时同属归档 KPI，不扩品种池进 T/TF/TL。

**升贴水极端旁路**（`universe.carry_bypass` / `execution_rules.carry_bypass`）：在 `entry_filter=seats` 之后软叠加。默认 `|近次月 gap|≥1%` 时升水禁开多、贴水禁开空；`action=scale` 可改为按 `scale` 减仓；缺升贴水数据不拦。日报信号带 `carry_bypass` / `carry_gap_pct`；决策页证据与跨模型对照会显示，逆向极端时结论降为观望。不改 ATR 止损止盈，也不把 `entry_filter` 切成 `carry`。

**多维波动率旁路**（知识卡 `external/knowledge/multidim_vol_factor_card.json`，模块 `vol_factor_combo.py`）：短5/中20/长60 日收益标准差，`ratio=短/长`；默认 `≥1.6` 高波扩张 → 决策降观望（`vol_bypass.action=observe`），`≤0.7` 仅标注。不替换 Path-A 入场，不编造研报 KPI。

**Plan A 日频因子实验室**（`lab/`，仍在 D:）：与 Path-A 并行的长样本因子库骨架，预算 5–20 GB。见 `lab/README.md`。灌数后跑 `run_ic_groups.py` + `run_oos_vs_path_a.py`。研究台 **决策 / 综合评估** 只读展示 Gate（`desk/lab_panel.py`），**未过 gate 不改 `entry_filter`**。

**股指择时**（上证50/沪深300/中证500/中证1000）：规格 `external/equity_timing_spec.json`，映射 `equity_timing.py`，每日信号填 `external/equity_timing_latest.json`。已并入研究台「状态评分 → 综合评估」（与方向三桶、HMM、模型投票、决策卡、策略库评分板一并计分）。与商品 Path-A 品种池分离；预测窗为 t+1 开→t+2 开。

### 期权机会说明

「期权机会」页复用 `option_hedge.py` 与 `universe.json` → `observe.option_hedge` 默认（`premium_atr_mult` / `strike_atr_mult`）。多→买保护 Put，空→买保护 Call；行权价与权利金先做 **合成 ATR 估算**，有新浪商品期权链时再对照近月实盘权利金（`option_compare.py`），仅研究观察。

**CF / CF2701 套保压力**：席位页选棉花时展示合成权利金曲线，并标注纸面建平仓（时间、品种、条件、权利金来源）；与机构净仓交叉仅作旁证（`desk/cf_option_pressure.py`）。规范见 Notion「CF2701机构席位与资金结构跟踪」。

### 状态评分

「状态评分」页把席位页同一套 signed 评分拆成多 / 空 / 震荡（非负且和为 100），并对当前品种用本地日线拟合三状态高斯 HMM。升贴水优先本地交割月，不足时用 akshare 基差/展期补。

**HMM 多因子 · 组合 · 事件评估**（同一页、综合评估下方）：以 HMM→多/空/震荡为底座，对动量/均值回归/突破/席位/升贴水做分态命中；等权与评分加权因子组合；Path-A 等策略净值按持仓日分态切片。事件因子已接线「动量机构同向」stub，并可经 `external/event_factors_latest.json`（见 `event_factors_latest.example.json`）或 `desk.regime_factor_eval.register_event_factor` 扩展。样本不足不补造。

**事件驱动层**（研究观察，不下单）至少包括：

- **动量跨越** — 动量本身是事件驱动的一种；r20/r60 门槛穿越单独成行，不被同向事件替换
- **席位/机构** — 前 20 净持仓翻向等
- **动量机构同向** — 动量方向（门槛穿越或 20/60 同向已指向）与五家机构净持仓（中信期货、国泰君安、华泰、永安、东证）符号一致，且当日至少一侧有触发；大商所无 `dce-*.json` 时跳过
- **基差极端** — `|主力基差率|≥3%`（贴水偏多、升水偏空）
- 以及方向翻转、席位切换、入选变化

模型板对趋势R2（主轴）、动量、均值回归、HMM（降权）、波动突破、席位资金、升贴水做历史方向命中；综合方向按「评分×乘数」加权（`desk/model_vote_weights.json`）。HMM×R2 联合 OOS 中 A 门控弱于 C=R2，故 HMM 不作硬否决。评分不是未来收益承诺。

## 目录

- `universe.json` — 品种池与资金参数（改这里即可扩品种）  
- `market_data.py` — 新浪、腾讯日线  
- `daily_update.py` — 日信号（免费源不足时才走 iFinD）  
- `weekly_backtest.py` — 基于 `archive/` 滚动纸面 PnL；GitHub 周跑会先 **补全近两周席位**（SHFE/CZCE/DCE/东财）并提交 `.cache/member/`，本地 `git pull` 后席位页曲线更密  

- `historical_backtest.py` — 近一年路径A纸面回测  
- `member_rank.py` — 上期所/郑商所排名 + 大商所 akshare 缓存  
- `basis_data.py` — akshare 展期/现货基差缓存  
- `option_compare.py` — 合成权利金 vs 新浪商品期权链  
- `desk/cf_option_pressure.py` — CF 权利金序列 + 建平仓标注（席位页）  

- `param_sweep.py` — stop×RR（可选门槛）批量纸面扫参  
- `desk/` — Streamlit 研究台（`app.py` + 策略注册表）  
- `notion_sync.py`（signals / backtest / annual / **trades**）/ `ifind_call.py`  
- `MOBILE.md` — 手机端配置说明  
- `.github/workflows/` — 定时 + 手动任务  

## Disclaimer

研究用途，不构成投资建议。请勿把密钥提交进仓库。
