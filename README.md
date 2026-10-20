# cta-path-a

中国商品期货 **CTA 路径A** 自动验证台（纸面记账，不下单）。

属于 [@12poing-a11y](https://github.com/12poing-a11y) 的量化研究档案。

## 策略规则（L1）

1. **信号**：主力合约近 20 日收益与近 60 日收益同向 → 顺势；否则空仓  
2. **仓位**：`lots = floor(风险预算 / (ATR14 × 合约乘数))`  
3. **参数**：Equity ¥200,000；单品种风险 1.5%（¥3,000）；品种池 JD / JM / CF / SR / RU / MA  
4. **路径A**：只记账、不自动下单；用于规则与执行纪律验证

## 自动化

| Workflow | Cron (UTC) | 北京时间 |
|----------|------------|----------|
| `CTA Daily 15:30 CST` | `30 7 * * 1-5` | 工作日 15:30 |
| `CTA Weekly Backtest` | `0 12 * * 0` | 周日 20:00 |

手机：GitHub App → **Actions** → **Run workflow**。

可选写入 Notion 日信号库 / 回测库（需 `NOTION_TOKEN` + 页面授权）。

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

- `daily_update.py` — 拉行情、算信号、落盘 `l1_report_risk15.json`  
- `weekly_backtest.py` — 基于 `archive/` 的纸面 PnL  
- `notion_sync.py` — 官方 Notion API 同步  
- `ifind_call.py` — iFinD MCP HTTP 客户端（支持 primary/backup Key）  
- `.github/workflows/` — 定时任务  

## Disclaimer

研究用途，不构成投资建议。请勿把密钥提交进仓库。
