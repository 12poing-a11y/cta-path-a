# -*- coding: utf-8 -*-
"""CLI: dual-source bar/seat observability report (free-first, no paid calls)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.data_quality.dual_source_diff import (  # noqa: E402
    build_report,
    write_report,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Compare free Sina bars vs history cache; EM seats vs exchange prints."
    )
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument(
        "--codes",
        default="",
        help="Comma codes (default: universe.json). Example: CF,MA,SR",
    )
    p.add_argument("--lookback-days", type=int, default=60)
    p.add_argument("--close-tol-pct", type=float, default=0.15)
    p.add_argument("--seat-ymd", default="", help="YYYYMMDD; default newest em-* cache")
    p.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not fetch Sina; only diff existing history vs empty free (seat cache still used).",
    )
    p.add_argument(
        "--no-write",
        action="store_true",
        help="Print summary only; do not write data/dual_source_diff_latest.json",
    )
    args = p.parse_args(argv)

    codes = [c.strip().upper() for c in str(args.codes).split(",") if c.strip()] or None
    report = build_report(
        Path(args.root),
        codes=codes,
        lookback_days=int(args.lookback_days),
        close_tol_pct=float(args.close_tol_pct),
        seat_ymd=str(args.seat_ymd or "") or None,
        fetch_free=not bool(args.cache_only),
        allow_paid=False,
    )
    path = None
    if not args.no_write:
        path = write_report(report, Path(args.root))

    summary = report.get("summary") or {}
    print(
        f"[dual-source-diff] status={report.get('overall_status')} "
        f"bars_mismatch={summary.get('bars_mismatch')} "
        f"bars_fill_suspected={summary.get('bars_paid_fill_suspected')} "
        f"seats_mismatch={summary.get('seats_mismatch')} "
        f"seats_missing={summary.get('seats_missing')} "
        f"paid_calls={summary.get('paid_calls')}"
    )
    if path:
        print(f"[dual-source-diff] wrote {path}")
    else:
        print(json.dumps(summary, ensure_ascii=False))
    return 0 if report.get("overall_status") != "mismatch" else 1


if __name__ == "__main__":
    raise SystemExit(main())
