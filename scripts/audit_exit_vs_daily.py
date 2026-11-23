#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit stop/target exits against same-basis daily OHLC (R0 baseline tool)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _tick_map(root: Path) -> dict[str, float]:
    uni = _load_json(root / "universe.json")
    out: dict[str, float] = {}
    for u in uni.get("symbols") or []:
        code = str(u.get("code") or "").strip()
        if not code:
            continue
        try:
            out[code] = float(u.get("tick") or 0)
        except (TypeError, ValueError):
            out[code] = 0.0
    return out


def _bar_by_date(bars: list[dict] | None, day: str) -> dict | None:
    if not bars:
        return None
    for b in bars:
        if str(b.get("date") or "")[:10] == day:
            return b
    return None


def _load_cache_history(root: Path, code: str) -> list[dict]:
    p = root / ".cache" / "history" / f"{code}0.json"
    if not p.is_file():
        return []
    data = _load_json(p)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("bars") or data.get("hist") or [])
    return []


def _load_cache_contract(root: Path, contract: str) -> list[dict]:
    p = root / ".cache" / "contracts" / f"{contract}.json"
    if not p.is_file():
        return []
    data = _load_json(p)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("bars") or data.get("hist") or [])
    return []


def _ohlc(bar: dict, *, basis: str) -> tuple[float, float, float, float] | None:
    try:
        if basis == "contract":
            o = bar.get("contract_open", bar.get("open"))
            h = bar.get("contract_high", bar.get("high"))
            lo = bar.get("contract_low", bar.get("low"))
            c = bar.get("contract_close", bar.get("close"))
        else:
            o, h, lo, c = bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close")
        return float(o), float(h), float(lo), float(c)
    except (TypeError, ValueError):
        return None


def resolve_day_bar(
    *,
    root: Path,
    snap: dict | None,
    code: str,
    day: str,
    basis: str,
    fill_contract: str | None,
) -> tuple[dict | None, str, str | None]:
    """
    Return (bar, source, skip_reason).
    skip_reason is set when the trade should be skipped (not counted as mismatch).
    """
    if snap and isinstance(snap.get("bars"), dict):
        bars = snap["bars"].get(code)
        bar = _bar_by_date(bars, day)
        if bar is None:
            return None, "snap_missing_day", "skipped_no_bar"
        if basis == "contract":
            bar_c = str(bar.get("contract") or "").strip().upper()
            want = str(fill_contract or "").strip().upper()
            if want and bar_c and bar_c != want:
                return None, "snap_proxied_contract", "skipped_proxied"
            # contract fields may still be absent → fall through to cache
            ohlc = _ohlc(bar, basis="contract")
            if ohlc is not None and (
                bar.get("contract_high") is not None
                or bar.get("contract_low") is not None
                or (want and bar_c == want)
            ):
                return bar, "snap_contract", None
            # try continuous fields only if same contract stamped
            if want and bar_c == want:
                return bar, "snap_same_contract_cont_fields", None
            if want and bar_c and bar_c != want:
                return None, "snap_proxied_contract", "skipped_proxied"
        else:
            return bar, "snap_continuous", None

    # Snapshot missing / unusable → cache fallback
    if basis == "continuous_proxy":
        bars = _load_cache_history(root, code)
        bar = _bar_by_date(bars, day)
        if bar is None:
            return None, "cache_history_missing", "skipped_no_bar"
        return bar, "cache_history", None

    # contract basis
    if not fill_contract:
        return None, "no_fill_contract", "skipped_no_bar"
    bars = _load_cache_contract(root, fill_contract)
    bar = _bar_by_date(bars, day)
    if bar is None:
        return None, "cache_contract_missing", "skipped_no_bar"
    return bar, "cache_contract", None


def exit_touches_daily(
    *,
    direction: str,
    reason: str,
    stop: float | None,
    target: float | None,
    high: float,
    low: float,
    tol: float,
) -> bool:
    d = str(direction)
    r = str(reason)
    if r == "stop":
        if stop is None:
            return False
        if d == "多":
            return low <= float(stop) + tol
        return high >= float(stop) - tol
    if r == "target":
        if target is None:
            return False
        if d == "多":
            return high >= float(target) - tol
        return low <= float(target) + tol
    return True


def audit_bt(
    bt: dict,
    *,
    root: Path | None,
    snap: dict | None,
    tick_by_code: dict[str, float] | None = None,
) -> dict:
    root = Path(root) if root is not None else ROOT
    ticks = tick_by_code or _tick_map(root)
    mismatches: list[dict] = []
    checked = 0
    skipped_proxied = 0
    skipped_no_bar = 0
    for t in bt.get("closed_pnls") or []:
        reason = str(t.get("reason") or "")
        if reason not in ("stop", "target"):
            continue
        code = str(t.get("code") or "")
        day = str(t.get("date") or "")[:10]
        basis = str(t.get("fill_price_basis") or "continuous_proxy").strip().lower()
        if basis not in ("continuous_proxy", "contract"):
            basis = "continuous_proxy"
        fill_contract = t.get("fill_contract")
        bar, source, skip = resolve_day_bar(
            root=root,
            snap=snap,
            code=code,
            day=day,
            basis=basis,
            fill_contract=str(fill_contract) if fill_contract else None,
        )
        if skip == "skipped_proxied":
            skipped_proxied += 1
            continue
        if skip == "skipped_no_bar" or bar is None:
            skipped_no_bar += 1
            continue
        ohlc = _ohlc(bar, basis=basis if source.startswith("snap") or source == "cache_contract" else "continuous")
        if ohlc is None:
            # continuous fields for cache_history / snap_continuous
            ohlc = _ohlc(bar, basis="continuous")
        if ohlc is None:
            skipped_no_bar += 1
            continue
        _o, high, low, _c = ohlc
        tol = float(ticks.get(code) or 0) * 1.0
        stop = t.get("stop")
        target = t.get("target")
        try:
            stop_f = float(stop) if stop is not None else None
            target_f = float(target) if target is not None else None
        except (TypeError, ValueError):
            skipped_no_bar += 1
            continue
        checked += 1
        ok = exit_touches_daily(
            direction=str(t.get("direction") or ""),
            reason=reason,
            stop=stop_f,
            target=target_f,
            high=high,
            low=low,
            tol=tol,
        )
        if not ok:
            mismatches.append(
                {
                    "date": day,
                    "code": code,
                    "direction": t.get("direction"),
                    "lots": t.get("lots"),
                    "reason": reason,
                    "stop": stop_f,
                    "target": target_f,
                    "open": _o,
                    "high": high,
                    "low": low,
                    "close": _c,
                    "fill_price_basis": basis,
                    "fill_contract": fill_contract,
                    "bar_source": source,
                }
            )
    return {
        "checked": checked,
        "mismatches": len(mismatches),
        "skipped_proxied": skipped_proxied,
        "skipped_no_bar": skipped_no_bar,
        "mismatch_trades": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit stop/target exits vs daily OHLC")
    ap.add_argument("--bt", default=str(ROOT / "historical_backtest_latest.json"))
    ap.add_argument("--snap", default=None, help="Input snapshot (default: --bt input_snapshot.path)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fail-on-mismatch", action="store_true")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)

    root = Path(args.root)
    bt_path = Path(args.bt)
    if not bt_path.is_absolute():
        bt_path = root / bt_path
    bt = _load_json(bt_path)

    snap = None
    snap_path = None
    if args.snap:
        snap_path = Path(args.snap)
        if not snap_path.is_absolute():
            snap_path = root / snap_path
    else:
        rel = (bt.get("input_snapshot") or {}).get("path")
        if rel:
            snap_path = root / Path(rel)

    if snap_path is not None and snap_path.is_file():
        snap = _load_json(snap_path)
    # else: cache fallback inside resolve_day_bar

    report = audit_bt(bt, root=root, snap=snap)
    report["bt_path"] = str(bt_path)
    report["snap_path"] = str(snap_path) if snap_path else None
    report["snap_loaded"] = snap is not None

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"[audit] wrote {out_path}")
    print(
        f"[audit] checked={report['checked']} mismatches={report['mismatches']} "
        f"skipped_proxied={report['skipped_proxied']} skipped_no_bar={report['skipped_no_bar']}"
    )
    for m in report["mismatch_trades"]:
        print(
            f"  MISMATCH {m['date']} {m['code']} {m['direction']} {m['reason']} "
            f"stop={m['stop']} target={m['target']} OHLC={m['open']}/{m['high']}/{m['low']}/{m['close']} "
            f"basis={m['fill_price_basis']} src={m['bar_source']}"
        )
    if args.fail_on_mismatch and report["mismatches"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
