# -*- coding: utf-8 -*-
"""Download SHFE/CZCE member ranking files into .cache/member.

Uses unique trading dates from lab continuous bars. Soft-skips holidays.
DCE (akshare) is optional and usually empty under WAF — skip unless --dce.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
sys.path.insert(0, str(ROOT))

from member_rank import _cache_path, _get, fetch_dce_member_day  # noqa: E402


def _bar_dates(start: str, end: str | None) -> list[str]:
    days: set[str] = set()
    for path in sorted((LAB / "data" / "bars" / "continuous").glob("*.json")):
        if path.name.startswith("."):
            continue
        bars = json.loads(path.read_text(encoding="utf-8")).get("bars") or []
        for b in bars:
            d = str(b.get("date") or "")
            if not d or d < start:
                continue
            if end and d > end:
                continue
            days.add(d)
    return sorted(days)


def _ensure_day(day: str, *, dce: bool) -> dict:
    ymd = day.replace("-", "")
    year = ymd[:4]
    shfe_path = _cache_path("shfe", ymd)
    czce_path = _cache_path("czce", ymd)
    shfe_had = shfe_path.exists() and shfe_path.stat().st_size > 200
    czce_had = czce_path.exists() and czce_path.stat().st_size > 200
    if not shfe_had:
        _get(
            f"https://www.shfe.com.cn/data/tradedata/future/dailydata/pm{ymd}.dat",
            shfe_path,
        )
    if not czce_had:
        _get(
            f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{ymd}/FutureDataHolding.txt",
            czce_path,
        )
    shfe_ok = shfe_path.exists() and shfe_path.stat().st_size > 200
    czce_ok = czce_path.exists() and czce_path.stat().st_size > 200
    dce_ok = False
    if dce:
        got = fetch_dce_member_day(ymd, force=False)
        dce_ok = bool((got or {}).get("products"))
    return {
        "day": day,
        "shfe": shfe_ok,
        "czce": czce_ok,
        "dce": dce_ok,
        "fetched": (not shfe_had) or (not czce_had),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2018-01-01", help="inclusive YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="inclusive YYYY-MM-DD (default: latest bar)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dce", action="store_true", help="also pull DCE via akshare (slow/WAF)")
    ap.add_argument("--limit", type=int, default=0, help="max days (0=all)")
    args = ap.parse_args()

    days = _bar_dates(args.start, args.end)
    if args.limit and args.limit > 0:
        days = days[: args.limit]
    print(
        f"[backfill-member] days={len(days)} "
        f"start={days[0] if days else None} end={days[-1] if days else None} dce={args.dce}"
    )
    if not days:
        return 1

    ok = empty = fetched = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(_ensure_day, d, dce=args.dce): d for d in days}
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                row = fut.result()
            except Exception as exc:
                empty += 1
                print(f"  ERR {futs[fut]} {exc}")
                continue
            if row["fetched"]:
                fetched += 1
            if row["shfe"] or row["czce"] or row["dce"]:
                ok += 1
            else:
                empty += 1
            if done % 100 == 0 or done == len(days):
                print(
                    f"  [{done}/{len(days)}] ok={ok} empty={empty} new_fetch≈{fetched} "
                    f"last={row['day']} shfe={int(row['shfe'])} czce={int(row['czce'])}"
                )
    folder = ROOT / ".cache" / "member"
    n_shfe = len(list(folder.glob("shfe-*.txt")))
    n_czce = len(list(folder.glob("czce-*.txt")))
    n_dce = len(list(folder.glob("dce-*.json")))
    print(f"[backfill-member] done files shfe={n_shfe} czce={n_czce} dce={n_dce}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
