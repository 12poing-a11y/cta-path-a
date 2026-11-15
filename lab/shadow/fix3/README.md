# fix3 影子（2026-11-15，基于 shadow/2026-11-15-patch-audit@c0fb75f）
研究用，不下单；不改 formal latest、不合 main、不改 routine。
- ① 冻结修复（historical_backtest.py，`freeze_fix=True` 默认）：合约成交仓位缺同月合约数据日 → 连续价+最近基差管理（不再跳过，也不用别的月份 OHLC）；
  持仓不得跨交割月（下一交易日进入交割月前按当日收盘强制出场，reason=delivery）；连续 >3 天无同月合约数据 → 强制出场（reason=freeze）；
  盯市改为按上次盯市价连续计（缺数日不丢 PnL）。`freeze_fix=False, min_seat_days=0` 复现 ee4476b（+4.992%/3.262%/43）。
- 席位门槛：载入席位历史 <60 个交易日的品种不进正式席位过滤（`min_seat_days=60`）。
- ② 周度跑批口径锁：research/execution/rule_lock.py + configs/formal_rule_lock.json（execution_rules.json 按 LF 归一化 sha=77999d44…，fill_series=mixed）。
- ③ CI 门禁：tests/test_freeze_fix_gates.py（截断前视 4 切点、锁定样本外/PBO/排名相关）、tests/test_rule_lock.py。
- 结果：recompute_result.json、oos_gate_result.json、seat_backfill_result.json（快照 bt_input_20261113_d246813d911a）。
