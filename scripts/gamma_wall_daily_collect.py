# -*- coding: utf-8 -*-
"""Daily Gamma Wall collector for GitHub Actions.

Resolves expiry in order:
1. env ``GAMMA_<CONTRACT>_EXPIRY``
2. latest PASS snapshot under ``data/gamma_wall/<CONTRACT>/`` if still after asof

Fails only when zero contracts produce a successful snapshot *and* the misses are
real errors (missing expiry config / quality FAIL). Empty CZCE day tables or
pre-settle futures gaps are treated as data-not-ready and exit 0 so scheduled
runs stay green when AkShare has not published yet — re-dispatch after settle.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gamma_wall import OBSERVE_MONTH, supported_contracts  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
CONTRACTS = supported_contracts(OBSERVE_MONTH)

# AkShare/CZCE lag markers — not config bugs; collect later the same day.
_NOT_READY_MARKERS = (
    "无返回行",
    "日盘未收/未结算前",
)


def is_data_not_ready(exc: BaseException) -> bool:
    msg = str(exc)
    return any(m in msg for m in _NOT_READY_MARKERS)


def _asof(explicit: str | None) -> str:
    if explicit:
        return explicit[:10]
    return date.today().strftime("%Y-%m-%d")  # runner should pass Asia/Shanghai date


def expiry_from_env(contract: str) -> str | None:
    key = f"GAMMA_{contract.upper()}_EXPIRY"
    val = (os.environ.get(key) or "").strip()
    return val or None


def expiry_from_snapshot(contract: str, asof: str, *, root: Path = ROOT) -> str | None:
    """Use most recent PASS snapshot's expiry if it is still strictly after asof."""
    folder = root / "data" / "gamma_wall" / contract.upper()
    if not folder.is_dir():
        return None
    best: tuple[str, str] | None = None  # (asof, expiry)
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        q = data.get("data_quality") or {}
        if str(q.get("status") or "").upper() != "PASS":
            continue
        snap_asof = str(data.get("asof") or "")[:10]
        expiry = str(data.get("expiry") or "")[:10]
        if len(expiry) != 10:
            continue
        try:
            if date.fromisoformat(expiry) <= date.fromisoformat(asof):
                continue
        except ValueError:
            continue
        if best is None or snap_asof >= best[0]:
            best = (snap_asof, expiry)
    return best[1] if best else None


def resolve_expiry(contract: str, asof: str, *, root: Path = ROOT) -> tuple[str | None, str]:
    env = expiry_from_env(contract)
    if env:
        return env, "env"
    snap = expiry_from_snapshot(contract, asof, root=root)
    if snap:
        return snap, "snapshot"
    return None, "missing"


def collect_one(contract: str, expiry: str, asof: str) -> dict[str, Any]:
    from gamma_wall import fetch_snapshot

    return fetch_snapshot(contract, expiry=expiry, trade_date=asof)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gamma Wall daily collect with expiry fallback")
    ap.add_argument("--date", default=None, help="asof YYYY-MM-DD (Asia/Shanghai)")
    ap.add_argument(
        "--contracts",
        default=",".join(CONTRACTS),
        help="comma-separated contracts",
    )
    args = ap.parse_args()
    asof = _asof(args.date)
    contracts = [c.strip().upper() for c in str(args.contracts).split(",") if c.strip()]
    ok_n = 0
    fail_n = 0
    skip_n = 0
    not_ready_n = 0
    for contract in contracts:
        expiry, src = resolve_expiry(contract, asof, root=ROOT)
        if not expiry:
            print(
                f"::notice::Skip {contract}: no GAMMA_{contract}_EXPIRY "
                f"and no usable PASS snapshot expiry after {asof}."
            )
            skip_n += 1
            continue
        print(f"[gamma] {contract} asof={asof} expiry={expiry} (via {src})")
        try:
            result = collect_one(contract, expiry, asof)
            out = ROOT / "data" / "gamma_wall" / contract / f"{asof}.json"
            print(
                f"[gamma] ok {contract} quality={((result.get('data_quality') or {}).get('status'))} → {out}"
            )
            ok_n += 1
        except Exception as exc:  # noqa: BLE001 — surface per-contract soft then tally
            if is_data_not_ready(exc):
                print(f"::notice::{contract} data not ready: {exc}")
                not_ready_n += 1
            else:
                print(f"::warning::{contract} failed: {exc}")
                fail_n += 1
    print(
        f"[gamma] summary ok={ok_n} fail={fail_n} "
        f"not_ready={not_ready_n} skip={skip_n}"
    )
    if ok_n > 0:
        return 0
    if fail_n == 0 and not_ready_n > 0:
        print(
            "::notice title=Gamma Wall deferred::"
            f"No validated snapshots for {asof}; CZCE/futures day tables not "
            "published yet. Re-run after settle (no config change needed)."
        )
        return 0
    print(
        "::error title=Gamma Wall collected nothing::"
        "No validated snapshots. Set repository Variables GAMMA_<CONTRACT>_EXPIRY "
        "(YYYY-MM-DD) or ensure data/gamma_wall has PASS snapshots with future expiry."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
