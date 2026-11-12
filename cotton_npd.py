# -*- coding: utf-8 -*-
"""Cotton News-Price Divergence (NPD) event-study engine.

Research-only. It never fetches or fabricates news/prices and never places orders.
Events are entered at the next available session OPEN to avoid same-day look-ahead.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
HORIZONS = (1, 3, 5, 10, 20)

# China focus set (六类) — only these CN categories count as core watchlist.
CN_CATEGORIES: dict[str, str] = {
    "CN_RESERVE": "国储棉轮入/轮出公告与成交结果",
    "CN_SLIDING_QUOTA": "棉花进口滑准税配额发放",
    "CN_CASDE": "农业农村部农产品供需形势分析（CASDE）",
    "CN_NBS_OUTPUT": "国家统计局棉花产量公告",
    "CN_XJ_TARGET_PRICE": "新疆棉目标价格等政策公告",
    "CN_CUSTOMS_IMPORT": "海关棉花进口月度数据",
}
# USDA / US side (expand later as needed).
USDA_CATEGORIES: dict[str, str] = {
    "USDA_WASDE": "USDA WASDE",
    "USDA_CROP_PROGRESS": "USDA Crop Progress",
    "USDA_OTHER": "USDA 其他官方发布",
}
FAMILY_CN = "CN"
FAMILY_USDA = "USDA"
STATUS_ACCEPTED = "accepted"
STATUS_PENDING = "待核"


def _parse_datetime(value: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        raise ValueError("missing_published_at")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def infer_family(category: str, family: str | None = None) -> str:
    cat = str(category or "").strip()
    fam = str(family or "").strip().upper()
    if fam in (FAMILY_CN, FAMILY_USDA):
        return fam
    if cat in CN_CATEGORIES or cat.startswith("CN_"):
        return FAMILY_CN
    if cat in USDA_CATEGORIES or cat.startswith("USDA"):
        return FAMILY_USDA
    # Legacy aliases
    if cat in ("CASDE",):
        return FAMILY_CN
    if cat in ("USDA_WASDE", "WASDE"):
        return FAMILY_USDA
    return "OTHER"


def normalize_category(category: str, family: str) -> str:
    cat = str(category or "").strip()
    if cat == "CASDE":
        return "CN_CASDE"
    if cat in ("WASDE", "USDA_WASDE"):
        return "USDA_WASDE"
    if family == FAMILY_CN and cat in CN_CATEGORIES:
        return cat
    if family == FAMILY_USDA and cat in USDA_CATEGORIES:
        return cat
    return cat or "unknown"


def provenance_status(
    *,
    published_at_raw: str,
    official_url: str,
    official_excerpt: str,
    status_raw: str | None = None,
) -> tuple[str, str | None]:
    """accepted only with official URL + excerpt + parseable publish time; else 待核."""
    forced = str(status_raw or "").strip()
    if forced in (STATUS_PENDING, "pending", "PENDING"):
        return STATUS_PENDING, "marked_pending"
    url = str(official_url or "").strip()
    excerpt = str(official_excerpt or "").strip()
    pub = str(published_at_raw or "").strip()
    reasons: list[str] = []
    if not pub:
        reasons.append("缺发布时间")
    else:
        try:
            _parse_datetime(pub)
        except Exception:  # noqa: BLE001
            reasons.append("发布时间不可解析")
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        reasons.append("缺官方原文链接")
    if len(excerpt) < 8:
        reasons.append("缺官方原文摘录")
    if reasons:
        return STATUS_PENDING, "；".join(reasons)
    return STATUS_ACCEPTED, None


def _finite_positive(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}:{value}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"invalid_or_non_positive_{field}:{value}")
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
    """Load events CSV with provenance gate.

    Required: ``event_id``, ``score``.
    For **accepted** study rows also require ``published_at``, ``official_url``,
    and ``official_excerpt`` (官方原文摘录). Missing any → ``status=待核`` and
    the row is kept for the watchlist but excluded from sensitivity stats.
    """
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
                score = int(str(raw.get("score", "")).strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid_score_line_{line}") from exc
            if score < -3 or score > 3:
                raise ValueError(f"score_out_of_range:{event_id}")

            official_url = str(
                raw.get("official_url") or raw.get("source") or ""
            ).strip()
            official_excerpt = str(
                raw.get("official_excerpt") or raw.get("excerpt") or ""
            ).strip()
            pub_raw = str(raw.get("published_at") or "").strip()
            status, pending_reason = provenance_status(
                published_at_raw=pub_raw,
                official_url=official_url,
                official_excerpt=official_excerpt,
                status_raw=raw.get("status"),
            )
            family = infer_family(
                str(raw.get("category") or ""),
                str(raw.get("family") or ""),
            )
            category = normalize_category(str(raw.get("category") or ""), family)

            published = None
            event_date = None
            if pub_raw:
                try:
                    published = _parse_datetime(pub_raw)
                    event_date = published.date()
                except Exception:  # noqa: BLE001
                    status = STATUS_PENDING
                    pending_reason = (pending_reason or "") + "；发布时间不可解析"
                    pending_reason = pending_reason.lstrip("；")

            rows.append(
                {
                    "event_id": event_id,
                    "published_at": published,
                    "event_date": event_date,
                    "category": category,
                    "family": family,
                    "headline": str(raw.get("headline") or "").strip(),
                    "score": score,
                    "source": official_url,
                    "official_url": official_url,
                    "official_excerpt": official_excerpt,
                    "status": status,
                    "pending_reason": pending_reason,
                }
            )
    rows.sort(
        key=lambda item: (
            item["published_at"] or datetime.min.replace(tzinfo=TZ),
            item["event_id"],
        )
    )
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


def _horizon_stats(rows: list[dict], horizon: int) -> dict[str, Any]:
    valid_rows = [r for r in rows if r.get(f"directional_{horizon}d") is not None]
    directional = [r[f"directional_{horizon}d"] for r in valid_rows]
    contrarian = [r[f"contrarian_{horizon}d"] for r in valid_rows]
    divergence = [r[f"divergence_{horizon}d"] for r in valid_rows]
    return {
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

    Only ``status=accepted`` events with a publish date enter return math.
    ``待核`` rows are listed but excluded from CN / USDA / combined stats.
    """
    if round_trip_cost_bps < 0:
        raise ValueError("round_trip_cost_bps_must_be_nonnegative")
    if not bars:
        raise ValueError("empty_bars")
    output: list[dict] = []
    for event in events:
        status = str(event.get("status") or STATUS_ACCEPTED)
        family = infer_family(str(event.get("category") or ""), event.get("family"))
        category = normalize_category(str(event.get("category") or ""), family)
        event_date = event.get("event_date")
        published = event.get("published_at")
        accepted = status == STATUS_ACCEPTED and event_date is not None
        entry_i = _find_next_session(bars, event_date) if accepted else None
        row = {
            "event_id": event["event_id"],
            "published_at": published.isoformat() if published is not None else None,
            "event_date": event_date.isoformat() if event_date is not None else None,
            "category": category,
            "family": family,
            "headline": event.get("headline") or "",
            "score": event["score"],
            "source": event.get("source") or event.get("official_url") or "",
            "official_url": event.get("official_url") or event.get("source") or "",
            "official_excerpt": event.get("official_excerpt") or "",
            "status": status,
            "pending_reason": event.get("pending_reason"),
            "entry_date": bars[entry_i]["date"].isoformat() if entry_i is not None else None,
            "entry_open": bars[entry_i]["open"] if entry_i is not None else None,
            "pre_5d": _pre_event_return(bars, event_date, 5) if accepted else None,
            "pre_10d": _pre_event_return(bars, event_date, 10) if accepted else None,
        }
        for horizon in horizons:
            exit_i = entry_i + horizon - 1 if entry_i is not None else None
            valid = (
                accepted
                and event["score"] != 0
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

    accepted_rows = [r for r in output if r.get("status") == STATUS_ACCEPTED]
    pending_rows = [r for r in output if r.get("status") != STATUS_ACCEPTED]
    cn_rows = [r for r in accepted_rows if r.get("family") == FAMILY_CN]
    usda_rows = [r for r in accepted_rows if r.get("family") == FAMILY_USDA]

    def _block(label: str, rows: list[dict]) -> dict[str, Any]:
        horizons_map: dict[str, Any] = {}
        by_year: dict[str, Any] = {}
        for horizon in horizons:
            horizons_map[str(horizon)] = _horizon_stats(rows, horizon)
            annual: dict[str, list[float]] = defaultdict(list)
            for item in rows:
                if item.get(f"directional_{horizon}d") is None:
                    continue
                year = str(item.get("event_date") or "")[:4]
                if len(year) == 4:
                    annual[year].append(item[f"directional_{horizon}d"])
            for year, values in annual.items():
                by_year.setdefault(year, {})[str(horizon)] = {
                    "n": len(values),
                    "directional_mean": mean(values),
                    "directional_win_rate": sum(v > 0 for v in values) / len(values),
                }
        return {
            "label": label,
            "event_count": len(rows),
            "scored_event_count": sum(1 for r in rows if int(r.get("score") or 0) != 0),
            "horizons": horizons_map,
            "by_year": by_year,
        }

    summary: dict[str, Any] = {
        "engine": "cotton_npd_v1",
        "event_count": len(events),
        "accepted_count": len(accepted_rows),
        "pending_count": len(pending_rows),
        "bar_count": len(bars),
        "bar_start": bars[0]["date"].isoformat(),
        "bar_end": bars[-1]["date"].isoformat(),
        "entry_rule": "first available session strictly after event calendar date, at OPEN",
        "cost_model": {
            "round_trip_cost_bps": round_trip_cost_bps,
            "note": "User-supplied assumption; zero means gross-like, not executable net performance.",
        },
        "cn_watchlist": CN_CATEGORIES,
        "usda_watchlist": USDA_CATEGORIES,
        "provenance_rule": (
            "accepted 须同时具备官方原文链接、官方原文摘录、可解析发布时间；"
            "否则标 待核，不进敏感性统计。"
        ),
        # Back-compat: combined accepted stats at top-level horizons/by_year.
        "horizons": _block("combined", accepted_rows)["horizons"],
        "by_year": _block("combined", accepted_rows)["by_year"],
        "by_family": {
            "CN": _block("中国事件", cn_rows),
            "USDA": _block("USDA事件", usda_rows),
            "combined": _block("中国+USDA合并", accepted_rows),
        },
        "pending_events": [
            {
                "event_id": r.get("event_id"),
                "category": r.get("category"),
                "family": r.get("family"),
                "pending_reason": r.get("pending_reason"),
                "headline": r.get("headline"),
            }
            for r in pending_rows
        ],
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


def _asof_date(asof: str | date | datetime | None) -> date:
    if asof is None:
        return datetime.now(TZ).date()
    if isinstance(asof, datetime):
        return asof.astimezone(TZ).date()
    if isinstance(asof, date):
        return asof
    text = str(asof).strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])


def entry_day_reminders(
    bars: list[dict],
    events: list[dict],
    asof: str | date | datetime | None = None,
) -> dict[str, Any]:
    """Shadow reminders for NPD **entry days** only (research, not a trade gate).

    An entry day is the first session strictly after the event's CST publication
    calendar date. Off entry days the payload is empty — no standing NPD signal.
    Divergence labels are outcomes and are never used as inputs here.
    """
    asof_d = _asof_date(asof)
    rows, summary = event_study(bars, events, round_trip_cost_bps=0.0)
    asof_iso = asof_d.isoformat()
    # Reminders only for accepted provenance rows on their entry day.
    active = [
        r
        for r in rows
        if r.get("entry_date") == asof_iso and r.get("status") == STATUS_ACCEPTED
    ]
    scored = [r for r in active if int(r.get("score") or 0) != 0]
    neutral = [r for r in active if int(r.get("score") or 0) == 0]
    reminders: list[dict[str, Any]] = []
    for row in scored + neutral:
        score = int(row.get("score") or 0)
        if score > 0:
            lean = "利多"
        elif score < 0:
            lean = "利空"
        else:
            lean = "中性(不评分)"
        reminders.append(
            {
                "event_id": row.get("event_id"),
                "entry_date": row.get("entry_date"),
                "event_date": row.get("event_date"),
                "published_at": row.get("published_at"),
                "category": row.get("category"),
                "family": row.get("family"),
                "headline": row.get("headline"),
                "score": score,
                "lean": lean,
                "source": row.get("source"),
                "official_url": row.get("official_url"),
                "entry_open": row.get("entry_open"),
                "pre_5d": row.get("pre_5d"),
                "note": (
                    "影子提醒：今日为 NPD 进入日（发布日后首个交易日开盘口径）；"
                    "仅研究观察，不改 Path-A / 不下单。"
                ),
            }
        )
    return {
        "ok": True,
        "live_trading": False,
        "shadow": True,
        "counts_toward_score": False,
        "asof": asof_iso,
        "is_entry_day": bool(reminders),
        "n": len(reminders),
        "n_scored": len(scored),
        "reminders": reminders,
        "entry_rule": "first session strictly after event calendar date, at OPEN",
        "by_family": summary.get("by_family"),
        "pending_count": summary.get("pending_count"),
        "cn_watchlist": CN_CATEGORIES,
    }


def _bars_from_ohlc_rows(raw: Any) -> list[dict]:
    extra: list[dict] = []
    if not isinstance(raw, list):
        return extra
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            day = date.fromisoformat(str(item.get("date") or "")[:10])
            extra.append(
                {
                    "date": day,
                    "open": _finite_positive(item.get("open"), "open"),
                    "close": _finite_positive(item.get("close"), "close"),
                    "volume": item.get("volume"),
                    "oi": item.get("oi") or item.get("open_interest"),
                }
            )
        except (TypeError, ValueError):
            continue
    return extra


def _merge_bars(base: list[dict], extra: list[dict]) -> list[dict]:
    if not extra:
        return base
    by_day = {b["date"]: b for b in base}
    for row in extra:
        by_day[row["date"]] = row
    return [by_day[k] for k in sorted(by_day)]


def load_bars_from_root(root: str | Path) -> list[dict]:
    """Prefer audited cotton CSV; extend with CF0 history + latest sina day folders."""
    root = Path(root)
    csv_path = root / "data" / "cotton" / "cf0_daily_20211112_20261111.csv"
    bars: list[dict] = []
    if csv_path.is_file():
        bars = load_bars(csv_path)
    # Extend / override with merged chart history when newer sessions exist.
    hist = root / ".cache" / "history" / "CF0.json"
    if hist.is_file():
        try:
            raw = json.loads(hist.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        bars = _merge_bars(bars, _bars_from_ohlc_rows(raw))
    # Sina day folders often have the newest session before history merge catches up.
    sina = root / ".cache" / "sina"
    if sina.is_dir():
        day_dirs = sorted(
            [p for p in sina.iterdir() if p.is_dir() and p.name[:4].isdigit()],
            key=lambda p: p.name,
        )
        for day_dir in day_dirs[-5:]:
            path = day_dir / "CF0.json"
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            bars = _merge_bars(bars, _bars_from_ohlc_rows(raw))
    if len(bars) < 25:
        raise ValueError("insufficient_cf_bars_for_npd")
    return bars


def load_events_from_root(root: str | Path) -> list[dict]:
    path = Path(root) / "data" / "cotton" / "cotton_events.csv"
    if not path.is_file():
        return []
    return load_events(path)


def shadow_reminders_for_root(
    root: str | Path,
    asof: str | date | datetime | None = None,
) -> dict[str, Any]:
    """Desk entry: load local cotton inputs and return entry-day shadow reminders."""
    root = Path(root)
    try:
        events = load_events_from_root(root)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "shadow": True,
            "counts_toward_score": False,
            "live_trading": False,
            "is_entry_day": False,
            "n": 0,
            "reminders": [],
            "error": f"events:{type(exc).__name__}:{exc}",
        }
    if not events:
        return {
            "ok": True,
            "shadow": True,
            "counts_toward_score": False,
            "live_trading": False,
            "is_entry_day": False,
            "n": 0,
            "reminders": [],
            "note": "无 data/cotton/cotton_events.csv；NPD 仅事件日提醒，无事件则静默。",
        }
    try:
        bars = load_bars_from_root(root)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "shadow": True,
            "counts_toward_score": False,
            "live_trading": False,
            "is_entry_day": False,
            "n": 0,
            "reminders": [],
            "error": f"bars:{type(exc).__name__}:{exc}",
        }
    return entry_day_reminders(bars, events, asof=asof)


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
