# -*- coding: utf-8 -*-
"""Shadow run of the paper MDS+EHI sleeve with real prices.

Prices: market_data.load_free_bars (Sina/Tencent, same pipeline as daily_update).
Seats: ensure_member_days (东财→新浪 + SHFE/CZCE/DCE underlay) then
load_member_seats for the last two bar dates (net_chg = day diff).
Writes data/sentiment_mds/shadow/sentiment_YYYYMMDD.json only; never touches latest.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data import load_free_bars  # noqa: E402
from member_rank import ensure_member_days, load_member_seats  # noqa: E402
from sentiment_mds import OUT, build_snapshot, price_row_from_bars, write_snapshot  # noqa: E402

SHADOW = OUT / "shadow"


def main() -> int:
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    codes = [s["code"] for s in cfg["symbols"]]
    prices: dict[str, dict] = {}
    for code in codes:
        try:
            bars, _ = load_free_bars(code)
            prices[code] = price_row_from_bars(bars)
        except Exception as exc:  # noqa: BLE001
            print(f"[shadow] price fail {code}: {exc}")
            prices[code] = {}
    dates = sorted({p["bar_date"] for p in prices.values() if p.get("bar_date")})
    if len(dates) < 1:
        print("[shadow] no bar dates")
        return 1
    day = dates[-1]
    prev_cands = sorted({p["prev_date"] for p in prices.values() if p.get("bar_date") == day and p.get("prev_date")})
    if not prev_cands:
        print(f"[shadow] no prev_date for {day}")
        return 1
    prev = prev_cands[-1]
    # Densify DCE/CZCE/EM caches so Path-A 20 are not stuck on SHFE-only prints.
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
        rows.append({"code": code, "net": net, "net_chg": net_chg, "ret_1d": px.get("ret_1d"),
                     "oi": px.get("oi"), "volume": px.get("volume")})
    snap = build_snapshot(rows, asof=day.replace("-", ""))
    snap["shadow"] = True
    snap["price_source"] = "market_data.load_free_bars (sina/tencent)"
    snap["seat_dates"] = [prev, day]
    snap["seat_source"] = "member_rank ensure_member_days (eastmoney+sina; shfe/czce/dce underlay)"
    path = write_snapshot(snap, out_dir=SHADOW, update_latest=False)
    nz = sum(1 for s in snap["symbols"] if s["ret_1d"] != 0)
    dce = {"V", "EG", "M", "EB", "PP", "L", "JD", "P", "I", "JM"}
    czce = {"MA", "FG", "TA", "SA", "CF", "SR"}
    scored = {s["code"] for s in snap["symbols"]}
    print(f"[shadow] {path} n={snap['n']} ret_nonzero={nz} p3={snap['portfolio_p3']} "
          f"stance={snap['stance']} longs={snap['longs']} shorts={snap['shorts']}")
    print(f"[shadow] dce_scored={sorted(scored & dce)} czce_scored={sorted(scored & czce)}")
    return 0 if snap["n"] and nz else 1


if __name__ == "__main__":
    raise SystemExit(main())
