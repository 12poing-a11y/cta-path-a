# -*- coding: utf-8 -*-
"""Batch shadow MDS+EHI over a date range. Paper-only; never touches latest.json.

Derives trading days from free bars (RB continuous). Soft-skips days with no
seats/prices and writes a JSONL log under data/sentiment_mds/shadow/.

Usage:
  .venv/bin/python scripts/run_sentiment_shadow_range.py --last 20
  .venv/bin/python scripts/run_sentiment_shadow_range.py --start 2026-09-24 --end 2026-10-29
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data import load_free_bars  # noqa: E402
from member_rank import ensure_member_days  # noqa: E402
from sentiment_mds import OUT  # noqa: E402

from scripts.sentiment_shadow import _norm_day, run_shadow_day  # noqa: E402

SHADOW = OUT / "shadow"


def _trading_days(start: str, end: str) -> list[str]:
    bars, _ = load_free_bars("RB")
    return sorted(
        {
            str(b.get("date"))
            for b in bars
            if start <= str(b.get("date") or "") <= end
        }
    )


def _last_n_days(n: int, end: str | None) -> tuple[str, str, list[str]]:
    bars, _ = load_free_bars("RB")
    days = [str(b.get("date")) for b in bars if b.get("date")]
    if end:
        end_iso = _norm_day(end)
        days = [d for d in days if d <= end_iso]
    if not days:
        return "", "", []
    slice_ = days[-n:] if n > 0 else days
    return slice_[0], slice_[-1], slice_


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=None, help="inclusive YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="inclusive YYYY-MM-DD")
    ap.add_argument("--last", type=int, default=0, help="last N trading days (overrides start)")
    ap.add_argument(
        "--pre-densify",
        action="store_true",
        default=True,
        help="ensure seats for all days (+prev) once before per-day scoring (default on)",
    )
    ap.add_argument("--no-pre-densify", action="store_true", help="skip bulk seat densify")
    ap.add_argument("--skip-existing", action="store_true", help="skip days that already have a snapshot")
    args = ap.parse_args(argv)

    if args.last and args.last > 0:
        start, end, days = _last_n_days(args.last, args.end)
    else:
        if not args.start or not args.end:
            print("need --start/--end or --last N", file=sys.stderr)
            return 2
        start, end = _norm_day(args.start), _norm_day(args.end)
        days = _trading_days(start, end)

    if not days:
        print("[range] no trading days in window")
        return 1

    SHADOW.mkdir(parents=True, exist_ok=True)
    print(f"[range] start={days[0]} end={days[-1]} n_days={len(days)}")

    # Need prev of first day for net_chg — densify one bar before start if present.
    bars, _ = load_free_bars("RB")
    all_dates = [str(b.get("date")) for b in bars if b.get("date")]
    densify_days = list(days)
    idx0 = all_dates.index(days[0]) if days[0] in all_dates else -1
    if idx0 > 0:
        densify_days = [all_dates[idx0 - 1]] + densify_days

    if args.pre_densify and not args.no_pre_densify:
        try:
            stats = ensure_member_days(densify_days, dce=True, public_first=True)
            print(
                f"[range] pre-densify days={stats.get('days')} "
                f"shfe={stats.get('shfe')} czce={stats.get('czce')} "
                f"dce={stats.get('dce')} em={stats.get('eastmoney')}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[range] pre-densify soft-fail: {exc}")

    log_path = SHADOW / f"range_log_{days[0].replace('-', '')}_{days[-1].replace('-', '')}.jsonl"
    ok_n = fail_n = skip_n = 0
    results = []
    with log_path.open("w", encoding="utf-8") as logf:
        for day in days:
            ymd = day.replace("-", "")
            out_file = SHADOW / f"sentiment_{ymd}.json"
            if args.skip_existing and out_file.exists():
                skip_n += 1
                row = {"day": day, "status": "skip_existing", "path": str(out_file)}
                logf.write(json.dumps(row, ensure_ascii=False) + "\n")
                results.append(row)
                print(f"[range] skip {day}")
                continue
            # densify=False: already bulk-ensured (or user opted out)
            result = run_shadow_day(day, densify=False)
            status = "ok" if result["ok"] else "fail"
            if result["ok"]:
                ok_n += 1
            else:
                fail_n += 1
            snap = result.get("snap") or {}
            row = {
                "day": day,
                "status": status,
                "path": result.get("path"),
                "error": result.get("error"),
                "n": snap.get("n"),
                "portfolio_p3": snap.get("portfolio_p3"),
                "stance": snap.get("stance"),
            }
            logf.write(json.dumps(row, ensure_ascii=False) + "\n")
            results.append(row)

    summary = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "start": days[0],
        "end": days[-1],
        "n_days": len(days),
        "ok": ok_n,
        "fail": fail_n,
        "skip": skip_n,
        "log": str(log_path),
        "shadow_dir": str(SHADOW),
        "note": "Paper MDS+EHI shadow range; does not update latest.json or formal scoring.",
        "results": results,
    }
    summary_path = SHADOW / f"range_summary_{days[0].replace('-', '')}_{days[-1].replace('-', '')}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[range] done ok={ok_n} fail={fail_n} skip={skip_n} "
        f"log={log_path} summary={summary_path}"
    )
    return 0 if ok_n else 1


if __name__ == "__main__":
    raise SystemExit(main())
