# cta-path-a

中国商品期货 **CTA 路径A** 自动验证台（纸面记账，不下单）。

属于 [@12poing-a11y](https://github.com/12poing-a11y) 的量化研究档案。

## 策略规则（L1）

1. **信号**：主力合约近 20 日收益与近 60 日收益同向 → 顺势；否则空仓  
2. **仓位**：`lots = floor(风险预算 / (ATR14 × 合约乘数))`  
3. **参数**：见 `universe.json`（Equity / 风险% / 多板块品种池）  
4. **路径A**：只记账、不自动下单；用于规则与执行纪律验证

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
- `daily_update.py` — 日信号  
- `weekly_backtest.py` — 基于 `archive/` 滚动纸面 PnL  
- `historical_backtest.py` — 拉近约 120 日行情做路径A历史回测  
- `notion_sync.py` / `ifind_call.py`  
- `MOBILE.md` — 手机端配置说明  
- `.github/workflows/` — 定时 + 手动任务  

## Disclaimer

研究用途，不构成投资建议。请勿把密钥提交进仓库。
