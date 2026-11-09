# -*- coding: utf-8 -*-
"""Shadow run of the paper MDS+EHI sleeve with real prices.

Prices: market_data.load_free_bars (Sina/Tencent, same pipeline as daily_update).
Seats: ensure_member_days (东财→新浪 + SHFE/CZCE/DCE underlay) then
load_member_seats for the last two bar dates (net_chg = day diff).
Writes data/sentiment_mds/shadow/sentiment_YYYYMMDD.json only; never touches latest.json.

Usage:
  .venv/bin/python scripts/sentiment_shadow.py
  .venv/bin/python scripts/sentiment_shadow.py --asof 2026-10-29
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data import load_free_bars  # noqa: E402
from member_rank import ensure_member_days, load_member_seats  # noqa: E402
from sentiment_mds import OUT, build_snapshot, price_row_from_bars, write_snapshot  # noqa: E402

SHADOW = OUT / "shadow"
DCE = {"V", "EG", "M", "EB", "PP", "L", "JD", "P", "I", "JM"}
CZCE = {"MA", "FG", "TA", "SA", "CF", "SR"}


def _norm_day(s: str) -> str:
    """Return YYYY-MM-DD from YYYYMMDD or YYYY-MM-DD."""
    t = str(s or "").strip().replace("-", "")
    if len(t) != 8 or not t.isdigit():
        raise ValueError(f"bad day: {s!r}")
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}"


def _universe_codes() -> list[str]:
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    return [s["code"] for s in cfg["symbols"]]


def _load_prices(codes: list[str], asof: str | None) -> dict[str, dict]:
    """Price rows truncated to asof (inclusive). asof=None → latest available."""
    prices: dict[str, dict] = {}
    for code in codes:
        try:
            bars, _ = load_free_bars(code)
            if asof:
                bars = [b for b in bars if str(b.get("date") or "") <= asof]
            prices[code] = price_row_from_bars(bars)
        except Exception as exc:  # noqa: BLE001
            print(f"[shadow] price fail {code}: {exc}")
            prices[code] = {}
    return prices


def run_shadow_day(
    asof: str | None = None,
    *,
    densify: bool = True,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Build one shadow snapshot for asof (YYYY-MM-DD) or latest bar date.

    Never writes data/sentiment_mds/latest.json.
    Returns {"ok": bool, "path": str|None, "snap": dict|None, "error": str|None}.
    """
    codes = _universe_codes()
    day_iso = _norm_day(asof) if asof else None
    prices = _load_prices(codes, day_iso)
    dates = sorted({p["bar_date"] for p in prices.values() if p.get("bar_date")})
    if not dates:
        return {"ok": False, "path": None, "snap": None, "error": "no bar dates"}
    day = dates[-1]
    if day_iso and day != day_iso:
        # Requested day missing from bars → soft skip
        return {
            "ok": False,
            "path": None,
            "snap": None,
            "error": f"no bars on {day_iso} (last available {day})",
        }
    prev_cands = sorted(
        {
            p["prev_date"]
            for p in prices.values()
            if p.get("bar_date") == day and p.get("prev_date")
        }
    )
    if not prev_cands:
        return {"ok": False, "path": None, "snap": None, "error": f"no prev_date for {day}"}
    prev = prev_cands[-1]
    if densify:
        try:
            stats = ensure_member_days([prev, day], dce=True, public_first=True)
            print(
                f"[shadow] seats ensure days={stats.get('days')} "
                f"shfe={stats.get('shfe')} czce={stats.get('czce')} "
                f"dce={stats.get('dce')} em={stats.get('eastmoney')}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[shadow] seats ensure soft-fail: {exc}")
    seats = load_member_seats([prev, day], codes)
    rows = []
    for code in codes:
        book = seats.get(code) or {}
        if day not in book:
            continue
        net = float(book[day].get("inst") or 0.0)
        net_chg = net - float(book[prev].get("inst") or 0.0) if prev in book else net
        px = prices.get(code) or {}
        if px.get("bar_date") != day:
            continue
        rows.append(
            {
                "code": code,
                "net": net,
                "net_chg": net_chg,
                "ret_1d": px.get("ret_1d"),
                "oi": px.get("oi"),
                "volume": px.get("volume"),
            }
        )
    if not rows:
        return {"ok": False, "path": None, "snap": None, "error": f"no seat+price rows for {day}"}
    snap = build_snapshot(rows, asof=day.replace("-", ""))
    snap["shadow"] = True
    snap["price_source"] = "market_data.load_free_bars (sina/tencent)"
    snap["seat_dates"] = [prev, day]
    snap["seat_source"] = (
        "member_rank ensure_member_days (eastmoney+sina; shfe/czce/dce underlay)"
    )
    target = out_dir or SHADOW
    path = write_snapshot(snap, out_dir=target, update_latest=False)
    nz = sum(1 for s in snap["symbols"] if s["ret_1d"] != 0)
    scored = {s["code"] for s in snap["symbols"]}
    print(
        f"[shadow] {path} n={snap['n']} ret_nonzero={nz} p3={snap['portfolio_p3']} "
        f"stance={snap['stance']} longs={snap['longs']} shorts={snap['shorts']}"
    )
    print(f"[shadow] dce_scored={sorted(scored & DCE)} czce_scored={sorted(scored & CZCE)}")
    ok = bool(snap["n"] and nz)
    return {
        "ok": ok,
        "path": str(path),
        "snap": snap,
        "error": None if ok else "n=0 or all ret_1d=0",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--asof",
        default=None,
        help="YYYY-MM-DD or YYYYMMDD; default = latest free-bar date",
    )
    ap.add_argument(
        "--no-densify",
        action="store_true",
        help="skip ensure_member_days (use existing seat cache only)",
    )
    args = ap.parse_args(argv)
    asof = _norm_day(args.asof) if args.asof else None
    result = run_shadow_day(asof, densify=not args.no_densify)
    if result["error"]:
        print(f"[shadow] fail: {result['error']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
