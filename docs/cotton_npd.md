# Cotton NPD — News-Price Divergence

## Purpose

NPD is an independent, research-only event-study module for Zhengzhou cotton (CF) with ICE cotton as a later cross-market extension. It measures whether the market's subsequent price path agrees with a timestamped, signed fundamental/news event. It does not modify Path-A entries, position sizing, or paper-book accounting.

Desk integration is **entry-day shadow reminder only** (`E1·NPD影子·不计分`).

## China watchlist (六类)

Only these Chinese categories are treated as the core CN focus set:

| category | 含义 |
|---|---|
| `CN_RESERVE` | 国储棉轮入、轮出的公告和成交结果 |
| `CN_SLIDING_QUOTA` | 棉花进口滑准税配额的发放 |
| `CN_CASDE` | 农业农村部每月《农产品供需形势分析》（CASDE） |
| `CN_NBS_OUTPUT` | 国家统计局棉花产量公告 |
| `CN_XJ_TARGET_PRICE` | 新疆棉目标价格等政策公告 |
| `CN_CUSTOMS_IMPORT` | 海关棉花进口月度数据 |

USDA side uses `USDA_WASDE` / `USDA_CROP_PROGRESS` / `USDA_OTHER`.

## Provenance gate（收表规则）

每条事件**同时**具备以下三项才标 `accepted` 并进入敏感性统计：

1. **官方原文链接**（`official_url`，http/https）
2. **官方原文摘录**（`official_excerpt`，不少于约一句）
3. **可解析发布时间**（`published_at`，ISO-8601；缺时区按北京时间）

缺任一字段 → `status=待核`，可留在表里备查，**不进**中国 / USDA / 合并统计，也**不触发**进入日影子提醒。

## Important timing rule

Every **accepted** event is entered at the first available trading session **strictly after its China Standard Time publication calendar date**, at that session's OPEN. This intentionally conservative rule avoids pretending that an event published after the close (or at an unknown intraday time) was tradable earlier that day. The reported 1/3/5/10/20-session returns end at the corresponding session CLOSE.

The event-study divergence label is an outcome label, not a signal that can be known at entry. Do not use that future label as an input feature.

## Input files

### Daily bars CSV

Required columns: `date,open,close`; optional: `volume,oi`.

Desk loader also merges `.cache/history/CF0.json` and recent `.cache/sina/*/CF0.json`.

### Event CSV

Columns:

`event_id,published_at,family,category,headline,score,official_url,official_excerpt,status`

- `family`: `CN` or `USDA` (optional if `category` already uses `CN_*` / `USDA_*`)
- `score`: −3…+3；0 = 中性，不进方向统计
- `status`: 可显式写 `待核`；否则由引擎按出处规则自动判定

## Run

```bash
python cotton_npd.py --bars data/cotton/cf0_daily_20211112_20261111.csv --events data/cotton/cotton_events.csv --output data/cotton_npd --round-trip-cost-bps 8
```

Outputs:

- `cotton_npd_events.csv` — event-level rows（含 status / family）
- `cotton_npd_summary.json` — **分开**列出：
  - `by_family.CN` 中国事件
  - `by_family.USDA` USDA 事件
  - `by_family.combined` 两者合并  
  便于直接比较郑棉对哪边消息更敏感（看各期限 `news_direction_win_rate` / `directional_mean` / `n`）。

## Research stages

1. Data audit for CF (and later ICE) bars.
2. Fill the six CN categories + USDA from **official** releases only.
3. Point-in-time scoring of surprise (−3…+3).
4. Event study with CN / USDA / combined blocks.
5. Controls (category, score strength, prior trend, vol regime, clustering).
6. Walk-forward validation — do not optimize on the full sample.
7. Desk: shadow entry-day reminder only until separately approved.

## Current limitations

The engine does **not** scrape news or invent timestamps. A five-year win rate must not be published until event coverage and continuous-contract rolls are audited.
