#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit exits against same-basis daily OHLC (R0 tool; R6b-fix adds roll checks).

Checks (every one must mirror the engine, never be loosened to reach 0):

* stop/target exits touch the daily bar the engine priced them on
  (continuous bar, or the held contract's own bar when the actual main moved
  off it, or the real contract bar for contract fills);
* (i)   exit date earlier than entry date → mismatch;
* (ii)  continuous_proxy exit price must lie inside [low, high] of the HELD
        contract's exit-day bar;
* (iii) exit on an actual-main roll day priced off the NEW main although the
        position holds the old contract → mismatch;
* contract fills priced by ``continuous + basis_off`` are only legitimate while
  the actual main of that day equals the main on the day ``basis_off`` was taken.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Float slack for [low, high] membership only (exit prices are rounded to 4 dp).
_EPS = 1e-6


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
            # Only real contract_* keys — do NOT fall back to continuous via .get default
            # when the key is missing (that was the R1 false-mismatch bug).
            if (
                bar.get("contract_high") is None
                or bar.get("contract_low") is None
                or bar.get("contract_close") is None
            ):
                return None
            close = float(bar["contract_close"])
            o = (
                float(bar["contract_open"])
                if bar.get("contract_open") is not None
                else close
            )
            return o, float(bar["contract_high"]), float(bar["contract_low"]), close
        o, h, lo, c = bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close")
        return float(o), float(h), float(lo), float(c)
    except (TypeError, ValueError):
        return None


def _contract_day_ohlc(
    *,
    root: Path,
    snap_bars: list[dict] | None,
    code: str,
    contract: str,
    day: str,
    main_map: Any,
) -> tuple[tuple[float, float, float, float] | None, str]:
    """(o,h,l,c), source for ``contract`` on ``day`` — mirrors engine ``_contract_day_bar``."""
    contract = str(contract or "").upper()
    b = _bar_by_date(snap_bars, day)
    if (
        b is not None
        and b.get("contract_high") is not None
        and b.get("contract_low") is not None
        and b.get("contract_close") is not None
        and str(b.get("contract") or "").upper() in ("", contract)
    ):
        o = _ohlc(b, basis="contract")
        if o is not None:
            return o, "snap_contract"
    if contract:
        cb = _bar_by_date(_load_cache_contract(root, contract), day)
        if cb is not None:
            o = _ohlc(cb, basis="continuous")
            if o is not None:
                return o, "cache_contract"
    if main_map is not None and b is not None and main_map.main(code, day) == contract:
        o = _ohlc(b, basis="continuous")
        if o is not None:
            return o, "continuous_is_main"
    return None, "missing"


def _basis_off_before(
    *,
    root: Path,
    snap_bars: list[dict],
    code: str,
    fill_contract: str,
    day: str,
    main_map: Any,
) -> tuple[float | None, str | None]:
    """Engine's last (contract_close − continuous close) before ``day`` and its main.

    The engine refreshes ``basis_off`` on every day it holds a real bar for the fill
    contract — snapshot ``contract_*`` first, otherwise ``.cache/contracts``.
    """
    want = fill_contract.upper()
    cache_by_day = {
        str(r.get("date") or "")[:10]: r for r in _load_cache_contract(root, want)
    }
    off = None
    off_main = None
    for b in snap_bars:
        d = str(b.get("date") or "")[:10]
        if d >= day:
            break
        close_c = None
        if (
            b.get("contract_close") is not None
            and str(b.get("contract") or "").upper() in ("", want)
        ):
            close_c = b.get("contract_close")
        elif d in cache_by_day:
            close_c = cache_by_day[d].get("close")
        if close_c is None:
            continue
        try:
            off = float(close_c) - float(b["close"])
            off_main = main_map.main(code, d) if main_map is not None else None
        except (TypeError, ValueError, KeyError):
            continue
    return off, off_main


def resolve_day_bar(
    *,
    root: Path,
    snap: dict | None,
    code: str,
    day: str,
    basis: str,
    fill_contract: str | None,
    held_contract: str | None = None,
    main_map: Any = None,
) -> tuple[dict | None, str, str | None]:
    """
    Return (bar, source, skip_reason).
    skip_reason is set when the trade should be skipped (not counted as mismatch);
    ``"mismatch_*"`` skip reasons are reported as mismatches by the caller.
    """
    snap_bars = None
    if snap and isinstance(snap.get("bars"), dict):
        snap_bars = snap["bars"].get(code)
        bar = _bar_by_date(snap_bars, day)
        if bar is None and basis == "continuous_proxy":
            return None, "snap_missing_day", "skipped_no_bar"
        if basis == "continuous_proxy" and bar is not None:
            # Engine: while the actual main differs from the held contract, the day is
            # priced on the HELD contract's own bar; otherwise on the continuous bar.
            held = str(held_contract or "").upper()
            cur_main = main_map.main(code, day) if main_map is not None else None
            if held and cur_main is not None and cur_main != held:
                o4, src = _contract_day_ohlc(
                    root=root,
                    snap_bars=snap_bars,
                    code=code,
                    contract=held,
                    day=day,
                    main_map=main_map,
                )
                if o4 is None:
                    return None, "held_bar_missing", "skipped_no_bar"
                return (
                    {"date": day, "open": o4[0], "high": o4[1], "low": o4[2], "close": o4[3]},
                    f"held_{src}",
                    None,
                )
            return bar, "snap_continuous", None
        if basis == "contract" and bar is not None:
            want = str(fill_contract or "").strip().upper()
            # Real contract_* on snap
            if (
                bar.get("contract_high") is not None
                and bar.get("contract_low") is not None
                and bar.get("contract_close") is not None
            ):
                return bar, "snap_contract", None
            # Exact-contract cache
            if want:
                cbar = _bar_by_date(_load_cache_contract(root, want), day)
                if cbar is not None:
                    return cbar, "cache_contract", None
            # Engine proxy: continuous + last basis_off — only while the actual main of
            # ``day`` equals the main on the day basis_off was measured (R6b-fix).
            off, off_main = (
                _basis_off_before(
                    root=root,
                    snap_bars=snap_bars or [],
                    code=code,
                    fill_contract=want,
                    day=day,
                    main_map=main_map,
                )
                if want
                else (None, None)
            )
            if off is not None:
                if main_map is not None and main_map.usable(code):
                    cur_main = main_map.main(code, day)
                    if cur_main is None or cur_main != off_main:
                        return None, "proxy_across_roll", "mismatch_proxy_across_roll"
                try:
                    proxied = {
                        "date": day,
                        "open": float(bar["open"]) + off,
                        "high": float(bar["high"]) + off,
                        "low": float(bar["low"]) + off,
                        "close": float(bar["close"]) + off,
                    }
                    return proxied, "snap_proxied", None
                except (TypeError, ValueError, KeyError):
                    pass
            return None, "contract_unpriced", "skipped_no_bar"

    # Snapshot missing / unusable → cache fallback
    if basis == "continuous_proxy":
        bars = _load_cache_history(root, code)
        bar = _bar_by_date(bars, day)
        if bar is None:
            return None, "cache_history_missing", "skipped_no_bar"
        return bar, "cache_history", None

    # contract basis without snap
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


def _build_audit_main_map(root: Path, snap: dict | None, ticks: dict[str, float]):
    if not snap or not isinstance(snap.get("bars"), dict):
        return None
    try:
        from research.data_quality.main_map import build_main_map
    except Exception:  # noqa: BLE001
        return None
    series = {
        code: {"meta": {"tick": ticks.get(code) or 0.0}, "hist": bars}
        for code, bars in snap["bars"].items()
    }
    return build_main_map(series, root=root)


def audit_bt(
    bt: dict,
    *,
    root: Path | None,
    snap: dict | None,
    tick_by_code: dict[str, float] | None = None,
) -> dict:
    root = Path(root) if root is not None else ROOT
    ticks = tick_by_code or _tick_map(root)
    main_map = _build_audit_main_map(root, snap, ticks)
    mismatches: list[dict] = []
    checked = 0
    skipped_proxied = 0
    skipped_no_bar = 0
    n_order = n_range = n_roll = 0
    range_skipped = 0
    for t in bt.get("closed_pnls") or []:
        reason = str(t.get("reason") or "")
        code = str(t.get("code") or "")
        day = str(t.get("date") or "")[:10]
        entry_day = str(t.get("entry_date") or "")[:10]
        basis = str(t.get("fill_price_basis") or "continuous_proxy").strip().lower()
        if basis not in ("continuous_proxy", "contract"):
            basis = "continuous_proxy"
        fill_contract = t.get("fill_contract")
        held_contract = t.get("held_contract")
        problems: list[str] = []
        try:
            exit_px = float(t["exit"]) if t.get("exit") is not None else None
        except (TypeError, ValueError):
            exit_px = None

        # (i) exit before entry
        if entry_day and day:
            n_order += 1
            if day < entry_day:
                problems.append("exit_before_entry")

        bar = None
        source = ""
        stop_f = target_f = None
        o_h_l_c: tuple[float, float, float, float] | None = None
        need_bar = reason in ("stop", "target") or (
            basis == "continuous_proxy" and exit_px is not None
        )
        if need_bar and day:
            bar, source, skip = resolve_day_bar(
                root=root,
                snap=snap,
                code=code,
                day=day,
                basis=basis,
                fill_contract=str(fill_contract) if fill_contract else None,
                held_contract=str(held_contract) if held_contract else None,
                main_map=main_map,
            )
            if skip == "mismatch_proxy_across_roll":
                problems.append("proxy_across_roll")
            elif skip == "skipped_proxied":
                skipped_proxied += 1
            elif skip == "skipped_no_bar" or bar is None:
                if reason in ("stop", "target"):
                    skipped_no_bar += 1
                else:
                    range_skipped += 1
            else:
                # snap_contract uses contract_*; cache / proxied / continuous use plain OHLC
                o_h_l_c = _ohlc(bar, basis="contract" if source == "snap_contract" else "continuous")
                if o_h_l_c is None:
                    if reason in ("stop", "target"):
                        skipped_no_bar += 1
                    else:
                        range_skipped += 1

        tol = float(ticks.get(code) or 0) * 1.0
        did_check = False
        conservative_target_gap = False
        if o_h_l_c is not None and reason in ("stop", "target"):
            try:
                stop_f = float(t["stop"]) if t.get("stop") is not None else None
                target_f = float(t["target"]) if t.get("target") is not None else None
            except (TypeError, ValueError):
                stop_f = target_f = None
                skipped_no_bar += 1
            else:
                did_check = True
                checked += 1
                if not exit_touches_daily(
                    direction=str(t.get("direction") or ""),
                    reason=reason,
                    stop=stop_f,
                    target=target_f,
                    high=o_h_l_c[1],
                    low=o_h_l_c[2],
                    tol=tol,
                ):
                    problems.append("stop_target_not_touched")

        # (ii) continuous_proxy exit price inside the held contract's [low, high]
        if (
            basis == "continuous_proxy"
            and exit_px is not None
            and o_h_l_c is not None
            and (source in ("snap_continuous", "cache_history") or source.startswith("held_"))
        ):
            n_range += 1
            if not (o_h_l_c[2] - _EPS <= exit_px <= o_h_l_c[1] + _EPS):
                problems.append("exit_outside_held_bar_range")
                # Informational only (still counted as a mismatch): R3 convention fills a
                # target that the bar gapped through AT the target, i.e. at a price worse
                # than anything the bar traded — never better than reality.
                d_ = str(t.get("direction") or "")
                if reason == "target" and (
                    (d_ == "多" and exit_px < o_h_l_c[2] - _EPS)
                    or (d_ == "空" and exit_px > o_h_l_c[1] + _EPS)
                ):
                    conservative_target_gap = True

        # (iii) roll day: exit priced off the NEW main while holding the old contract
        if (
            exit_px is not None
            and main_map is not None
            and day
            and entry_day
            and entry_day < day
        ):
            prev_main = None
            hist = (snap or {}).get("bars", {}).get(code) or []
            for hb in hist:
                hd = str(hb.get("date") or "")[:10]
                if hd >= day:
                    break
                prev_main = main_map.main(code, hd) or prev_main
            new_main = main_map.main(code, day)
            held = str(
                (held_contract if basis == "continuous_proxy" else fill_contract) or ""
            ).upper()
            if (
                prev_main is not None
                and new_main is not None
                and prev_main != new_main
                and held
                and held != new_main
            ):
                n_roll += 1
                snap_bars = (snap or {}).get("bars", {}).get(code) or []
                new_ohlc, _s1 = _contract_day_ohlc(
                    root=root,
                    snap_bars=snap_bars,
                    code=code,
                    contract=new_main,
                    day=day,
                    main_map=main_map,
                )
                old_ohlc, _s2 = _contract_day_ohlc(
                    root=root,
                    snap_bars=snap_bars,
                    code=code,
                    contract=held,
                    day=day,
                    main_map=main_map,
                )
                in_new = new_ohlc is not None and (
                    new_ohlc[2] - _EPS <= exit_px <= new_ohlc[1] + _EPS
                )
                in_old = old_ohlc is not None and (
                    old_ohlc[2] - _EPS <= exit_px <= old_ohlc[1] + _EPS
                )
                if in_new and not in_old:
                    problems.append("roll_day_exit_from_new_main")

        if problems:
            o_, h_, l_, c_ = o_h_l_c if o_h_l_c is not None else (None, None, None, None)
            mismatches.append(
                {
                    "date": day,
                    "code": code,
                    "direction": t.get("direction"),
                    "lots": t.get("lots"),
                    "reason": reason,
                    "entry_date": entry_day or None,
                    "exit": exit_px,
                    "stop": stop_f,
                    "target": target_f,
                    "open": o_,
                    "high": h_,
                    "low": l_,
                    "close": c_,
                    "fill_price_basis": basis,
                    "fill_contract": fill_contract,
                    "held_contract": held_contract,
                    "bar_source": source,
                    "problems": problems,
                    "roll_new_main_exit": "roll_day_exit_from_new_main" in problems,
                    "conservative_target_gap_fill": conservative_target_gap,
                }
            )
        _ = did_check
    return {
        "checked": checked,
        "mismatches": len(mismatches),
        "mismatches_excluding_conservative_target_gap": sum(
            1
            for m in mismatches
            if not (m["conservative_target_gap_fill"] and m["problems"] == ["exit_outside_held_bar_range"])
        ),
        "skipped_proxied": skipped_proxied,
        "skipped_no_bar": skipped_no_bar,
        "checks": {
            "entry_order_checked": n_order,
            "continuous_range_checked": n_range,
            "continuous_range_skipped_no_bar": range_skipped,
            "roll_day_exits_checked": n_roll,
        },
        "mismatch_trades": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit exits vs daily OHLC")
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
        f"skipped_proxied={report['skipped_proxied']} skipped_no_bar={report['skipped_no_bar']} "
        f"checks={report['checks']}"
    )
    for m in report["mismatch_trades"]:
        print(
            f"  MISMATCH {m['date']} {m['code']} {m['direction']} {m['reason']} "
            f"stop={m['stop']} target={m['target']} OHLC={m['open']}/{m['high']}/{m['low']}/{m['close']} "
            f"basis={m['fill_price_basis']} src={m['bar_source']} problems={m['problems']}"
        )
    if args.fail_on_mismatch and report["mismatches"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
