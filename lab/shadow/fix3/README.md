# fix3 影子（2026-11-15，基于 shadow/2026-11-15-patch-audit@c0fb75f）
研究用，不下单；不改 formal latest、不合 main、不改 routine。
- ① 冻结修复（historical_backtest.py，`freeze_fix=True` 默认）：合约成交仓位缺同月合约数据日 → 连续价+最近基差管理（不再跳过，也不用别的月份 OHLC）；
  持仓不得跨交割月（下一交易日进入交割月前按当日收盘强制出场，reason=delivery）；连续 >3 天无同月合约数据 → 强制出场（reason=freeze）；
  盯市改为按上次盯市价连续计（缺数日不丢 PnL）。`freeze_fix=False, min_seat_days=0` 复现 ee4476b（+4.992%/3.262%/43）。
- 席位门槛：载入席位历史 <60 个交易日的品种不进正式席位过滤（`min_seat_days=60`）。
- ② 周度跑批口径锁：research/execution/rule_lock.py + configs/formal_rule_lock.json（execution_rules.json 按 LF 归一化 sha=77999d44…，fill_series=mixed）。
- ③ CI 门禁：tests/test_freeze_fix_gates.py（截断前视 4 切点、锁定样本外/PBO/排名相关）、tests/test_rule_lock.py。
- 结果：recompute_result.json、oos_gate_result.json、seat_backfill_result.json（快照 bt_input_20261113_d246813d911a）。

## fix3-opt（2026-11-15，基于 main a570d53 期权升级）
- 席位补数改按**当日历史主力**（Sina 日线持仓量最大，候选=当月起 12 个月合约）选合约：`member_rank.historical_main_contract` / `fetch_dce_member_day_historical`；
  来源顺序：大商所官网（memberDealPosiQuotes HTTP 500，不可用）→ 东财（仅仍挂牌合约）→ 新浪；每行记 source/contract/contract_rule。
  06-05、07-13、07-17、07-31 四天两源均无数据：已删除旧的「今日主力」行（按缺席位处理，待核）。日志 dce_seat_hist_log.json。
- 席位门槛改为 as-of-T：T 日经 lag 可见的累计席位交易日 ≥60 才启用；截断前视同步截断席位（oos_gate.lookahead）。
- 开仓交割月拦截：合约成交日距交割月首日 <10 个交易日时，不用该合约成交，改用连续主力（ENTRY_DELIVERY_ACTION="proxy"，可选 "block"）。
- historical_backtest.py 写正式结果前：check_rules + check_fill_series + check_clean，失败返回 2、不写。
- 结果：recompute_result.json（快照席位）、seat_backfill_result.json（H 口径）、oos_gate_result.json / oos_gate_backfill_result.json。
- 脆弱：fd5dd04 的 +3.4pp 来自 2 笔交割强平后的路径变化（小N核）；加入场拦截后该部分消失/改变，结果对路径高度敏感。
