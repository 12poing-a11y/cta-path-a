# -*- coding: utf-8 -*-
"""R7a-D3: companion contract bundle for an existing input snapshot (snapshot file left untouched).

usage: python archive/R7/_make_snapshot_bundle.py SNAPSHOT [--root DIR] [--max-mb 30]
Writes SNAPSHOT-stem.contracts.json (or .contracts.json.gz above --max-mb): every listing-calendar
candidate of every bar date in the snapshot, bars <= snapshot end, read from the cache under --root.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    from research.data_quality.contract_cache import listed_candidates
    from research.data_quality.contract_store import CacheContractStore, build_bundle, write_bundle

    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--max-mb", type=float, default=30.0)
    a = ap.parse_args(argv)
    snap_path = Path(a.snapshot)
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    series = {c: {"hist": h} for c, h in snap["bars"].items()}
    wanted = sorted({c for v in listed_candidates(series).values() for c in v})
    bundle = build_bundle(
        CacheContractStore(Path(a.root)), wanted, end=snap.get("end"),
        meta={"source": "local .cache/contracts (R7a-D3)", "snapshot": snap_path.name},
    )
    stem = snap_path.name[: -len(".json")]
    out = snap_path.with_name(f"{stem}.contracts.json")
    write_bundle(bundle, out)
    mb = out.stat().st_size / 1e6
    if mb > a.max_mb:
        gz = out.with_name(out.name + ".gz")
        write_bundle(bundle, gz)
        out.unlink()
        out = gz
    print(
        f"wanted={len(wanted)} contracts_with_bars={bundle['n_contracts']} bars={bundle['n_bars']} "
        f"missing={len(bundle['missing_contracts'])} -> {out} ({out.stat().st_size:,} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
