# CF0 daily price snapshot (2021-11-12 to 2026-11-11)

- Source file in repository main: `.cache/history/CF0.json`
- Source blob SHA: `62d8c24ecb29eb02072791e95bcf32c750e26300`
- Snapshot generated: 2026-11-12
- Requested window: 2021-11-12 through 2026-11-12 (inclusive)
- Rows in source window: 1215
- Rows retained: 1209
- Rows excluded: 6 (weekend placeholder rows with missing OHLC; no price values imputed)
- First retained session: 2021-11-12
- Last retained session: 2026-11-11
- Duplicate dates in source window: 0
- Missing volume among retained rows: 0
- Missing open interest among retained rows: 1

## Important limitations

This is the repository's Sina-derived `CF0` main-continuous series snapshot. The continuous-series roll construction / adjustment methodology has not yet been independently audited. It is suitable as a preliminary historical price-reaction series, but **not yet approved as an executable-contract return series**. Contract-roll jumps must be identified and controlled before interpreting event-study returns as tradable P&L.

No ICE series is included in this file. No news events or event scores are included. Do not infer a five-year news/price backtest result from this price file alone.
