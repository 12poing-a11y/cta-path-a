# -*- coding: utf-8 -*-
"""Shadow replay of Path-A backtest from input snapshot (no network, no formal overwrite)."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import historical_backtest as hb  # noqa: E402

# Legacy default paths (fix3 / freeze tests import this module for side effects).
_DEFAULT_SNAP = ROOT / "archive/snapshots/bt_input_20261113_d246813d911a.json"
_DEFAULT_BT = ROOT / "historical_backtest_latest.json"

snap: dict | None = None
formal: dict | None = None


def load_inputs(snap_path: Path | str, bt_path: Path | str) -> tuple[dict, dict]:
    snap_obj = json.loads(Path(snap_path).read_text(encoding="utf-8"))
    bt_obj = json.loads(Path(bt_path).read_text(encoding="utf-8"))
    return snap_obj, bt_obj


def apply_freeze(snap_obj: dict, bt_obj: dict) -> None:
    """Monkeypatch: contract_pack from BT; member/carry already lagged in snapshot."""
    hb.prepare_pack_for_execution = lambda pack, root=None: bt_obj.get("contract_pack") or {}
    hb.load_member_seats = lambda dates, codes: snap_obj["member"]
    hb.load_member_changes = lambda dates, codes: snap_obj["member"]
    hb.lag_member = lambda m, dates, lag: m
    hb.load_curves = lambda codes: {
        c: ({"carry": v} if not (isinstance(v, dict) and "carry" in v) else v)
        for c, v in (snap_obj.get("carry") or {}).items()
    }
    hb.lag_curves_carry = lambda curves, dates, lag: curves


def make_pack(bars=None, snap_obj: dict | None = None):
    """Build cfg + series pack. ``snap_obj`` defaults to module-level ``snap`` (legacy)."""
    s = snap_obj if snap_obj is not None else snap
    if s is None:
        raise ValueError("make_pack needs snap_obj or module-level snap")
    p = hb._load_cfg()
    bars = bars or s["bars"]
    series = {}
    for u in p["cfg"]["symbols"]:
        c = u["code"]
        if c in bars:
            series[c] = {"meta": dict(u), "hist": copy.deepcopy(bars[c])}
    return p, (series, dict(s.get("errors") or {}), dict(s.get("sources") or {}))


def run(p=None, pack=None, **kw):
    if p is None or pack is None:
        p, pack = make_pack()
    mode = p["entry_filter"]
    return hb._simulate_cfg(p, mode, pack=pack, **kw)


def _load_legacy_globals() -> None:
    global snap, formal
    if not _DEFAULT_SNAP.is_file() or not _DEFAULT_BT.is_file():
        return
    snap = json.loads(_DEFAULT_SNAP.read_text(encoding="utf-8"))
    formal = json.loads(_DEFAULT_BT.read_text(encoding="utf-8"))
    apply_freeze(snap, formal)


_load_legacy_globals()


def main(argv: list[str] | None = None) -> int:
    global snap, formal
    ap = argparse.ArgumentParser(description="Offline Path-A replay from input snapshot")
    ap.add_argument(
        "--bt",
        default=str(_DEFAULT_BT),
        help="BT result JSON providing contract_pack (default: root formal latest)",
    )
    ap.add_argument(
        "--snap",
        default=None,
        help="Input snapshot JSON (default: --bt input_snapshot.path)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Write full run() result JSON (optional)",
    )
    ap.add_argument(
        "--contracts",
        default=None,
        help="contract bundle (default: the snapshot's embedded contract_bars, else its *.contracts.json[.gz])",
    )
    ap.add_argument(
        "--contract-root",
        default=None,
        help="read month contracts from the local cache under this root instead of a bundle",
    )
    args = ap.parse_args(argv)

    bt_path = Path(args.bt)
    if not bt_path.is_absolute():
        bt_path = ROOT / bt_path
    bt_obj = json.loads(bt_path.read_text(encoding="utf-8"))
    if args.snap:
        snap_path = Path(args.snap)
        if not snap_path.is_absolute():
            snap_path = ROOT / snap_path
    else:
        rel = (bt_obj.get("input_snapshot") or {}).get("path")
        if not rel:
            print("[replay] --bt has no input_snapshot.path; pass --snap", file=sys.stderr)
            return 2
        snap_path = ROOT / Path(rel)
    if not snap_path.is_file():
        print(f"[replay] snapshot missing: {snap_path}", file=sys.stderr)
        return 2

    snap_obj, _ = load_inputs(snap_path, bt_path)
    apply_freeze(snap_obj, bt_obj)
    # Keep module globals in sync for any nested callers.
    snap, formal = snap_obj, bt_obj
    p, pack = make_pack(snap_obj=snap_obj)
    from research.data_quality.contract_store import CacheContractStore, load_bundle, snapshot_store

    if args.contract_root:
        store = CacheContractStore(Path(args.contract_root))
    elif args.contracts:
        store = load_bundle(args.contracts)
    else:
        store = snapshot_store(snap_obj, snap_path)
        if store is None:
            print("[replay] snapshot has no contract bundle; falling back to the local contract cache", file=sys.stderr)
            store = CacheContractStore(ROOT)
    print(f"[replay] contracts: {store!r}")
    out = run(p, pack, contract_root=store)
    keys = [
        "ret_pct",
        "max_dd_pct",
        "closed_trades",
        "trade_win_rate",
        "expectancy_r",
        "exits",
        "proxy_entry_n",
        "contract_entry_n",
        "same_day_exit_n",
        "minute_stop_exits",
        "daily_exit_fallback_checks",
        "conclusion",
    ]
    print({k: out.get(k) for k in keys})
    print("ref_bt", {k: bt_obj.get(k) for k in keys})
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.setdefault("input_snapshot", bt_obj.get("input_snapshot"))
        out["replay_contract_source"] = repr(store)
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[replay] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
