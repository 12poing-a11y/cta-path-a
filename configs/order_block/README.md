# Order block shadow track

Shadow research only. No orders. This track does not change formal Path-A.

Formal paper stays on `execution_rules.json`: stop **ATR×1.2**, reward **1.5R**. The runner does not read that file and does not write `paper_book_latest.json`, `l1_report.json`, `historical_backtest_latest.json`, `benchmark_latest.json`, or any `latest.json`.

An order block here is a location and a stop reference. It is not treated as proven alpha. v1 keeps failed zones and zones that never retest. There is no quality score.

## Definition (v1)

1. A swing high or low is confirmed `swing_right` bars after the pivot (`swing_right >= 1`).
2. Break of structure is a **close** through the latest confirmed swing.
3. The zone is the nearest opposite candle strictly before that break (full high to low).
4. The zone can emit a signal only on a **later** bar that trades into it.
5. A closing break of the far side retires the zone for new signals.
6. The shadow fill is the **next bar's open**. The signal bar's low or high is not a fill.
7. If that same later bar touches both the zone stop and the shadow target, the stop is used.

`shadow_reward_rr` in `baseline.json` sizes only this experiment's target off the zone boundary. Trend, momentum, and ATR are separate and unwired (`trend_filter.json`, `risk_management.json` exit as stubs).

## Run

From the repo root:

```bash
python scripts/order_block_shadow.py --demo
python scripts/order_block_shadow.py --bars path/to/bars.json
python scripts/order_block_shadow.py --code RB
```

`--demo` uses a built-in series and needs no network. `--bars` accepts a JSON list of `{date, open, high, low, close}` or an object with a `bars` array. `--code` calls `market_data.load_free_bars` (Sina/Tencent cache or network).

Outputs go to `data/order_block/shadow/`. Each file records the config, every zone, every retest signal, shadow trades, and stub hooks for ablation and walk-forward. Those hooks are marked `status: stub` and are not results.

```bash
python -m pytest tests/test_order_block.py -q
```

## What this slice does not claim

- No edge versus Path-A, buy-and-hold, or a trend pullback.
- No sample-outside result. Walk-forward is a stub.
- No incremental value. Ablation is a stub.
- Zero commission in the baseline is a control setting, not a reason to promote the track.
- A chart order block is not an observable institutional order.

Promotion, if it is ever considered, starts from the no-lookahead tests in `tests/test_order_block.py`. This slice stops there.
