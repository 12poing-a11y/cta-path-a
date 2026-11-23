# VP Phase 1A — 用户操作说明

## Desk

1. 启动：`streamlit run desk/app.py`  
2. 打开页面 **「虚拟组合」**  
3. 创建账户（起始资金）→ 入金/出金 → 手工开平（自填次日开盘价与 asof）  
4. 查看权益、持仓、ledger 尾部  

## CLI / Python

```python
from pathlib import Path
from virtual_portfolio import create_account, open_position, close_position, load_account_state

root = Path(".")
create_account(root, "demo", initial_cash=200_000)
open_position(root, "demo", symbol="MA", side="long", qty=1, price=2500, asof="2026-11-24")
print(load_account_state(root, "demo")["equity"])
```

## 注意

- Phase 1A **不能** `source=CTA_SIGNAL`（留给 1B）。  
- 保证金表含研究估计（`verified_at=null`）；`VPTEST` 品种故意无保证金以演示 `MARGIN_DATA_MISSING`。  
- 数据仅在 `data/virtual_portfolio/`；勿当正式 KPI。  
- 不修 paper 异常；不解锁 F2。
