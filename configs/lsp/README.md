# LSP shadow track（流动性扫荡 × 筹码峰近似）

研究影子轨。不下单。不改 Path-A / `paper_book` / `entry_filter`。

## v1 定义

1. 在 bar `i` 用此前 `lookback` 根 K 的 typical price × volume 做直方图 → POC / VAH / VAL。  
2. **扫高收回**：`high > VAH` 且 `close < VAH` → 做空信号。  
3. **扫低收回**：`low < VAL` 且 `close > VAL` → 做多信号。  
4. 成交：下一根开盘；止损用刺穿极值；目标 `shadow_reward_rr` × 风险。  

先做 **日线 + 60 分钟**。15m / 1m MSS / Delta 未接入。

## 运行

```bash
python scripts/lsp_shadow.py --demo
python scripts/lsp_shadow.py --code CF --tf daily
python scripts/lsp_shadow.py --code CF --tf 60
python scripts/lsp_shadow.py --code CF --tf both
```

产物：`data/lsp/shadow/`。
