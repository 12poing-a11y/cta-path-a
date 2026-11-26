# -*- coding: utf-8 -*-
"""R8 PREREG_OOS sec. 8: 300k diagnostic groups (A300k, B300k, C300k), long window, official path + 5% guard.
Output archive/R8/DIAG300K/<group>/.  Run once; technical re-runs (crash / env error) must be disclosed.  Report only."""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import long_sample as ls  # noqa: E402


def main() -> int:
    bundle = ls.build_official_pack(guard_pct=ls.GUARD_PCT)
    info = bundle[3]
    assert info["max_loaded_date"] <= ls.W1, info["max_loaded_date"]
    print("pack", info["max_loaded_date"], info["pack_sha256"], flush=True)
    for kind in "ABC":
        g = f"{kind}300k"
        t0 = time.time()
        r = ls.run_group(g, data_source="official", guard_pct=ls.GUARD_PCT, out_dir=HERE / "DIAG300K" / g, pack_bundle=bundle)
        print(g, round(time.time() - t0), "s", {s: (r[s]["ret_pct"], r[s]["max_dd_pct"], r[s]["closed_trades"]) for s in ("base", "stress")}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
