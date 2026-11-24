# R5b 第 0 步：模拟账本（refresh_paper_book）与回测（simulate）的差异清单

基线：R5a（42cb2e9）。旧路径 = `paper_book.refresh_paper_book`（根目录 `paper_book_latest.json` 仍是这个格式）；
新路径 = R5b 引擎账本（`"engine": "R5b"`），持仓管理和 T+1 开仓与 simulate 共用 `book_core.PositionEngine`。

## 1. 差异表

| # | 项目 | simulate（回测） | 旧 refresh_paper_book | R5b 引擎账本 |
|---|---|---|---|---|
| 1 | 入场价基准 | T 日收盘出信号，T+1 开盘成交（`next_open_fill`；有合约开盘价用合约价），止损/止盈按同一距离平移 | T 日信号收盘价直接记为入场价，`entry_date` = 信号日 | 同回测：T 日写 pending，T+1 开盘成交并平移止损/止盈 |
| 2 | 入场当天管理 | 成交当天就用当天 K 线管理（可当天止损/止盈） | `entry_date == asof` 跳过盘中检查 | 去掉跳过保护；先成交 pending，再管理全部持仓（含刚成交的） |
| 3 | 分钟线 + 日线兜底 | 15m 首次触及（需 `minute_bars_match_daily` + 与入场价对齐）；分钟缺失/不符 → 按日线高低价 `apply_stop_target` | 只看 15m；分钟缺失、与日线不符、或本地 CODE0 历史缺当天 → 直接"不平仓"，没有日线兜底 | 同回测（共用代码） |
| 4 | 交易日/日线来源 | 本次运行的 bars（hist） | `.cache/history/{CODE}0.json`（CODE0 历史缓存）取交易日列表和当天日线 | 本次运行的 bars |
| 5 | 跳空止损 | R6b：换月开盘先检查旧合约开盘是否跳空穿止损（`roll_open_gaps_through_stop`） | 无 | 同回测 |
| 6 | R6a/b 换月与 held_contract | 主力切换后按持有合约真实 K 线计价；收盘后排 `pending_roll`，次日开盘换月（两笔成交成本） | 无（连续合约价，不换月） | 同回测；持仓带 `held_contract` / `pending_roll` / `roll_events` |
| 7 | 信号失效平仓 | 收盘时 r20/r60 用复权（roll-free）序列判断同向是否失效，按管理 K 线收盘价平仓 | 用日报行的 r20/r60/方向启发式（`_should_exit`），按日报收盘价平仓 | 同回测 |
| 8 | 交割与冻结 | freeze_fix：合约成交进入交割月前平仓（delivery）、连续无价超过 `MAX_STALE_DAYS` 平仓（freeze） | 无 | 同回测 |
| 9 | 成本 | 每笔成交扣 `fill_cost`（手续费 + 滑点 tick；换月两笔） | 不扣任何成本 | 同回测 |
| 10 | 权益口径 | 逐日盯市，扣成本；入场成本记在信号日 | `equity` = 只加已实现盈亏（不扣成本）；`equity_mark` = equity + 浮动 | `equity_mtm`/`equity_mark` = 逐日盯市扣成本；入场成本在 T+1 成交时扣（与回测相差未成交 pending 的入场成本，见对账）；`equity` = 已实现 = equity_mtm − 浮动（保持旧读者语义） |
| 11 | 新仓手数用哪个权益 | `compound_equity(前一日回测权益)` | 日报用 `equity_state.json` 的 live 权益（`_load_live_equity`）复利 | 账本自己的权益：当天成交后、当天盈亏前的权益（= 回测的前一日权益口径） |
| 12 | 组合上限时点 | 先平当天该平的，再用剩余持仓算 gross/ATR 风险/板块/数量上限（R4/R4b，持仓用复权 ATR、持有合约收盘价） | 日报先于账本刷新：held = 上次账本持仓（含当天可能平掉的仓，偏保守），用日报行的收盘价/ATR；账本里再用 `caps_book_check` 复核 | 同回测：先 roll（成交 + 管理 + 平仓），再用剩余持仓算上限，生成 pending |
| 13 | observe min_lots | 回测配置 min_lots = 0 | 日报对 observe 袖套抬到 `OBSERVE_MIN_LOTS`（1 手） | 保留为参数（日报仍抬 1 手）；对账测试用 0 |
| 14 | 停牌/缺当天 K 线 | 当天无 K 线：不管理，`stale_days+1` | 跳过 | 同回测 |
| 15 | 漏跑的交易日 | 不存在（逐日循环） | 只看 asof 当天，漏跑的日子永远不检查 | 逐日补管理漏掉的交易日；只在最后一天生成新 pending（漏跑日的信号不补，记入 notes） |
| 16 | 同日重跑 | 不适用 | 同 asof + 同日报指纹 → no-op | 账本存 `base`（当天前状态），重跑从 base 重算；结果指纹相同 → no-op（已测） |
| 17 | 合约成交覆盖 | `prepare_pack_for_execution`（交割日历 + 合约 OHLC 覆盖，仅缓存） | 日报没有调用（R5a 遗留缺口） | 引擎账本路径在日报里调用（仅本地缓存） |
| 18 | roll_carry 入场分支（mode=roll） | 有 | 无 | 未接入（当前 entry_filter=seats 不触发） |
| 19 | 下一交易日（交割检查用） | 回测日期轴的下一天 | 不适用 | 日报：已覆盖日期的下一天，最后一天用工作日日历（不含节假日）近似 |

## 2. `paper_book_latest.json` 的下游读者

| 读者 | 位置 | 用到的字段 |
|---|---|---|
| `daily_update.py` | `_load_paper_held` → `_apply_caps`；`refresh_paper_book` 返回值 | 顶层 `ok, positions`；持仓 `bucket, lots, mult, mark→entry, atr`；返回 `ok, asof, held_n, opened_n, closed_n, error` |
| `paper_book.py`（自读） | `_seed_positions`、`refresh_paper_book`、`load_paper_positions` | `ok, positions, trade_ledger, parent_backtest_end, batch, asof(_ymd), l1_fingerprint, equity`；`load_paper_positions` 只透传白名单字段 |
| `desk/equity_book.py` | `load_book_equity` | `ok, equity, equity_floating, equity_mark, asof, held_n, positions`；`mark = equity_mark or equity+floating` |
| `desk/app.py` | 权益卡片 + 刷新按钮 | `equity_mark, equity_floating, equity, source, asof`；文案写死"已实现 equity·浮动·盯市 equity_mark" |
| `desk/composite_eval.py` | 账本评分 | `equity, equity_mark`：`ret = equity_mark/equity − 1` |
| `desk/decision.py` | 路径 A 账本页 | 经 `load_paper_positions`：`end, source, positions(direction, lots, entry, reason, stop, target, equity_delta)`, `trade_ledger(date, event, direction, lots, entry, exit, stop, target, tp_sl_scheme, strategy, entry_reason, reason, R, equity_delta, equity_after, code)` |
| `desk/final_signal.py` | 止盈止损预警 | `positions(direction, lots, mark, stop, target, atr, entry, equity_delta, exit_condition, stop_atr_mult)`, `end/asof` |
| `desk/blend_positions.py` | 混合持仓 | `asof/end, source, positions(direction, lots, code, name, mark, mult, entry_date, entry)` |
| `desk/options_panel.py` | 期权面板 | `positions(direction, lots, entry, stop, target, entry_date, name, atr, mult)` |
| `desk/vol_engine_panel.py` | 波动率面板预警 | 原始 JSON `positions(mark, stop, target, direction)` |
| `desk/sentiment_panel.py` | 情绪面板 | 原始 JSON `positions(direction)` |
| `desk/sync_desk.py` | 本地同步 | `asof/asof_ymd, ok, positions` 数量；比较 paper asof 与 l1 asof |
| `notion_sync.py` | Notion 持仓/交易表 | 经 `load_paper_positions`：`positions(...)`, `trade_ledger`（只同步 建仓/平仓）, `closed_today`；`paper.get("equity")`（白名单不含，恒为 None） |
| `weekly_backtest.py` | `_paper_book_equity` | 读 `equity`（同样拿不到，死代码） |
| CI `.github/workflows/daily.yml` | 只 `git add paper_book_latest.json`；先跑全量 pytest | 无字段 |
| VP（`virtual_portfolio/*`）、`signals/*_eval.py` | 只把文件名列入禁写名单 | 无字段 |

测试夹具：`test_paper_book_idempotent.py`（含"入场当天跳过盘中检查"）、`test_desk_local_sync.py`、`test_options_panel_variety.py`、`test_final_signal.py`、`test_blend_positions.py`、`test_proxy_positions.py`（读真实根账本，断言 positions 里不含 "proxy" 字样）等。

## 3. 兼容性（R5b 只加字段）

- 顶层新增：`engine, pending, pending_n, equity_mtm, equity_realized, sizing_equity, plan, base, today_trade_ids, days_rolled, state_fingerprint`。旧字段全部保留，`equity`/`equity_floating`/`equity_mark` 维持"已实现 / 浮动 / 盯市"的旧语义（equity_mark = equity + floating）。
- 持仓新增：`fill_price_basis, fill_contract, held_contract, last_mark, stale_days, pending_roll, roll_events, entry_orig, mark_from, signal_date, pnl_net`；`mark`、`mult`、`equity_delta`（= 净浮动盈亏）、`exit_condition` 继续填写。
- 账本行新增：`signal_date, fill_price_basis, fill_contract, held_contract, entry_cost, roll_events, engine, tag(backfill_R5)`。
- `load_paper_positions` 额外透传 `engine`、`pending`（只加键）。

不兼容 / 需要 R7 处理的点：

1. `tests/test_proxy_positions.py` 断言根账本 positions 里没有 "proxy" 子串；R5b 持仓的 `fill_price_basis = "continuous_proxy"` 会让它失败——R7 正式写入根账本前要改这条断言（或改字段值）。本刀不写根账本，测试仍绿。
2. `test_paper_book_idempotent.py::test_entry_day_skips_intraday` 固定了旧语义"入场当天不检查"；R5b 引擎账本不再跳过，但旧路径（旧格式账本）仍保留该行为，测试不改。
3. `entry_date` 在 R5b 里是 T+1 成交日（旧账本是信号日）；Notion 建仓行的日期随之变成成交日。
4. Notion 交易表同步对 trade_ledger 不设上限：R7 若采用方案 A，`backfill_R5` 的 2 条平仓行会补推到 Notion（属预期）；方案 B 另起账本则不会。
5. 旧格式账本的 `refresh_paper_book` 遇到 R5b 账本会拒绝运行（返回 ok=False），防止旧逻辑改写引擎账本。
6. 日报在旧格式根账本下仍走旧顺序（日报先于账本刷新、held 偏保守），直到 R7 把根账本换成 R5b 格式；换格式后日报自动走引擎路径（selected == pending）。
