# cta-path-a

中国商品期货 **CTA 路径A** 纸面验证 + **Streamlit 研究台**（只记账、不下单）。

属于 [@12poing-a11y](https://github.com/12poing-a11y) 的量化研究档案。

## 现在是什么

| 层 | 作用 |
|----|------|
| **Path-A 引擎** | 20/60 同向 + ATR 仓位 + 席位确认；日报 / 周回测 / 一年回测；可选写 Notion |
| **研究台 `desk/`** | 最终信号、多策略净值、技术形态、决策、图表、席位、情绪、期权/Gamma、套利观察 |
| **本地代理** | `proxy_cta.py`：CWFT / Long-Short CWFT / frontnext_st；另有 **观察袖套·F+短动量**（消融冻结版，影子对照，建议≤权益 10%，不进 `paper_book`） |
| **GitHub Actions** | 工作日 15:30 日报、周六周回测、周日/手动历史回测；本机 `git pull` 即可同步缓存 |

研究用途，不构成投资建议。密钥勿提交进仓库。

## 策略规则（Path-A / L1）

1. **信号**：主力近 20 日与近 60 日收益同向 → 顺势；否则空仓  
2. **仓位**：`lots = floor(风险预算 / (ATR14 × 合约乘数))`  
3. **组合上限**：最多 **3** 个品种；总名义敞口 ≤ 权益 **50%**（`position_rules.apply_portfolio_caps`）  
4. **参数**：`universe.json`（Equity ¥20万 / 风险% / `max_positions` / `max_gross_exposure_pct`）  
5. **入场**：现行 `entry_filter=seats`（机构 → 外资 → 家人对面；席位只确认/拦住 20/60，不开反向）  
6. **执行**：`execution_rules.json` + `universe.json → selection`（正式 SSOT：止损 **0.8×ATR** / 止盈 **2R**；历史档位见 `execution_rules.archived_params`，含曾用 1.2×ATR/1.5R）
7. **正式回测成交**：T 日收盘算信号，**T+1 开盘成交**（`fill_price=next_open`）；席位/升贴水可用性滞后 1 个交易日。周度 KPI 与历史回测共用同一 `simulate` 引擎（含止损止盈与成本）。报告须标明配置版本（`execution_rules` sha + Git commit），见 `research.data_quality.config_version_stamp`。
8. **研究升级**：数据有效性 / 可交易性双掩码与 Base·Stress·Extreme 成本情景见 `docs/UPGRADE_PLAN.md`（Research/Shadow 不得未经批准改正式参数）。

正式 KPI 以 `historical_backtest_latest.json`（`schema_version=cta-backtest-v11-next-open`）为准。当前 seats / next_open 样本（约 2025-12-17→2026-11-10）：净约 **+2.25%**、净回撤约 **5.57%**、成本约 5880（毛约 +5.19%）。旧对照窗数字（**收盘成交 close**）：base 净约 +6.7%/回撤约 5.5%，seats 约 +6.2%/5.0%；`universe.notes` 另记 close 口径约 +10.09%/4.86%——**仅历史对照，不作正式成绩**。成本：每边 1 跳滑点 + 申万公示手续费（毛/净并列）。

旁路（不改 ATR、不切 `entry_filter`）：升贴水极端、多维波动观望、实验室 Gate / 软信号。详见下文与 `lab/README.md`。

## 行情来源

日线：**新浪 + 腾讯**合并（同日新浪覆盖腾讯）。不足 80 根、缺 OHLC、或最后交易日过旧时，才用 **iFinD** 主力连续补缺（重叠日仍以免费源为准）。

具体合约 / 换月 / 近次月：新浪合约日 K；缺口可再走 **扶摇 Fuyao**、**天勤 TqSdk**（可选 Secrets / 本地 `.env`，无 Key 则跳过、不拖垮日更）。

会员持仓：**东财 → 新浪补缺**（`.cache/member/`）；上期/郑商 txt、DCE zip 为辅。席位标签用机构席（`_INST`），不用家人席冒充。

新浪连续：`InnerFuturesNewService.getDailyKLine`，代码 `{品种}0`。`hq.sinajs.cn` 实时字段不改写日线 OHLC。

## 研究台（Streamlit）

```bash
pip install -r requirements-desk.txt
streamlit run desk/app.py
```

页序（仅渲染当前页）：**最终信号** → 概览对比 → 技术分析 → 决策 → 图表 → 日信号 → 状态评分 → 席位板块 → 情绪 → E1 影子 → 期权机会 → 套利观察 → Gamma 结构。

概览对比含：策略健康 / 窗口 KPI（中文表头）、多策略净值与回撤叠加、**本地代理·模拟持仓**（品种列统一为「甲醇MA2701」式名称+期号）、**策略×指标消融**表（`scripts/strategy_indicator_ablation.py` → `data/ablation/`）。

侧栏「同步日报」：`git pull` 拿 Actions 落库；可选本机重跑 `daily_update.py`。同步后滚 `paper_book_latest.json`（或 `python paper_book.py`）。

### 本地代理与观察袖套

```bash
python proxy_cta.py
```

写入 `external/strategies/proxy_*.json` + `desk/strategies/extra/`。每条代理自带 `final_positions` / `trade_log`（研究模拟，**与 Path-A `paper_book` 分离**）。

| id | 说明 |
|----|------|
| `proxy_cwft` | 本地代理·CWFT |
| `proxy_long_short_cwft` | 本地代理·Long/Short CWFT |
| `proxy_frontnext_st` | 本地代理·C_frontnext&ShortTrend |
| `proxy_observe_f_short_mom` | **观察袖套·F+短动量**：`ablate={C,LONG_MOM}`，样本内网格冒尖故仅影子跟踪，建议帽 ≤10% 权益 |

东证周报 KPI 不能稳定自动抓取，研究台不再挂「东证·…」实盘条；归档见 `external/archive/`。

### 如何挂新策略

1. 产出含 `equity_curve`（及可选 KPI）的 JSON  
2. `desk/strategies/extra/<id>.json` 指向该文件  
3. 重启 Streamlit，侧栏多选叠加  

内置：`path_a`、`benchmark`、`path_a_opt_hedge`、`wyckoff`（可占位）、`param_sweep` 等。扫参：`python param_sweep.py`。

## 自动化（GitHub Actions）

| Workflow | Cron (UTC) | 北京时间 |
|----------|------------|----------|
| `CTA Daily 15:30 CST` | `30 7 * * 1-5` | 工作日 15:30 |
| `CTA Weekly Backtest` | `0 1 * * 6` | 周六 09:00 |
| `CTA Historical Backtest` | `0 13 * * 0` + 手动 | 周日 21:00 / 随时 Run |
| Gamma 日采（可选） | 见 `.github/workflows/gamma_wall_daily.yml` | AkShare 郑商所结算 IV；未配 `GAMMA_*_EXPIRY` 的品种跳过 |

手机：GitHub App → Actions → Run workflow。配置见 [`MOBILE.md`](./MOBILE.md)。

日报通常提交：`l1_report.json` / `archive/`、`.cache/member/`、`.cache/sina/<日>/{CODE}0.json`、分钟 `.cache/akshare/minute/`（15m/60m）。

## Secrets / 本地环境

| 名称 | 用途 |
|------|------|
| `IFIND_AUTH_TOKEN` / `_BACKUP` | 免费源不足时补日线；启动始终优先 primary |
| `NOTION_TOKEN` | 可选：信号/流水/年报写入 Notion |
| `FUYAO_API_KEY` | 可选：合约日线补洞 |
| `TQ_USER` / `TQ_PASS` | 可选：天勤补洞 / 期权链研究备份 |

本地可复制 `.env.example` → `.env.tqsdk` / `.env.fuyao`（已 gitignore）。CI 无扶摇/天勤 Key 时跳过对应补洞，不失败。

`IFIND_ACTIVE_SLOT` 默认 `primary`；`IFIND_PERSIST_FAILOVER=1` 才把 failover 写回本地 `mcp_config.json`。

## 本地 / CI 命令

```bash
pip install -r requirements.txt
# 本地：mcp_config.example.json → mcp_config.json（iFinD）
python daily_update.py
python weekly_backtest.py
python notion_sync.py signals   # 日信号台账
python notion_sync.py trades    # 建平仓流水 + 规则/统计
python notion_sync.py annual    # 一年回测并顺带 trades
python proxy_cta.py             # 本地代理 + 观察袖套曲线/持仓
python scripts/strategy_indicator_ablation.py   # 策略×指标消融网格
```

平仓原因码：`target` 止盈 / `stop` 止损 / `signal` 趋势失效。

CI 跑 desk 相关测试时安装 `requirements-desk.txt`（streamlit/plotly），与核心 `requirements.txt` 分开。

## 研究旁路与实验室（摘要）

- **升贴水**（`carry_bypass`）：默认 `|近次月 gap|≥1%` 时升水禁开多、贴水禁开空；缺数不拦  
- **多维波动**（`vol_factor_combo.py`）：短/长比过高 → 决策观望  
- **Plan A 因子实验室**（`lab/`）：IC/OOS 与 Path-A 对照；Gate 未过不改 `entry_filter` — 见 `lab/README.md`  
- **股指择时**：`equity_timing.py` → 综合评估计分；与商品池分离  
- **期权 / Gamma**：合成 ATR 权利金 + 新浪链对照；Gamma 墙优先 AkShare 郑商所结算 IV  

## 目录要点

- `universe.json` / `execution_rules.json` — 品种池与执行 SSOT  
- `daily_update.py` / `weekly_backtest.py` / `historical_backtest.py`  
- `market_data.py` / `member_rank.py` / `basis_data.py` / `tqsdk_client.py`  
- `proxy_cta.py` / `desk/` / `paper_book.py`  
- `notion_sync.py` / `.github/workflows/` / `MOBILE.md`  
- `external/` — 代理曲线、东证归档、知识卡、股指择时产物  
- `data/ablation/` — 消融快照（本地/研究生成）  

## Disclaimer

研究用途，不构成投资建议。请勿把密钥提交进仓库。
