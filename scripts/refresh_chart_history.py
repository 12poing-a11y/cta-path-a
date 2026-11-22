# -*- coding: utf-8 -*-
"""Refresh .cache/history/{CODE}0.json for Path-A universe.

Free-first: Sina continuous (+ local sina day-folder overlay), then TqSdk,
then iFinD only if still short of the latest expected session.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_data import (  # noqa: E402
    fill_main_with_tqsdk,
    latest_expected_session_date,
    load_free_bars,
    merge_bars,
    save_chart_history,
)


def _universe_codes(root: Path) -> list[str]:
    uni = json.loads((root / "universe.json").read_text(encoding="utf-8"))
    return [str(s.get("code") or "").upper() for s in (uni.get("symbols") or []) if s.get("code")]


def _overlay_local_sina(root: Path, code: str, bars: list[dict]) -> list[dict]:
    """Merge newer CODE0 bars already cached under .cache/sina/<day>/."""
    sina = root / ".cache" / "sina"
    if not sina.is_dir():
        return bars
    symbol = f"{code}0.json"
    dirs = sorted([p for p in sina.iterdir() if p.is_dir()])
    merged = list(bars)
    for day in dirs:
        path = day / symbol
        if not path.is_file():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(rows, list) and rows:
            merged = merge_bars(merged, rows)
    return merged


def refresh_one(
    code: str,
    *,
    root: Path,
    allow_paid: bool,
) -> dict:
    expected = latest_expected_session_date().isoformat()
    free, meta = load_free_bars(code)
    bars = [b for b in free if str(b.get("date") or "")[:10] <= expected]
    bars = _overlay_local_sina(root, code, bars)
    bars = [b for b in bars if str(b.get("date") or "")[:10] <= expected]
    sources = [meta.get("source") or "sina"]
    paid = {"tqsdk": False, "ifind": False}

    last = str(bars[-1]["date"])[:10] if bars else ""
    if allow_paid and (not last or last < expected):
        filled, tmeta = fill_main_with_tqsdk(
            code, bars, need_date=expected, root=root, length=80
        )
        if tmeta.get("tqsdk"):
            bars = [b for b in filled if str(b.get("date") or "")[:10] <= expected]
            sources.append("tqsdk")
            paid["tqsdk"] = True
            last = str(bars[-1]["date"])[:10] if bars else ""

    if allow_paid and (not last or last < expected):
        try:
            from historical_backtest import _fetch_ifind_recent_history

            uni = {"code": code}
            # minimal symbol row for ifind helper
            for sym in json.loads((root / "universe.json").read_text(encoding="utf-8")).get(
                "symbols"
            ) or []:
                if str(sym.get("code") or "").upper() == code:
                    uni = sym
                    break
            from datetime import date as _date

            ifind = _fetch_ifind_recent_history(uni, _date.fromisoformat(expected))
            if ifind:
                bars = merge_bars(bars, ifind)
                bars = [b for b in bars if str(b.get("date") or "")[:10] <= expected]
                sources.append("ifind")
                paid["ifind"] = True
        except Exception as exc:  # noqa: BLE001
            paid["ifind_error"] = str(exc)[:120]

    path = save_chart_history(code, bars, root=root)
    last = str(bars[-1]["date"])[:10] if bars else ""
    return {
        "code": code,
        "n": len(bars),
        "last": last,
        "expected": expected,
        "fresh": bool(last and last >= expected),
        "source": "+".join(sources),
        "paid": paid,
        "path": str(path) if path else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--codes", default="", help="comma codes; default universe")
    ap.add_argument(
        "--allow-paid",
        action="store_true",
        help="if free/local still short of expected session, try TqSdk then iFinD",
    )
    args = ap.parse_args(argv)
    root = Path(args.root)
    codes = [c.strip().upper() for c in str(args.codes).split(",") if c.strip()]
    if not codes:
        codes = _universe_codes(root)

    rows = []
    for code in codes:
        try:
            row = refresh_one(code, root=root, allow_paid=bool(args.allow_paid))
        except Exception as exc:  # noqa: BLE001
            row = {"code": code, "fresh": False, "error": str(exc)[:160]}
        rows.append(row)
        print(
            f"[history] {row.get('code')} last={row.get('last')} "
            f"fresh={row.get('fresh')} n={row.get('n')} src={row.get('source')} "
            f"err={row.get('error') or row.get('paid', {}).get('ifind_error') or ''}"
        )

    fresh_n = sum(1 for r in rows if r.get("fresh"))
    print(f"[history] done fresh={fresh_n}/{len(rows)} expected={rows[0].get('expected') if rows else '-'}")
    return 0 if fresh_n == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
