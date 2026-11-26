# -*- coding: utf-8 -*-
"""R8 long-sample entry (research only; formal layer untouched).  See archive/R8/APPENDIX_1.md for the registered rules.

Data source switch (``data_source``)
  * ``local``    (DEFAULT) the existing frozen-snapshot 216-day path.  Nothing about the engine changes: the result must equal
                 the formal/frozen result bit for bit (regression test).  Guard is never applied here.
  * ``official`` the long sample (2016-01-04 .. 2025-12-31) on exchange-official per-contract data only:
                   - main contract identified by the engine's own price-match rule against the Sina continuous series
                     (the continuous series is used for identification ONLY) with the volume guard (``guard_pct``, 5%);
                   - unidentified days carry the previous main (no roll);
                   - the price / ATR / signal series is the stitched official OHLC of each day's main contract
                     (actual contract prices); signals / ATR via the R6c roll-free AdjustedSeries; notional / lots at actual prices;
                   - contract-level roll = the engine's existing held-contract roll (continuous_proxy positions).

usage: python archive/R8/long_sample.py --group A1000k [--out archive/R8/OOS/A1000k] [--data-source official] [--guard 0.05]
"""
from __future__ import annotations

import copy
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "archive" / "R8"), str(ROOT / "lab" / "shadow")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

W0, W1 = "2016-01-04", "2025-12-31"
FU_START = "2018-10-16"
GUARD_PCT = 0.05
N_TRIALS = 30
LEVELS = {"800k": 800_000.0, "1000k": 1_000_000.0, "1200k": 1_200_000.0, "300k": 300_000.0}


# ----------------------------------------------------------------------------------------------------------------------
# official data -> guarded main map -> stitched series
# ----------------------------------------------------------------------------------------------------------------------
def traded(r: dict) -> bool:
    return all((r.get(k) or 0) > 0 for k in ("open", "high", "low", "close"))


def bundle_of(by: dict) -> dict:
    out = {}
    for c, rows in by.items():
        rr = [dict(date=d, open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume"),
                   settle=r.get("settle"), oi=r.get("oi")) for d, r in sorted(rows.items()) if traded(r)]
        if rr:
            out[c] = rr
    return out


def guarded_main_series(code: str, hist: list[dict], store, tick: float, pct: float, ref_vol):
    """The engine's ``build_main_map`` loop (calendar candidates, price-only match, prior-main tie-break) + volume guard.

    ``ref_vol(contract, day)`` = official volume.  ``pct == 0`` reproduces ``build_main_map`` exactly (verified in tests).
    Returns {day: main or None} (None = unidentified)."""
    from research.data_quality.calendar import listed_contracts_on
    from research.data_quality.main_map import match_main_contract

    rows_cache, m, prev = {}, {}, None
    for b in hist:
        d = str(b.get("date") or "")[:10]
        if not d:
            continue
        cands = {}
        for c in listed_contracts_on(code, d):
            rows = rows_cache.get(c)
            if rows is None:
                rows = rows_cache[c] = store.by_date(c)
            if d in rows:
                cands[c] = rows[d]
        if pct > 0 and cands:
            vols = {c: float(ref_vol(c, d) or 0) for c in cands}
            vmax = max(vols.values())
            if vmax > 0:
                cands = {c: r for c, r in cands.items() if vols[c] >= pct * vmax}
        main, _ = match_main_contract(b, cands, tick=float(tick or 0.0), prev_main=prev)
        m[d] = main
        prev = main
    return m


def build_official_pack(*, guard_pct: float = GUARD_PCT, w0: str = W0, w1: str = W1, by: dict | None = None, codes=None,
                        matcher_dir=None):
    """-> (pack, main_map, store, info).  ``pack`` = (series, errors, sources) as the engine expects."""
    import historical_backtest as hb
    from contract_loader import load_all
    from research.data_quality.contract_store import BundleContractStore
    from research.data_quality.main_map import MainMap

    by = by if by is not None else load_all()
    qd = {d for v in by.values() for d in v}
    bundle = bundle_of(by)
    store = BundleContractStore(bundle)
    p = hb._load_cfg()
    symbols = [u for u in p["cfg"]["symbols"] if codes is None or u["code"] in codes]

    def ref_vol(c, d):
        return (by.get(c, {}).get(d) or {}).get("volume") or 0

    series, maps, stats, raw_maps = {}, {}, {}, {}
    n_unid_days = Counter()
    for u in symbols:
        code = u["code"]
        mdir = Path(matcher_dir) if matcher_dir is not None else ROOT / ".cache" / "history"  # default = R8 frozen input
        cont = [b for b in json.loads((mdir / f"{code}0.json").read_text(encoding="utf-8"))
                if w0 <= str(b["date"])[:10] <= w1 and str(b["date"])[:10] in qd]
        start = FU_START if code == "FU" else w0
        cont = [b for b in cont if str(b["date"])[:10] >= start]
        mm = guarded_main_series(code, cont, store, float(u.get("tick") or 0.0), guard_pct, ref_vol)
        raw_maps[code] = mm
        hist, resolved, last = [], {}, None
        for b in cont:
            d = str(b["date"])[:10]
            main = mm.get(d)
            if main is None:
                n_unid_days[code] += 1
            main = main or last  # unidentified day: carry the previous main, no roll
            if main is None:
                continue
            r = by.get(main, {}).get(d)
            if r is None or not traded(r) or not (r.get("volume") or 0) > 0:
                last = main
                continue  # no usable official bar of the (carried) main today -> no bar for this code today
            hist.append({"date": d, "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]), "volume": float(r["volume"]), "oi": r.get("oi"),
                         "settle": r.get("settle"), "contract": main})
            resolved[d] = main
            last = main
        if hist:
            series[code] = {"meta": dict(u), "hist": hist}
            maps[code] = resolved
            n = len(hist)
            none_n = sum(1 for b in hist if raw_maps[code].get(b["date"]) is None)
            stats[code] = {"days": n, "matched": n - none_n, "none_days": none_n, "coverage": round((n - none_n) / n, 4)}
    main_map = MainMap(maps=maps, stats=stats)
    info = {
        "window": [w0, w1], "guard_pct": guard_pct, "fu_start": FU_START,
        "symbols": sorted(series), "bars": {c: len(s["hist"]) for c, s in series.items()},
        "first_bar": {c: s["hist"][0]["date"] for c, s in series.items()},
        "max_loaded_date": max(b["date"] for s in series.values() for b in s["hist"]),
        "unidentified_symbol_days_carried": dict(n_unid_days),
        "roll_events": sum(1 for c, m in maps.items() for a, b in zip(sorted(m), sorted(m)[1:]) if m[a] != m[b]),
        "pack_sha256": hb.pack_sha256(series),
    }
    assert info["max_loaded_date"] <= w1, "long sample must not load anything after the window end"
    return (series, {}, {c: "official" for c in series}), main_map, store, info


# ----------------------------------------------------------------------------------------------------------------------
# running one configuration (one cost scenario) with recording taps
# ----------------------------------------------------------------------------------------------------------------------
def _long_params(group_kind: str, equity: float, scenario: str):
    import historical_backtest as hb
    from research.execution.cost_model import load_cost_scenario
    from path_a_filters import carry_bypass_cfg

    p = hb._load_cfg()
    p["equity0"] = float(equity)
    p["carry_bypass"] = carry_bypass_cfg({"enabled": False})  # no carry data in the long sample (basic mode)
    p["filter_atr_spike"] = group_kind == "B"
    sc = load_cost_scenario(scenario, root=ROOT)
    if scenario != "base":
        p["slippage_ticks"], p["fee_mult"], p["cost_scenario"] = sc["slippage_ticks"], sc["fee_mult"], scenario
    return p


def run_long(group_kind: str, equity: float, scenario: str, pack, main_map, store, *, with_taps: bool = True,
             p: dict | None = None, mode: str = "base", ls_extra: dict | None = None) -> dict:
    """One official-data long run.  ``group_kind`` in {A, B, C}.

    ``p`` / ``mode`` / ``ls_extra`` (default None / "base" / None = exactly the registered long-sample run) are only used by the
    read-only attribution (bridge cells): another parameter set, entry mode or ``long_sample`` keys."""
    import historical_backtest as hb
    import research.data_quality.adjusted as adj_mod
    from position_rules import _strength
    from research.execution import entry_filters as ef

    p = p if p is not None else _long_params(group_kind, equity, scenario)
    series = copy.deepcopy(pack[0])
    pk = (series, dict(pack[1]), dict(pack[2]))
    ls = {"main_map": main_map, "skip_contract_overlay": True, "no_minute": True}
    ls.update(ls_extra or {})
    if group_kind == "C":
        ls["candidate_pool"] = ef.MonthlyNotionalPool(
            equity0=equity, mult={c: float(s["meta"]["mult"]) for c, s in series.items()},
            bars={c: s["hist"] for c, s in series.items()})
    cand_attr, caps_first, cand_log = {}, {}, []
    ctx = {"day": None}
    orig_cand, orig_caps = hb.path_a_candidate, hb.apply_portfolio_caps

    def cand_wrap(code, hist, i, **kw):
        ctx["day"] = kw["ctx"]["day"]
        res = orig_cand(code, hist, i, **kw)
        sz = res.get("sizing")
        if res.get("status") in ("ok", "lots0") and sz is not None:
            cand_log.append({"day": ctx["day"], "code": code, "status": res["status"]})
        if res.get("status") == "ok":
            c = res["candidate"]
            cand_attr[(ctx["day"], code)] = {"close": float(c["close"]), "mult": float(c["mult"]), "atr14": res.get("atr"),
                                             "atr100": ef.long_atr(kw.get("adj"), hist, i)}
        return res

    def caps_wrap(cands, **kw):
        sel, meta = orig_caps(cands, **kw)
        d = ctx["day"]
        if d is not None and d not in caps_first:
            caps_first[d] = {"cands": [dict(c) for c in cands], "meta": json.loads(json.dumps(meta, default=str)),
                             "selected": [c["code"] for c in sel], "max_positions": kw.get("max_positions")}
        return sel, meta

    clog: list[dict] = []
    if with_taps:
        hb.path_a_candidate, hb.apply_portfolio_caps = cand_wrap, caps_wrap
    try:
        out = hb._simulate_cfg(p, mode, pack=pk, contract_root=store, candidate_log=clog if with_taps else None, long_sample=ls)
    finally:
        hb.path_a_candidate, hb.apply_portfolio_caps = orig_cand, orig_caps
    res = {"out": out, "p": p, "cand_attr": cand_attr, "pool": ls.get("candidate_pool"), "clog": clog}
    if with_taps:
        held_by_day = {e["date"]: e.get("held") or {} for e in clog}
        cats: Counter = Counter()
        cats["lots0"] = sum(1 for r in cand_log if r["status"] == "lots0")
        ev_cat: dict = {(r["day"], r["code"]): "lots0" for r in cand_log if r["status"] == "lots0"}  # attribution only
        res["clog_days"] = {e["date"]: {"slots_left": e.get("slots_left"), "n_cands": len(e.get("cands") or [])} for e in clog}
        for d, v in caps_first.items():
            m, cands, final = v["meta"], v["cands"], set(v["selected"])
            weak, bsk = set(m.get("weak_filtered") or []), set(m.get("bucket_skipped") or [])
            ranked = sorted([c for c in cands if c["code"] not in weak], key=_strength, reverse=True)
            ncap = set()
            counts = Counter(str(h.get("bucket") or "_") for h in held_by_day.get(d, {}).values())
            sel3 = []
            for c in ranked:
                if len(sel3) >= max(0, int(v["max_positions"])):
                    ncap.add(c["code"])
                    continue
                b = str(c.get("bucket") or "_")
                if int(p["max_per_bucket"]) > 0 and counts.get(b, 0) >= int(p["max_per_bucket"]):
                    continue
                sel3.append(c)
                counts[b] = counts.get(b, 0) + 1
            for c in cands:
                code = c["code"]
                if code in final:
                    ev_cat[(d, code)] = "selected"
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
                ev_cat[(d, code)] = k
        res["ev_cat"] = ev_cat
        res["skips"] = dict(cats)
        res["pool_blocked_signals"] = sum((out.get("long_sample") or {}).get("pool_blocked_signals", {}).values())
    return res


# ----------------------------------------------------------------------------------------------------------------------
# per-trade net pnl (price pnl on the engine's shifted entry + all fills re-costed), folds, metrics
# ----------------------------------------------------------------------------------------------------------------------
def trade_net_pnl(t: dict, meta: dict, slip: float, fee_mult: float) -> dict:
    import historical_backtest as hb

    sign = 1.0 if str(t["direction"]) in ("多", "long", "buy") else -1.0
    lots, mult = int(t["lots"]), float(meta["mult"])
    gross = sign * (float(t["exit"]) - float(t["entry"])) * lots * mult  # entry is already shifted by every roll
    cost = hb.fill_cost(meta, float(t.get("entry_orig", t["entry"])), lots, slippage_ticks=slip, fee_mult=fee_mult)
    for ev in t.get("roll_events") or []:
        if ev.get("status") == "shifted":
            cost += hb.fill_cost(meta, float(ev["old_open"]), lots, slippage_ticks=slip, fee_mult=fee_mult)
            cost += hb.fill_cost(meta, float(ev["new_open"]), lots, slippage_ticks=slip, fee_mult=fee_mult)
    cost += hb.fill_cost(meta, float(t["exit"]), lots, slippage_ticks=slip, fee_mult=fee_mult)
    return {"gross": gross, "cost": cost, "net": gross - cost, "n_rolls": sum(1 for e in (t.get("roll_events") or []) if e.get("status") == "shifted")}


def year_folds(curve: list[dict], equity0: float) -> dict:
    last = {}
    for x in curve:
        last[str(x["date"])[:4]] = float(x["equity"])
    out, prev = {}, float(equity0)
    for y in sorted(last):
        out[y] = last[y] / prev - 1.0
        prev = last[y]
    return out


def slim(res: dict, meta_by_code: dict, equity0: float) -> dict:
    out = res["out"]
    ls = out.get("long_sample") or {}
    slip, fm = float(out["slippage_ticks"]), float(out["fee_mult"])
    trades = []
    for t in out["closed_pnls"]:
        n = trade_net_pnl(t, meta_by_code[t["code"]], slip, fm)
        trades.append({**{k: t.get(k) for k in ("code", "direction", "lots", "entry_date", "date", "entry", "exit", "reason", "R")},
                       "entry_orig": t.get("entry_orig"), "n_rolls": n["n_rolls"], "gross": round(n["gross"], 2), "cost": round(n["cost"], 2),
                       "net": round(n["net"], 2), "held_contract": t.get("held_contract")})
    keep = ("ok", "mode", "cost_scenario", "fee_mult", "slippage_ticks", "start", "end", "trade_days", "equity_start", "equity_end", "ret_pct",
            "gross_ret_pct", "cost_yuan", "max_dd_pct", "gross_max_dd_pct", "closed_trades", "roll_shifted", "roll_unpriced_cont",
            "roll_unpriced", "held_contract_missing", "roll_held_bar_days", "roll_open_gap_stops", "adj_fallback_days", "adj_fallback_days_in_window",
            "adj_roll_days", "exits", "blocks", "quality_blocks", "signal_candidates", "avg_held", "bars", "entry_filters", "freeze_fix",
            "git_sha", "universe_sha256", "execution_rules_sha256", "research_cost_sha256", "conclusion", "main_map_full_history")
    rec = {k: out.get(k) for k in keep}
    if "entry_filters" in rec and rec["entry_filters"]:
        rec["entry_filters"] = {k: v for k, v in rec["entry_filters"].items() if k != "log"}
    rec.update({
        "final_positions": out.get("final_positions"), "equity_curve": [{k: x[k] for k in ("date", "equity", "held", "gross_pct")} for x in out["equity_curve"]],
        "trades": trades, "skips": res.get("skips"), "pool_blocked_signals": res.get("pool_blocked_signals"),
        "pool": (ls.get("pool") if ls else None), "folds_year": year_folds(out["equity_curve"], equity0),
        "long_sample": {k: v for k, v in ls.items() if k != "pool"},
    })
    return rec


# ----------------------------------------------------------------------------------------------------------------------
# local (default) path: the frozen 216-day replay, engine unchanged
# ----------------------------------------------------------------------------------------------------------------------
def run_local_216(snap_path, bt_path, overrides: dict | None = None) -> dict:
    """Default data source.  Same sequence as ``_r8_lib.replay_group`` without any tap; restores the patched ``hb`` globals."""
    import historical_backtest as hb

    # captured BEFORE importing ``lab.shadow.replay``: its import-time legacy side effect also patches these globals
    saved = {k: getattr(hb, k) for k in ("prepare_pack_for_execution", "load_member_seats", "load_member_changes", "lag_member",
                                         "load_curves", "lag_curves_carry")}
    try:
        from lab.shadow import replay
        from research.data_quality.contract_store import snapshot_store


        snap_obj, bt_obj = replay.load_inputs(snap_path, bt_path)
        replay.apply_freeze(snap_obj, bt_obj)
        p, pack = replay.make_pack(snap_obj=snap_obj)
        p.update(dict(overrides or {}))
        store = snapshot_store(snap_obj, Path(snap_path))
        return hb._simulate_cfg(p, p["entry_filter"], pack=pack, contract_root=store)
    finally:
        for k, v in saved.items():
            setattr(hb, k, v)


def run_group(name: str, *, data_source: str = "local", guard_pct: float | None = None, out_dir: Path | None = None, pack_bundle=None,
              snap_path=None, bt_path=None, overrides=None):
    """``name`` e.g. A1000k / B800k / C1200k.  Returns the local ``out`` dict (216-day) or {'base': rec, 'stress': rec}."""
    if data_source == "local":
        if guard_pct not in (None, 0, 0.0):
            raise ValueError("the volume guard is official-path only; the local default path never applies it")
        if snap_path is None or bt_path is None:
            raise ValueError("local source needs the frozen snapshot and its BT result")
        return run_local_216(snap_path, bt_path, overrides)
    if data_source != "official":
        raise ValueError(f"unknown data_source {data_source!r}")
    kind, lvl = name[0].upper(), name[1:]
    if kind not in ("A", "B", "C") or lvl not in LEVELS:
        raise ValueError(f"bad group name {name!r}")
    equity = LEVELS[lvl]
    gp = GUARD_PCT if guard_pct is None else float(guard_pct)
    pack, main_map, store, info = pack_bundle or build_official_pack(guard_pct=gp)
    meta = {c: s["meta"] for c, s in pack[0].items()}
    res = {}
    for scen in ("base", "stress"):
        r = run_long(kind, equity, scen, pack, main_map, store)
        res[scen] = slim(r, meta, equity)
        res[scen]["cand_attr_n"] = len(r["cand_attr"])
        if kind == "A" and scen == "stress":
            res["stress_cand_attr"] = {f"{d}|{c}": v for (d, c), v in r["cand_attr"].items()}
        assert res[scen]["start"] >= W0 and res[scen]["end"] <= W1, (res[scen]["start"], res[scen]["end"])
    res["info"] = info
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for scen in ("base", "stress"):
            (out_dir / f"result_{scen}.json").write_text(json.dumps(res[scen], ensure_ascii=False, default=str), encoding="utf-8")
        if "stress_cand_attr" in res:
            (out_dir / "stress_cand_attr.json").write_text(json.dumps(res["stress_cand_attr"], default=str), encoding="utf-8")
        (out_dir / "run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--data-source", default="official", choices=("official", "local"))
    ap.add_argument("--guard", type=float, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    r = run_group(a.group, data_source=a.data_source, guard_pct=a.guard, out_dir=Path(a.out) if a.out else None)
    if a.data_source == "official":
        for s in ("base", "stress"):
            print(a.group, s, "ret", r[s]["ret_pct"], "dd", r[s]["max_dd_pct"], "trades", r[s]["closed_trades"], "rolls", r[s]["roll_shifted"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
