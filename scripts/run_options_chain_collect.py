# -*- coding: utf-8 -*-
"""Collect CF/SR/MA option chain snapshots into data/options/snapshots/.

Prefers gamma_wall raw cache (offline). Soft-fails per code/date; never touches Path-A formal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gamma_wall import OBSERVE_MONTH  # noqa: E402
from research.options.chain_store import (  # noqa: E402
    accumulate_live_bidask,
    build_from_gamma_raw_cache,
    build_from_tq_live,
    build_snapshot,
    collect_code_from_cache,
    list_raw_cache_dates,
    write_snapshot,
)


def collect_one(root: Path, code: str, asof: str, contract: str) -> dict:
    try:
        snap = build_from_gamma_raw_cache(root, code=code, asof=asof, futures_contract=contract)
    except FileNotFoundError:
        from gamma_wall import _fetch_czce_day, _load_exact_contract_daily, _num, _row_on_date

        frame = _fetch_czce_day(code, asof)
        option_rows = frame.to_dict("records")
        fut_rows = _load_exact_contract_daily(contract, root=root, refresh=True, need_date=asof)
        frow = _row_on_date(fut_rows, asof)
        settle = _num(frow.get("settle")) or _num(frow.get("close")) if frow else None
        fut_date = str(frow.get("date") or "")[:10] if frow else None
        snap = build_snapshot(
            code=code,
            asof=asof,
            futures_contract=contract,
            underlying_settle=float(settle) if settle is not None else None,
            option_rows=option_rows,
            source="czce_day_live",
            futures_date=fut_date,
        )
    path = write_snapshot(root, snap, allow_reject=True)
    return {
        "code": code,
        "asof": asof,
        "path": str(path),
        "quality": (snap.get("quality") or {}).get("status"),
        "n_legs": len(snap.get("legs") or []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--codes", default="CF,SR,MA")
    ap.add_argument("--month", default=OBSERVE_MONTH, help="YYYYMM futures month e.g. 2701")
    ap.add_argument("--asof", default="", help="single date YYYY-MM-DD; default=all raw cache dates")
    ap.add_argument(
        "--tq-live",
        action="store_true",
        help="fetch live Tq Bid/Ask (fast path, no IV) into today's snapshot",
    )
    ap.add_argument(
        "--tq-live-only",
        action="store_true",
        help="skip gamma cache; only accumulate live Bid/Ask",
    )
    ap.add_argument("--deadline", type=float, default=45.0, help="per-code wall seconds for Tq")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    codes = [c.strip().upper() for c in str(args.codes).split(",") if c.strip()]
    results = []
    if not args.tq_live_only:
        for code in codes:
            contract = f"{code}{args.month}"
            if args.asof:
                try:
                    results.append(collect_one(args.root, code, args.asof, contract))
                    r = results[-1]
                    print(f"[options-chain] {code} {args.asof} q={r['quality']} legs={r['n_legs']}")
                except Exception as exc:
                    print(f"[options-chain] {code} {args.asof} soft-fail: {exc}")
            else:
                for r in collect_code_from_cache(args.root, code, month=args.month):
                    results.append(r)
                    if r.get("error"):
                        print(f"[options-chain] {code} {r.get('asof')} soft-fail: {r['error']}")
                    else:
                        print(f"[options-chain] {code} {r['asof']} q={r['quality']} legs={r['n_legs']}")
                if not list_raw_cache_dates(args.root, code):
                    print(f"[options-chain] {code}: no dates")
    if args.tq_live or args.tq_live_only:
        acc = accumulate_live_bidask(
            args.root,
            codes=codes,
            month=args.month,
            overall_deadline_s=float(args.deadline),
        )
        for r in acc.get("results") or []:
            results.append(r)
            if r.get("ok"):
                print(
                    f"[options-chain] {r['code']} LIVE q={r.get('quality')} "
                    f"legs={r.get('n_legs')} bid_ask={r.get('n_with_bid_ask')} "
                    f"t={r.get('elapsed_s')}s"
                )
            else:
                print(f"[options-chain] {r.get('code')} tq-live soft-fail: {r.get('error')}")
        print(f"[options-chain] live accumulate ok={acc.get('n_ok')} fail={acc.get('n_fail')}")
    summary = {"n": len([r for r in results if not r.get("error")]), "results": results}
    out = args.root / "data" / "options" / "snapshots" / "collect_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[options-chain] wrote {out} n={summary['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
