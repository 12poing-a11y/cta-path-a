# 影子审核 2026-11-15（ee4476b 补丁）
只读正式口径；不改 historical_backtest_latest.json，不合 main，不下单。
- replay.py：用 archive/snapshots/bt_input_20261113_d246813d911a.json 离线重放正式回测（与 ee4476b 正式 JSON 逐项一致：+4.992%/3.262%/43笔）。
- variants.py：A=正式；B=全部连续代理(去合约戳)；C=合约缺戳日用"连续+最近基差"前向填充（修复持仓冻结）。
- oos_lookahead.py：截断前视测试（3/31、6/30、8/31、10/15）+ 训练段(≤08-31)选参/测试段(09-01→11-13)成绩，网格 STOP(0.8,1.0,1.2)×RR(1,1.5,2,2.5,3,4)。
- cf_stop_mc.py：CF2701 新浪日K（截至 2026-11-13）ATR14 + 5日自助路径，检查 15200/15300 止损。
结果见 *_result.json。
