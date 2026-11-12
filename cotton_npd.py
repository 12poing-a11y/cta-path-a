# -*- coding: utf-8 -*-
"""Cotton News-Price Divergence (NPD) event-study engine.

Research-only. It never fetches or fabricates news/prices and never places orders.
Events are entered at the next available session OPEN to avoid same-day look-ahead.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
HORIZONS = (1, 3, 5, 10, 20)


def _parse_datetime(value: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def _finite_positive(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}:{value}") from exc
    if number <= 0:
        raise ValueError(f"non_positive_{field}:{value}")
    return number


def load_bars(path: str | Path) -> list[dict]:
    """Load daily futures bars CSV: date,open,close[,volume,oi]."""
    rows: list[dict] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line, raw in enumerate(csv.DictReader(handle), start=2):
            day = date.fromisoformat(str(raw.get("date", ""))[:10])
            row = {
                "date": day,
                "open": _finite_positive(raw.get("open"), "open"),
                "close": _finite_positive(raw.get("close"), "close"),
                "volume": raw.get("volume") or None,
                "oi": raw.get("oi") or raw.get("open_interest") or None,
            }
            rows.append(row)
    rows.sort(key=lambda item: item["date"])
    if len({row["date"] for row in rows}) != len(rows):
        raise ValueError("duplicate_bar_date")
    if len(rows) < 25:
        raise ValueError("insufficient_bars_min_25")
    return rows


def load_events(path: str | Path) -> list[dict]:
    """Load normalized events CSV: event_id,published_at,category,headline,score,source."""
    rows: list[dict] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line, raw in enumerate(csv.DictReader(handle), start=2):
            event_id = str(raw.get("event_id") or "").strip()
            if not event_id:
                raise ValueError(f"missing_event_id_line_{line}")
            if event_id in seen:
                raise ValueError(f"duplicate_event_id:{event_id}")
            seen.add(event_id)
            try:
                score = int(raw.get("score", ""))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid_score_line_{line}") from exc
            if score < -3 or score > 3:
                raise ValueError(f"score_out_of_range:{event_id}")
            published = _parse_datetime(raw.get("published_at", ""))
            rows.append({
                "event_id": event_id,
                "published_at": published,
                "event_date": published.date(),
                "category": str(raw.get("category") or "unknown").strip(),
                "headline": str(raw.get("headline") or "").strip(),
                "score": score,
                "source": str(raw.get("source") or "").strip(),
            })
    rows.sort(key=lambda item: (item["published_at"], item["event_id"]))
    return rows


def _find_next_session(bars: list[dict], event_date: date) -> int | None:
    """Return first bar strictly AFTER publication calendar date."""
    for index, bar in enumerate(bars):
        if bar["date"] > event_date:
            return index
    return None


def _pre_event_return(bars: list[dict], event_date: date, lookback: int) -> float | None:
    """Return from lookback close to the last close strictly before event date."""
    prior = [i for i, bar in enumerate(bars) if bar["date"] < event_date]
    if len(prior) <= lookback:
        return None
    end_i = prior[-1]
    start_i = end_i - lookback
    return bars[end_i]["close"] / bars[start_i]["close"] - 1.0


def event_study(
    bars: list[dict],
    events: list[dict],
    *,
    horizons: tuple[int, ...] = HORIZONS,
    round_trip_cost_bps: float = 0.0,
) -> tuple[list[dict], dict]:
    """Calculate event outcomes and directional/contrarian paper returns.

    Costs are applied as a configurable round-trip basis-point deduction.
    A zero default is deliberately not presented as a realistic net result.
    """
    if round_trip_cost_bps < 0:
        raise ValueError("round_trip_cost_bps_must_be_nonnegative")
    if not bars:
        raise ValueError("empty_bars")
    output: list[dict] = []
    for event in events:
        entry_i = _find_next_session(bars, event["event_date"])
        row = {
            "event_id": event["event_id"],
            "published_at": event["published_at"].isoformat(),
            "event_date": event["event_date"].isoformat(),
            "category": event["category"],
            "headline": event["headline"],
            "score": event["score"],
            "source": event["source"],
            "entry_date": bars[entry_i]["date"].isoformat() if entry_i is not None else None,
            "entry_open": bars[entry_i]["open"] if entry_i is not None else None,
            "pre_5d": _pre_event_return(bars, event["event_date"], 5),
            "pre_10d": _pre_event_return(bars, event["event_date"], 10),
        }
        for horizon in horizons:
            exit_i = entry_i + horizon - 1 if entry_i is not None else None
            valid = (
                event["score"] != 0
                and entry_i is not None
                and exit_i is not None
                and exit_i < len(bars)
            )
            if not valid:
                row[f"fwd_{horizon}d"] = None
                row[f"directional_{horizon}d"] = None
                row[f"contrarian_{horizon}d"] = None
                row[f"divergence_{horizon}d"] = None
                continue
            gross = bars[exit_i]["close"] / bars[entry_i]["open"] - 1.0
            cost = round_trip_cost_bps / 10000.0
            news_direction = 1 if event["score"] > 0 else -1
            directional = news_direction * gross - cost
            contrarian = -news_direction * gross - cost
            row[f"fwd_{horizon}d"] = gross
            row[f"directional_{horizon}d"] = directional
            row[f"contrarian_{horizon}d"] = contrarian
            row[f"divergence_{horizon}d"] = bool(news_direction * gross < 0)
        output.append(row)

    summary: dict[str, Any] = {
        "engine": "cotton_npd_v1",
        "event_count": len(events),
        "bar_count": len(bars),
        "bar_start": bars[0]["date"].isoformat(),
        "bar_end": bars[-1]["date"].isoformat(),
        "entry_rule": "first available session strictly after event calendar date, at OPEN",
        "cost_model": {
            "round_trip_cost_bps": round_trip_cost_bps,
            "note": "User-supplied assumption; zero means gross-like, not executable net performance.",
        },
        "horizons": {},
        "by_year": {},
    }
    for horizon in horizons:
        valid_rows = [r for r in output if r.get(f"directional_{horizon}d") is not None]
        directional = [r[f"directional_{horizon}d"] for r in valid_rows]
        contrarian = [r[f"contrarian_{horizon}d"] for r in valid_rows]
        divergence = [r[f"divergence_{horizon}d"] for r in valid_rows]
        summary["horizons"][str(horizon)] = {
            "n": len(valid_rows),
            "news_direction_win_rate": (
                sum(value > 0 for value in directional) / len(directional) if directional else None
            ),
            "contrarian_win_rate": (
                sum(value > 0 for value in contrarian) / len(contrarian) if contrarian else None
            ),
            "divergence_rate": sum(divergence) / len(divergence) if divergence else None,
            "directional_mean": mean(directional) if directional else None,
            "directional_median": median(directional) if directional else None,
            "contrarian_mean": mean(contrarian) if contrarian else None,
        }
        annual: dict[str, list[float]] = defaultdict(list)
        for item in valid_rows:
            annual[item["event_date"][:4]].append(item[f"directional_{horizon}d"])
        for year, values in annual.items():
            summary["by_year"].setdefault(year, {})[str(horizon)] = {
                "n": len(values),
                "directional_mean": mean(values),
                "directional_win_rate": sum(v > 0 for v in values) / len(values),
            }
    return output, summary


def write_outputs(rows: list[dict], summary: dict, output_dir: str | Path) -> None:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    if rows:
        keys = list(rows[0])
        with (target / "cotton_npd_events.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
    (target / "cotton_npd_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Cotton NPD event study (research only)")
    parser.add_argument("--bars", required=True, help="Daily bars CSV: date,open,close")
    parser.add_argument("--events", required=True, help="Normalized event CSV")
    parser.add_argument("--output", default="data/cotton_npd")
    parser.add_argument("--round-trip-cost-bps", type=float, default=0.0)
    args = parser.parse_args()
    bars = load_bars(args.bars)
    events = load_events(args.events)
    rows, summary = event_study(
        bars, events, round_trip_cost_bps=args.round_trip_cost_bps
    )
    write_outputs(rows, summary, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
