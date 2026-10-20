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

换月和近月/次月用新浪具体合约日 K（如 `RB2601`）。会员持仓用上期所、郑商所公开排名；大商所没有这份文件时该过滤放行。上面任一公开序列不够，才对那个品种补一次 iFinD。

2025-11-26 至 2026-10-20 的对照里，20/60 现版净收益 +6.75%、净最大回撤 5.50%。换月窗口加 ATR 超过收盘 8% 之后，净收益 −3.84%、净最大回撤 8.22%。升贴水、持仓量、会员持仓、高潮日与板块都没有同时超过现版的净收益和回撤。日报因此用 `entry_filter=base`。回测仍按每边 1 跳滑点，手续费用申银万国 2026-09-02 客户公示价，同时给出毛收益和净收益。

日报已补进席位级联，`entry_filter=seats`。顺序是：跟随机构（中信期货、国泰君安、华泰期货、永安期货、东证期货/东证融汇），其次跟随外资（摩根大通、摩根士丹利、瑞银、高盛），再次站在家人对面（东方财富、平安、方正中期、徽商、中信建投）。公开排名写「中信建投」，按这个名字计入中建投。席位只确认或拦住 20/60 的方向，单边行情不开反向单。大商所没有会员排名时放行。2025-11-27 至 2026-10-20，seats 净收益 +6.22%、净最大回撤 5.04%；同窗 base +6.77%、5.50%。这一年五家机构净持仓每天都有方向，开仓决定落在机构一侧；外资和家人留在机构净持仓为 0 时使用。

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
| `CTA Weekly Backtest` | `0 12 * * 0` | 周日 20:00 |
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
python notion_sync.py signals   # 可选
```

## 目录

- `universe.json` — 品种池与资金参数（改这里即可扩品种）  
- `market_data.py` — 新浪、腾讯日线  
- `daily_update.py` — 日信号（免费源不足时才走 iFinD）  
- `weekly_backtest.py` — 基于 `archive/` 滚动纸面 PnL  
- `historical_backtest.py` — 近一年路径A纸面回测  
- `notion_sync.py` / `ifind_call.py`  
- `MOBILE.md` — 手机端配置说明  
- `.github/workflows/` — 定时 + 手动任务  

## Disclaimer

研究用途，不构成投资建议。请勿把密钥提交进仓库。
