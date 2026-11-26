# -*- coding: utf-8 -*-
"""R8 long-sample formal run: 9 groups (A/B/C x 800k/1000k/1200k), Base + Stress, official data, 5% volume guard.

Output: archive/R8/OOS/<group>/ (result_base.json, result_stress.json, run_info.json).  The pack is built once; a final
re-run of A1000k/base must be identical to the first (the pack must not be mutated by the engine).
Forbidden here (PREREG_OOS): 300k diagnostic groups, shadow, anything touching the 216-day window.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import long_sample as ls  # noqa: E402

OUT = HERE / "OOS"


def _h(rec):
    return hashlib.sha256(json.dumps([rec["trades"], rec["equity_curve"]], sort_keys=True, default=str).encode()).hexdigest()


def main() -> int:
    t0 = time.time()
    bundle = ls.build_official_pack(guard_pct=ls.GUARD_PCT)
    pack, main_map, store, info = bundle
    print("pack", round(time.time() - t0), "s", {k: info[k] for k in ("max_loaded_date", "roll_events")}, flush=True)
    assert info["max_loaded_date"] <= ls.W1, info["max_loaded_date"]
    first = None
    for lvl in ("800k", "1000k", "1200k"):
        for kind in ("A", "B", "C"):
            g = f"{kind}{lvl}"
            t1 = time.time()
            r = ls.run_group(g, data_source="official", guard_pct=ls.GUARD_PCT, out_dir=OUT / g, pack_bundle=bundle)
            if g == "A1000k":
                first = _h(r["base"])
            print(g, round(time.time() - t1), "s", {s: (r[s]["ret_pct"], r[s]["max_dd_pct"], r[s]["closed_trades"], r[s]["roll_shifted"]) for s in ("base", "stress")}, flush=True)
    again = ls.run_group("A1000k", data_source="official", guard_pct=ls.GUARD_PCT, pack_bundle=bundle)
    assert _h(again["base"]) == first, "pack mutated by the engine: A1000k re-run differs"
    print("determinism check: A1000k re-run identical", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
