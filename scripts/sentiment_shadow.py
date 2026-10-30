# -*- coding: utf-8 -*-
"""Shadow run of the paper MDS+EHI sleeve with real prices.

Prices: market_data.load_free_bars (Sina/Tencent, same pipeline as daily_update).
Seats: member_rank.load_member_seats for the last two bar dates (net_chg = day diff).
Writes data/sentiment_mds/shadow/sentiment_YYYYMMDD.json only; never touches latest.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_data import load_free_bars  # noqa: E402
from member_rank import load_member_seats  # noqa: E402
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
    day = dates[-1]
    prev = sorted({p["prev_date"] for p in prices.values() if p.get("bar_date") == day})[-1]
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
    path = write_snapshot(snap, out_dir=SHADOW, update_latest=False)
    nz = sum(1 for s in snap["symbols"] if s["ret_1d"] != 0)
    print(f"[shadow] {path} n={snap['n']} ret_nonzero={nz} p3={snap['portfolio_p3']} "
          f"stance={snap['stance']} longs={snap['longs']} shorts={snap['shorts']}")
    return 0 if snap["n"] and nz else 1


if __name__ == "__main__":
    raise SystemExit(main())
