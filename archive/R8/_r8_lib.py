# -*- coding: utf-8 -*-
"""R8 helper: offline replay of one group on its frozen input snapshot with recording taps (nothing patched on disk).

``replay_group(snap_path, bt_path, overrides)`` returns the engine result plus:
  * ``skips``      signal-day split with the same classification as step 0 (static_sizing.md section c)
  * ``cand_attr``  per (day, code) attributes of every ``ok`` candidate (close, mult, sizing_eq, ATR14, ATR100)
                   -> lets us evaluate a filter predicate on ANY run's own path (used for the 'filtered-out trades')
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab" / "shadow"))


def replay_group(snap_path: Path, bt_path: Path, overrides: dict | None = None) -> dict:
    import historical_backtest as hb
    import research.data_quality.adjusted as adj_mod
    from lab.shadow import replay
    from position_rules import _strength
    from research.data_quality.contract_store import snapshot_store
    from research.execution import entry_filters as ef

    overrides = dict(overrides or {})
    snap_obj, bt_obj = replay.load_inputs(snap_path, bt_path)
    replay.apply_freeze(snap_obj, bt_obj)
    p, pack = replay.make_pack(snap_obj=snap_obj)
    p.update(overrides)
    store = snapshot_store(snap_obj, Path(snap_path))

    holder: dict = {}
    ctx = {"day": None}
    cand_log: list[dict] = []
    cand_attr: dict[tuple, dict] = {}
    caps_first: dict[str, dict] = {}
    orig_adj, orig_cand, orig_caps = adj_mod.build_adjusted_pack, hb.path_a_candidate, hb.apply_portfolio_caps

    def adj_wrap(*a, **k):
        r = orig_adj(*a, **k)
        holder["adj"] = r
        return r

    def cand_wrap(code, hist, i, **kw):
        ctx["day"] = kw["ctx"]["day"]
        res = orig_cand(code, hist, i, **kw)
        sz = res.get("sizing")
        if res.get("status") in ("ok", "lots0") and sz is not None:
            cand_log.append({"day": ctx["day"], "code": code, "status": res["status"]})
        if res.get("status") == "ok":
            c = res["candidate"]
            cand_attr[(ctx["day"], code)] = {
                "close": float(c["close"]), "mult": float(c["mult"]), "atr14": res.get("atr"),
                "atr100": ef.long_atr(kw.get("adj"), hist, i), "risk_per_lot": sz["risk_per_lot"],
                "day_risk": kw["params"]["day_risk"],
            }
        return res

    def caps_wrap(cands, **kw):
        sel, meta = orig_caps(cands, **kw)
        d = ctx["day"]
        if d is not None and d not in caps_first:
            caps_first[d] = {"cands": [dict(c) for c in cands], "meta": json.loads(json.dumps(meta, default=str)),
                             "selected": [c["code"] for c in sel], "max_positions": kw.get("max_positions")}
        return sel, meta

    adj_mod.build_adjusted_pack, hb.path_a_candidate, hb.apply_portfolio_caps = adj_wrap, cand_wrap, caps_wrap
    clog: list[dict] = []
    try:
        out = hb._simulate_cfg(p, p["entry_filter"], pack=pack, contract_root=store, candidate_log=clog)
    finally:
        adj_mod.build_adjusted_pack, hb.path_a_candidate, hb.apply_portfolio_caps = orig_adj, orig_cand, orig_caps

    sizing_eq = {e["date"]: float(e["sizing_eq"]) for e in clog}
    held_by_day = {e["date"]: e.get("held") or {} for e in clog}
    for (d, _c), a in cand_attr.items():
        a["sizing_eq"] = sizing_eq.get(d)

    # ---- skip split (same logic as _static_sizing.py section c) --------------------------------
    cats: Counter = Counter()
    cats["lots0"] = sum(1 for r in cand_log if r["status"] == "lots0")
    for d, v in caps_first.items():
        m, cands, final = v["meta"], v["cands"], set(v["selected"])
        weak, bsk = set(m.get("weak_filtered") or []), set(m.get("bucket_skipped") or [])
        ranked = sorted([c for c in cands if c["code"] not in weak], key=_strength, reverse=True)
        sel3, ncap, bk = [], set(), set()
        counts = Counter(str(h.get("bucket") or "_") for h in held_by_day.get(d, {}).values())
        for c in ranked:
            if len(sel3) >= max(0, int(v["max_positions"])):
                ncap.add(c["code"])
                continue
            b = str(c.get("bucket") or "_")
            if int(p["max_per_bucket"]) > 0 and counts.get(b, 0) >= int(p["max_per_bucket"]):
                bk.add(c["code"])
                continue
            sel3.append(c)
            counts[b] = counts.get(b, 0) + 1
        assert bk == bsk, (d, bk, bsk)
        for c in cands:
            code = c["code"]
            if code in final:
                continue
            if code in weak:
                k = "weak_momentum"
            elif code in bsk:
                k = "bucket_full"
            elif code in ncap:
                k = "positions_full"
            else:
                sg, sr = float(m.get("scale_gross", 1.0)), float(m.get("scale_risk", 1.0))
                lg = math.floor(int(c["lots"]) * sg) if sg < 1 else int(c["lots"])
                lr = math.floor(lg * sr) if sr < 1 else lg
                k = "gross_cap_to_0" if (sg < 1 and lg == 0) else ("atr_risk_cap_to_0" if lr == 0 else "hard_trim")
            cats[k] += 1
    selected_n = sum(len(v["selected"]) for v in caps_first.values())
    ef_out = out.get("entry_filters") or {}
    return {
        "out": out, "p": p, "skips": dict(cats), "selected_entries": selected_n,
        "filter_hits": (ef_out.get("hits") or {}), "cand_attr": cand_attr,
        "slots_left_zero_days": sum(1 for e in clog if int(e.get("slots_left") or 0) == 0),
        "candidate_days": len(clog),
    }
