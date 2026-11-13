# -*- coding: utf-8 -*-
"""Backfill Sina exact-contract daily bars into .cache/contracts/ for fill overlay.

Usage (repo root):
  python lab/scripts/backfill_front_month_daily.py
  python lab/scripts/backfill_front_month_daily.py --month 2701
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_data import fetch_sina_exact_contract  # noqa: E402
from research.execution.contract_pack import (  # noqa: E402
    default_front_month,
    front_contract_for,
    load_exact_contract_daily,
    overlay_contract_fills,
)


def save_contract(contract: str, bars: list[dict], root: Path) -> Path:
    out_dir = root / ".cache" / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{contract.upper()}.json"
    payload = {
        "contract": contract.upper(),
        "n": len(bars),
        "bars": bars,
        "source": "sina_exact_contract",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="YYMM e.g. 2701")
    ap.add_argument("--sleep", type=float, default=0.35)
    ap.add_argument("--codes", default="", help="comma codes; default=universe")
    args = ap.parse_args(argv)

    month = args.month or default_front_month(ROOT)
    uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    codes = [c.strip().upper() for c in args.codes.split(",") if c.strip()]
    if not codes:
        codes = [str(s["code"]).upper() for s in uni.get("symbols") or [] if s.get("code")]

    rows = []
    for i, code in enumerate(codes):
        contract = front_contract_for(code, month)
        print(f"[contracts] {i+1}/{len(codes)} fetch {contract}...")
        try:
            bars = fetch_sina_exact_contract(contract)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR {exc}")
            rows.append({"code": code, "contract": contract, "ok": False, "error": str(exc)[:120]})
            continue
        if not bars:
            print("  empty")
            rows.append({"code": code, "contract": contract, "ok": False, "n": 0})
        else:
            path = save_contract(contract, bars, ROOT)
            print(f"  n={len(bars)} {bars[0]['date']}→{bars[-1]['date']} → {path.relative_to(ROOT)}")
            rows.append(
                {
                    "code": code,
                    "contract": contract,
                    "ok": True,
                    "n": len(bars),
                    "start": bars[0]["date"],
                    "end": bars[-1]["date"],
                }
            )
        time.sleep(max(0.0, float(args.sleep)))

    # Coverage vs a minimal continuous-length proxy using existing pack overlay
    series = {}
    for code in codes:
        # Build synthetic hist from continuous CODE0 if available via contracts loader length only
        c = front_contract_for(code, month)
        bars = load_exact_contract_daily(c, root=ROOT)
        # For overlay test use contract bars as hist too
        series[code] = {"meta": {"code": code}, "hist": bars[-260:] if bars else []}
    report = overlay_contract_fills(series, month=month, root=ROOT, min_coverage=0.3)
    out = {
        "month": month,
        "rows": rows,
        "ok_n": sum(1 for r in rows if r.get("ok")),
        "overlay": report,
    }
    dest = ROOT / "lab" / "research" / "contracts" / "front_month_backfill_latest.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[contracts] ok={out['ok_n']}/{len(rows)} wrote {dest.relative_to(ROOT)}")
    return 0 if out["ok_n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
