# -*- coding: utf-8 -*-
"""R5a: cold-cache cost of ``_ensure_contracts`` (what a CI checkout with empty .cache/contracts pays).

Uses an empty temp root and a live Sina fetcher that bypasses the same-day response cache, so the
numbers are real round trips.  Output: archive/R5/contract_fetch_cold.json
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import requests  # noqa: E402

import daily_update as du  # noqa: E402
import market_data as md  # noqa: E402

snap = json.loads((ROOT / "archive/snapshots/bt_input_20261123_da9c8de64ab4.json").read_text(encoding="utf-8"))
bars = {c: b for c, b in snap["bars"].items()}
universe = [u for u in du.UNIVERSE if u["code"] in bars]


_orig_root = md.ROOT  # cold: empty same-day Sina response cache + empty in-process memo (real round trips)
md._MEM.clear()
from research.data_quality import contract_cache as cc  # noqa: E402

orig = cc.ensure_contract_bars


def run(root):
    t0 = time.perf_counter()
    st = du._ensure_contracts(universe, bars, root=root)
    st["wall_seconds"] = round(time.perf_counter() - t0, 2)
    return st


def parse_rows(rows):
    return rows


out = {}
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    md.ROOT = td
    try:
        cold = run(td)
        warm = run(td)
    finally:
        md.ROOT = _orig_root
    # fidelity: what do the three cache states give for today's signals?
    import copy
    import historical_backtest as hb

    carry_cfg, vol_cfg = hb.carry_bypass_cfg(None), hb.vol_bypass_cfg(None)
    curves = {c: ({"carry": v} if not (isinstance(v, dict) and "carry" in v) else v) for c, v in snap["carry"].items()}

    def sig(root):
        s, info = du.compute_signals(
            universe, copy.deepcopy(bars), mode="seats", bypass=carry_cfg, vbypass=vol_cfg, curves=curves,
            member_loader=lambda dates, codes: snap["member"], risk_budget=3000.0, contract_root=root,
            observe_min_lots=0,
        )
        return {x["code"]: x for x in s}

    with tempfile.TemporaryDirectory() as empty:
        s_repo, s_cold, s_empty = sig(ROOT), sig(td_keep := td), sig(Path(empty))
    fid = {}
    for name, other in (("cold_fetched_vs_repo", s_cold), ("empty_vs_repo", s_empty)):
        diffs = []
        for c, a in s_repo.items():
            b = other[c]
            d = {k: [a.get(k), b.get(k)] for k in ("direction", "r20", "r60", "atr", "lots_raw", "block", "adj_fallback") if a.get(k) != b.get(k)}
            if d:
                diffs.append({"code": c, **d})
        fid[name] = {"n_codes_differing": len(diffs), "directions_differ": [d["code"] for d in diffs if "direction" in d], "rows": diffs}
    out_fid = fid
out["cold"] = {k: cold[k] for k in ("requests", "seconds", "wall_seconds", "cached_n")}
out["cold"]["fetched_n"] = len(cold["fetched"])
out["cold"]["failed"] = cold["failed"]
out["warm_second_run"] = {k: warm[k] for k in ("requests", "seconds", "wall_seconds", "cached_n")}
out["n_codes"] = len(universe)
out["fidelity_vs_repo_cache"] = out_fid
(ROOT / "archive/R5/contract_fetch_cold.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
