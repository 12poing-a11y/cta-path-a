# Cotton NPD — News-Price Divergence

## Purpose

NPD is an independent, research-only event-study module for Zhengzhou cotton (CF) with ICE cotton as a later cross-market extension. It measures whether the market's subsequent price path agrees with a timestamped, signed fundamental/news event. It does not modify Path-A entries, position sizing, or paper-book accounting.

## Important timing rule

Every event is entered at the first available trading session **strictly after its China Standard Time publication calendar date**, at that session's OPEN. This intentionally conservative rule avoids pretending that an event published after the close (or at an unknown intraday time) was tradable earlier that day. The reported 1/3/5/10/20-session returns end at the corresponding session CLOSE.

The event-study divergence label is an outcome label, not a signal that can be known at entry. For example, a positive event followed by a negative forward return is counted as a positive-news/negative-price divergence. Do not use that future label as an input feature.

## Input files

### Daily bars CSV

Required columns: `date,open,close`; optional: `volume,oi`.

- Use a consistent, documented CF main-continuous series for broad history.
- Keep exact delivery-contract data separate; do not splice delivery contracts without a roll methodology.
- Preserve source, contract/continuous basis, adjustment method, and raw cache provenance in the upstream dataset.
- ICE data should be stored as a separate series and aligned by its own trading calendar before cross-market analysis.

### Event CSV

Required columns: `event_id,published_at,score`; recommended: `category,headline,source`.

- `published_at`: ISO-8601 timestamp. If timezone is absent, China Standard Time is assumed.
- `score`: signed integer from -3 to +3; positive = bullish cotton fundamental surprise, negative = bearish, zero = neutral/unscored.
- Score the *surprise versus prevailing expectations*, not merely whether the headline sounds bullish or bearish.
- Keep source URL, original publication time, ingestion time, event family, affected geography, expected duration, and confidence in the source master even if they are not all included in this first CSV interface.
- Deduplicate syndicated copies and revisions; a USDA/WASDE revision is a new event only when it changes information available to the market.

## Run

```bash
python cotton_npd.py --bars data/cotton/cf_daily.csv --events data/cotton/cotton_events.csv --output data/cotton_npd --round-trip-cost-bps 8
```

The 8 bps above is an example only, not an asserted CF execution cost. Replace it with a measured fee + slippage assumption. The default is zero and must be treated as gross-like, not executable net performance.

Outputs:
- `cotton_npd_events.csv`: event-level pre-event context, forward returns, directional/contrarian paper returns, and divergence labels.
- `cotton_npd_summary.json`: aggregate and per-year event statistics.

## Research stages

1. **Data audit first:** collect 2021-11-12 through 2026-11-12 daily CF and ICE bars; report missing sessions, duplicate dates, contract roll gaps, source and adjustment provenance.
2. **Event master:** collect timestamped, source-linked events from USDA/WASDE, USDA Crop Progress, ICE/CFTC positioning, China Cotton Association, China Cotton Information Center, customs/trade releases, weather agencies, reserve/auction notices, mill orders and inventory reports.
3. **Point-in-time scoring:** score surprise and confidence with a written rubric. Preserve original text and publication timestamps. Do not backfill an event timestamp from a later recap.
4. **Event study:** calculate pre-event 5/10-session returns, post-event 1/3/5/10/20-session returns, divergence rates, directional and contrarian outcomes.
5. **Controls:** stratify by category, score strength, prior trend, volatility regime, inventory/season, CF-ICE spread, and event clustering. Cluster multiple headlines describing the same underlying information.
6. **Validation:** chronological train/test split, walk-forward checks, bootstrap confidence intervals, overlapping-event controls, realistic fees/slippage and roll costs. Report annual stability and sample counts; do not optimize thresholds on the full five-year sample.
7. **Integration:** shadow output only in daily cotton research report after data-quality gates pass. No Path-A formal signal or position changes until separately validated and approved.

## Current limitations

This initial engine is a deterministic CSV-based event-study core. It does **not** scrape historical news, authenticate the source timestamps, download historical bars, infer event scores, or claim five-year results. Those are separate data acquisition and point-in-time labeling tasks. A five-year win rate must not be published until both event and price coverage are audited.
