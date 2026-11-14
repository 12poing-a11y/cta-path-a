# -*- coding: utf-8 -*-
"""Refresh shadow attribution ledger + category win-rate summary.

Research only — does not touch paper_book / Path-A entry_filter.

Usage:
  python scripts/run_shadow_perf.py
  python scripts/run_shadow_perf.py --asof 2026-11-13
  python scripts/run_shadow_perf.py --backfill-history --max-days 40
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.shadow_perf import refresh_shadow_perf  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Shadow attribution ledger (Research)")
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD or YYYYMMDD")
    ap.add_argument(
        "--backfill-history",
        action="store_true",
        help="Also ingest archive L1 + sentiment shadow history",
    )
    ap.add_argument("--max-days", type=int, default=60, help="History window when backfilling")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    out = refresh_shadow_perf(
        args.root,
        asof=args.asof,
        backfill_history=bool(args.backfill_history),
        max_history_days=int(args.max_days),
        write=True,
    )
    primary = (out.get("summary") or {}).get("by_bucket") or []
    enough = sum(1 for r in primary if r.get("enough"))
    print(
        json.dumps(
            {
                "ok": out.get("ok"),
                "asof": out.get("asof"),
                "n_ledger": out.get("n_ledger"),
                "n_candidates_new": out.get("n_candidates_new"),
                "bucket_rows": len(primary),
                "bucket_enough": enough,
                "path": out.get("path"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
