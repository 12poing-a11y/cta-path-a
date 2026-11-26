# -*- coding: utf-8 -*-
"""R8 follow-up (READ-ONLY check; no strategy is run; not counted in DSR; formal layer / freeze lock untouched).

Question: in the 216-day window (2026-01-05 .. 2026-11-25), does the local contract store contain the contract with the
largest same-day volume?  The official 2026 daily quotes (SHFE / CZCE / DCE) were fetched in this session
(archive/R8/raw_contract, manifests include 2026), so the official volume is the reference.

For each frozen group (A = E1000k, B = F2; each with its own input snapshot) the engine's main_map is rebuilt with the
engine's own `build_main_map` (tapped at the call site, then aborted -> no simulation).  Per (code, day):
  top      = official candidate (calendar-listed, has an official bar that day) with the largest volume
  in_store = does the group's snapshot contract store have `top` on that day?   (gap day = top missing)
  engine   = main_map[code][day], its official volume and ratio to the day's max
  suspect  = engine main's official volume < 5% of the day's max
Also checks the shadow/paper-book store alternatives: the snapshot bundle (what paper_book uses first) and the local
cache store (CacheContractStore(ROOT), the fallback when no snapshot is given).
Writes archive/R8/window_gap_check.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab" / "shadow"))
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from contract_loader import load_all  # noqa: E402
from research.data_quality.calendar import listed_contracts_on  # noqa: E402

W0, W1 = "2026-01-05", "2026-11-25"
PCT = 0.05
GROUPS = {
    "A_E1000k": ("archive/R8/E1000k/result.json", "archive/snapshots/bt_input_20261125_05dade0b049c.json"),
    "B_F2": ("archive/R8/F2/result.json", "archive/snapshots/bt_input_20261125_ded77f068e9b.json"),
}

by = load_all()


def official_cands(code, d):
    out = {}
    for c in listed_contracts_on(code, d):
        r = by.get(c, {}).get(d)
        if r and all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close")):
            out[c] = float(r.get("volume") or 0)
    return out


class _Stop(Exception):
    pass


def tap_main_map(snap_path, bt_path):
    import historical_backtest as hb
    import research.data_quality.main_map as mmod
    from lab.shadow import replay
    from research.data_quality.contract_store import snapshot_store

    snap_obj, bt_obj = replay.load_inputs(snap_path, bt_path)
    replay.apply_freeze(snap_obj, bt_obj)
    p, pack = replay.make_pack(snap_obj=snap_obj)
    store = snapshot_store(snap_obj, Path(snap_path))
    box = {}
    orig = mmod.build_main_map

    def tap(series, **kw):
        box["mm"] = orig(series, **kw)
        raise _Stop()

    mmod.build_main_map = tap
    try:
        hb._simulate_cfg(p, p["entry_filter"], pack=pack, contract_root=store)
    except _Stop:
        pass
    finally:
        mmod.build_main_map = orig
    assert "mm" in box, "main_map was not built"
    return box["mm"], store, snap_obj


def analyse(name, bt_path, snap_path):
    from research.data_quality.contract_store import CacheContractStore

    mm, store, snap_obj = tap_main_map(ROOT / snap_path, ROOT / bt_path)
    cache_store = CacheContractStore(ROOT)
    bt = json.loads((ROOT / bt_path).read_text(encoding="utf-8"))
    days_by_code = {c: sorted(d for d in (str(b["date"])[:10] for b in snap_obj["bars"][c]) if W0 <= d <= W1) for c in snap_obj["bars"]}
    rows, per_code = {}, defaultdict(Counter)
    for c, days in days_by_code.items():
        for d in days:
            cands = official_cands(c, d)
            if not cands:
                per_code[c]["no_official_candidate_days"] += 1
                continue
            vmax = max(cands.values())
            top = max(cands, key=lambda x: cands[x])
            eng = mm.main(c, d)
            ev = cands.get(eng) if eng else None
            in_store = d in store.by_date(top)
            in_cache = d in cache_store.by_date(top)
            suspect = bool(eng and vmax > 0 and ev is not None and ev < PCT * vmax)
            eng_missing_official = bool(eng and eng not in cands)
            rows[(c, d)] = dict(top=top, top_vol=vmax, in_store=in_store, in_cache=in_cache, engine=eng,
                                engine_vol=ev, engine_ratio=(None if ev is None or vmax <= 0 else round(ev / vmax, 4)),
                                suspect=suspect, engine_is_top=(eng == top), engine_not_in_official=eng_missing_official)
            k = per_code[c]
            k["days"] += 1
            k["gap_days_snapshot_store"] += (not in_store)
            k["gap_days_cache_store"] += (not in_cache)
            k["engine_none_days"] += (eng is None)
            k["engine_not_top_days"] += (eng is not None and eng != top)
            k["suspect_days"] += suspect
            k["gap_and_suspect_days"] += ((not in_store) and suspect)
            k["gap_and_engine_not_top_days"] += ((not in_store) and eng is not None and eng != top)

    # trades
    closed = list(bt.get("closed_pnls") or [])
    final = list((bt.get("final_positions") or {}).values())
    trades = []
    for t in closed:
        trades.append(dict(code=t["code"], entry=str(t["entry_date"])[:10], exit=str(t["date"])[:10], fill_contract=t.get("fill_contract"),
                           basis=t.get("fill_price_basis"), open=False, direction=t.get("direction"), lots=t.get("lots")))
    for t in final:
        trades.append(dict(code=t["code"], entry=str(t["entry_date"])[:10], exit=None, fill_contract=t.get("fill_contract"),
                           basis=t.get("fill_price_basis"), open=True, held_contract=t.get("held_contract"), direction=t.get("direction"), lots=t.get("lots")))
    aff = []
    for t in trades:
        c = t["code"]
        ev = []
        for kind, d in (("entry", t["entry"]), ("exit", t["exit"])):
            if d is None:
                continue
            r = rows.get((c, d))
            if r is None:
                ev.append(dict(kind=kind, date=d, note="no official candidate / not in window"))
                continue
            ev.append(dict(kind=kind, date=d, gap=(not r["in_store"]), suspect=r["suspect"], engine=r["engine"], engine_ratio=r["engine_ratio"],
                           top=r["top"], top_in_cache=r["in_cache"], fill_contract_is_engine=(t["fill_contract"] == r["engine"])))
        # in-hold days with a suspect engine main / main != top
        hold_susp = []
        end = t["exit"] or W1
        for (cc, d), r in rows.items():
            if cc == c and t["entry"] <= d <= end and (r["suspect"] or (r["engine"] is not None and not r["engine_is_top"] and not r["in_store"])):
                hold_susp.append(dict(date=d, engine=r["engine"], ratio=r["engine_ratio"], top=r["top"], gap=(not r["in_store"])))
        t["events"] = ev
        t["hold_suspect_days"] = sorted(hold_susp, key=lambda x: x["date"])
        t["fill_contract_official_ratio"] = None
        r0 = rows.get((c, t["entry"]))
        if r0 and t["fill_contract"]:
            cs = official_cands(c, t["entry"])
            if t["fill_contract"] in cs and r0["top_vol"] > 0:
                t["fill_contract_official_ratio"] = round(cs[t["fill_contract"]] / r0["top_vol"], 4)
        # fill contract vs official volume on the SIGNAL day T (day before the T+1 fill) and on the fill day
        dl = days_by_code[c]
        prev = dl[dl.index(t["entry"]) - 1] if t["entry"] in dl and dl.index(t["entry"]) > 0 else None
        t["entry_signal_day"] = prev
        t["fill_contract_ratio_signal_day"] = None
        t["engine_main_signal_day"] = mm.main(c, prev) if prev else None
        if prev and t["fill_contract"]:
            cs = official_cands(c, prev)
            if t["fill_contract"] in cs and cs and max(cs.values()) > 0:
                t["fill_contract_ratio_signal_day"] = round(cs[t["fill_contract"]] / max(cs.values()), 4)
        t["fill_contract_thin_on_signal_day"] = t["fill_contract_ratio_signal_day"] is not None and t["fill_contract_ratio_signal_day"] < PCT
        t["fill_contract_thin_on_fill_day"] = t["fill_contract_official_ratio"] is not None and t["fill_contract_official_ratio"] < PCT
        t["affected_entry_exit_on_gap_day"] = any(e.get("gap") for e in ev)
        t["affected_suspect_on_entry_exit"] = any(e.get("suspect") for e in ev)
        t["affected_hold_suspect"] = bool(hold_susp)
        aff.append(t)
    tot = Counter()
    for k, v in per_code.items():
        tot.update(v)
    return dict(per_code={k: dict(v) for k, v in sorted(per_code.items())}, totals=dict(tot), n_trades=len(trades), trades=aff,
                gap_days=[dict(code=c, date=d, **r) for (c, d), r in sorted(rows.items()) if not r["in_store"]],
                suspect_days=[dict(code=c, date=d, **r) for (c, d), r in sorted(rows.items()) if r["suspect"]])


def main():
    out = {"window": [W0, W1], "pct": PCT, "reference": "official daily quotes fetched 2026-11-26 (SHFE/CZCE/DCE), manifests in raw_contract"}
    for g, (bt, sn) in GROUPS.items():
        out[g] = analyse(g, bt, sn)
        o = out[g]
        print(g, "totals", o["totals"], "trades", o["n_trades"], flush=True)
        print("  trades affected: gap-day entry/exit:", sum(t["affected_entry_exit_on_gap_day"] for t in o["trades"]),
              "| suspect on entry/exit:", sum(t["affected_suspect_on_entry_exit"] for t in o["trades"]),
              "| suspect days in hold:", sum(t["affected_hold_suspect"] for t in o["trades"]),
              "| fill contract <5% of max on signal day T:", sum(t["fill_contract_thin_on_signal_day"] for t in o["trades"]),
              "| on fill day:", sum(t["fill_contract_thin_on_fill_day"] for t in o["trades"]), flush=True)
    (ROOT / "archive" / "R8" / "window_gap_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
