# -*- coding: utf-8 -*-
"""R8 follow-up (read-only): why does 'official / main-open / full' (138 trades, Base) trade more than 'local / calendar-front / full' (99)?

No returns are compared, nothing is tuned, nothing enters DSR.  Cells (all A1000k, Base, full mode, 2026-01-05 -> 2026-11-25):
  A = local snapshot / calendar front-contract open (frozen E1000k)      99 trades
  B = official stitched main / main-contract open                          138 trades
  C = local snapshot / main-contract open (continuous series open)         97 trades   (controls for the fill basis alone)
Output: archive/R8/ATTRIB/trades138.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(HERE), str(ROOT / "lab" / "shadow")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import long_sample as ls  # noqa: E402
import bridge as br  # noqa: E402


def run_cells():
    official = ls.build_official_pack(w1=br.WIN1)
    cells = {}
    for nm, (d, f) in {"A": ("local", "cal"), "B": ("official", "main"), "C": ("local", "main")}.items():
        k = {}
        rec = br.run_cell(d, f, "full", "base", official, keep=k)
        out = k["r"]["out"]
        cells[nm] = {"rec": rec, "clog": {e["date"]: e for e in k["r"]["clog"]}, "series": {c: {b["date"]: b for b in s["hist"]} for c, s in k["last_pack"]["series"].items()},
                     "member": k["last_pack"]["member"], "carry": k["last_pack"]["carry"], "out": out,
                     "dates": [x["date"] for x in out["equity_curve"]]}
        print(nm, rec["closed_trades"], flush=True)
    return official, cells


def trades_of(cell):
    out = cell["out"]
    rows = [{"code": t["code"], "dir": t["direction"], "entry_date": t["entry_date"], "exit_date": t["date"], "reason": t.get("reason"), "open_at_end": False}
            for t in out["closed_pnls"]]
    rows += [{"code": c, "dir": p["direction"], "entry_date": p["entry_date"], "exit_date": None, "reason": "open_at_end", "open_at_end": True}
             for c, p in (out.get("final_positions") or {}).items()]
    return rows


def key(t):
    return (t["code"], str(t["dir"]), t["entry_date"])


def prev_date(dates, d):
    i = dates.index(d) if d in dates else None
    return dates[i - 1] if i else None


def explain_in_A(cellA, sig_day, code, entry_date, dates_A):
    """Which gate stopped (code, signal day) in the local calendar cell."""
    clog = cellA["clog"]
    e = clog.get(sig_day)
    if e is None:
        held = None
        for x in cellA["out"]["equity_curve"]:
            if x["date"] == sig_day:
                held = x.get("codes")
        return {"where": "no_free_slot", "detail": f"A had no free position slot on {sig_day} (held after day: {held})"}
    v = (e.get("verdicts") or {}).get(code)
    if v is None:
        in_pos = code in (e.get("held") or {})
        has_bar = sig_day in cellA["series"].get(code, {})
        return {"where": "not_evaluated", "detail": "A already held this code" if in_pos else ("no bar for this code in A on the signal day" if not has_bar else "not evaluated")}
    st = v.get("status")
    if st in ("no_signal", "no_ret", "no_atr"):
        return {"where": "signal_differs", "detail": f"A status={st} aligned={v.get('aligned')} gate_ok={v.get('gate_ok')} r20={v.get('r20')} r60={v.get('r60')}"}
    if st == "blocked":
        return {"where": f"blocked:{v.get('block_kind')}", "detail": str(v.get("blocked"))}
    if st == "lots0":
        return {"where": "lots0", "detail": "sized to 0 lots"}
    sel = {c for c, _ in e.get("selected") or []}
    if code in sel:
        fb = cellA["series"].get(code, {}).get(entry_date) or {}
        flags = {k: fb.get(k) for k in ("delivery_restricted", "near_delivery", "roll_blocked", "no_new_position") if fb.get(k)}
        return {"where": "fill_time_quality" if flags else "selected_but_not_filled", "detail": f"selected on signal day; fill bar {entry_date} flags={flags}", "fill_flags": flags}
    ca = [c["code"] for c in (e.get("cands") or [])]
    return {"where": "caps:not_selected", "detail": f"A candidate but not selected (slots_left={e.get('slots_left')}, cands={ca}, held={list((e.get('held') or {}).keys())})"}


def main() -> int:
    official, cells = run_cells()
    main_map = official[1]
    A, B, C = cells["A"], cells["B"], cells["C"]
    tA, tB, tC = trades_of(A), trades_of(B), trades_of(C)
    kA, kB, kC = {key(t) for t in tA}, {key(t) for t in tB}, {key(t) for t in tC}
    only_B = [t for t in tB if key(t) not in kA]
    only_A = [t for t in tA if key(t) not in kB]
    common = [t for t in tB if key(t) in kA]
    from research.data_quality.calendar import delivery_flags_for_date

    rows = []
    for t in only_B:
        sig = prev_date(B["dates"], t["entry_date"])
        vB = ((B["clog"].get(sig) or {}).get("verdicts") or {}).get(t["code"]) or {}
        ex = explain_in_A(A, sig, t["code"], t["entry_date"], A["dates"])
        exC = explain_in_A(C, sig, t["code"], t["entry_date"], C["dates"])
        main_c = main_map.main(t["code"], t["entry_date"])
        fl = delivery_flags_for_date(t["code"], t["entry_date"], front_contract=main_c) if main_c else {}
        mem = (B["member"].get(t["code"]) or {}).get(sig)
        pair = ((B["carry"].get(t["code"]) or {}).get(sig))
        rows.append({
            "code": t["code"], "dir": t["dir"], "signal_day": sig, "entry_date": t["entry_date"], "exit_date": t["exit_date"], "reason": t["reason"],
            "in_C": key(t) in kC,
            "B": {"status": vB.get("status"), "seat_label": vB.get("seat_label"), "seat_short": vB.get("seat_short"), "carry": vB.get("carry"),
                  "main_contract_on_fill_day": main_c, "main_contract_in_delivery_window": bool(fl.get("delivery_restricted")), "sessions_to_last_trade": fl.get("sessions_to_last_trade"),
                  "seat_row_present": mem is not None, "carry_pair_present": pair is not None},
            "A": ex, "C": exC,
        })
    rows_A = []
    for t in only_A:  # the reverse direction: why B did not take these
        sig = prev_date(A["dates"], t["entry_date"])
        rows_A.append({"code": t["code"], "dir": t["dir"], "signal_day": sig, "entry_date": t["entry_date"], "B": explain_in_A(B, sig, t["code"], t["entry_date"], B["dates"])})
    # ---- A-side summary of why they are absent ------------------------------------------------------------------
    summ_A = Counter(r["A"]["where"] for r in rows)
    summ_C = Counter(r["C"]["where"] for r in rows)
    # ---- signal-level concordance (days both evaluated) ---------------------------------------------------------------
    conc = Counter()
    for d, eb in B["clog"].items():
        ea = A["clog"].get(d)
        if ea is None:
            continue
        for code, vb in (eb.get("verdicts") or {}).items():
            va = (ea.get("verdicts") or {}).get(code)
            sa = (va or {}).get("status", "not_evaluated")
            sb = vb.get("status")
            conc[(sa, sb)] += 1
    # ---- fill-time quality gate: where do flags come from? ---------------------------------------------------------
    flagged = {nm: sum(1 for c in cells[nm]["series"].values() for b in c.values() if b.get("delivery_restricted")) for nm in "ABC"}
    flags_B_main = Counter()  # every B entry: is the traded main contract itself inside the no-new-position window?
    for t in tB:
        mc = main_map.main(t["code"], t["entry_date"])
        fl = delivery_flags_for_date(t["code"], t["entry_date"], front_contract=mc) if mc else {}
        flags_B_main["in_window" if fl.get("delivery_restricted") else "outside"] += 1
    flags_A_main = Counter()
    for t in tA:
        mc = main_map.main(t["code"], t["entry_date"])
        fl = delivery_flags_for_date(t["code"], t["entry_date"], front_contract=mc) if mc else {}
        flags_A_main["in_window" if fl.get("delivery_restricted") else "outside"] += 1
    # ---- seats / carry data alignment ------------------------------------------------------------------------------
    def cmp_dict(x, y, lo="2026-01-01"):
        diff = 0
        n = 0
        for c in set(x) | set(y):
            dx, dy = x.get(c) or {}, y.get(c) or {}
            for d in set(dx) | set(dy):
                if d >= lo:
                    n += 1
                    if dx.get(d) != dy.get(d):
                        diff += 1
        return {"cells": n, "differ": diff}
    align = {"member_A_vs_B": cmp_dict(A["member"], B["member"]), "carry_A_vs_B": cmp_dict({c: v for c, v in A["carry"].items()}, {c: v for c, v in B["carry"].items()})}
    # silent-pass accounting among entered trades: no seat row / no carry pair on the signal day
    def silent(cell, trades):
        out = Counter()
        for t in trades:
            sig = prev_date(cell["dates"], t["entry_date"])
            v = ((cell["clog"].get(sig) or {}).get("verdicts") or {}).get(t["code"]) or {}
            out["trades"] += 1
            if v.get("seat_short"):
                out["seat_filter_skipped_seat_short"] += 1
            elif (cell["member"].get(t["code"]) or {}).get(sig) is None:
                out["seat_row_missing_not_short"] += 1
            if ((cell["carry"].get(t["code"]) or {}).get(sig)) is None:
                out["carry_pair_missing"] += 1
        return dict(out)
    sil = {"A": silent(A, tA), "B": silent(B, tB), "B_only": silent(B, only_B)}
    sg = {nm: {"seat_days_min": min((cells[nm]["out"]["seat_gate"]["seat_days"] or {0: 0}).values()), "skipped_seat_filter_signals": cells[nm]["out"]["seat_gate"]["skipped_seat_filter_signals"]} for nm in "ABC"}
    # which codes never have a seat book (DCE): trades per cell on those codes
    short_codes = set(cells["B"]["out"]["seat_gate"]["skipped_seat_filter_signals"])
    dce_trades = {nm: sum(1 for t in trades_of(cells[nm]) if t["code"] in short_codes) for nm in "ABC"}
    # ---- carry pair vs official contracts ---------------------------------------------------------------------------
    from contract_loader import load_all

    by = load_all()
    byd = defaultdict(dict)  # (code, date) -> {contract: row}
    import re

    for contract, dd in by.items():
        m = re.match(r"([A-Za-z]+)\d+", contract)
        if not m:
            continue
        for d, r in dd.items():
            if d >= "2025-10-01":
                byd[(m.group(1).upper(), d)][contract] = r

    def _exp(c):
        return int(re.findall(r"\d+", c)[-1])

    dts = B["dates"]

    def ident(code, d):
        """The carry pair at key d is the raw pair of the previous session (availability lag 1)."""
        i = dts.index(d) if d in dts else None
        pair = (B["carry"].get(code) or {}).get(d)
        if not i or not pair:
            return None
        src = dts[i - 1]
        cand = {c: r for c, r in (byd.get((code.upper(), src)) or {}).items() if (r.get("oi") or 0) > 0 or (r.get("volume") or 0) > 0}
        nm = [c for c, r in cand.items() if abs(float(r["close"]) - pair[0]) < 1e-6]
        fm = [c for c, r in cand.items() if abs(float(r["close"]) - pair[1]) < 1e-6]
        alive = sorted(cand, key=_exp)
        return {"src": src, "near": nm, "far": fm, "official_main": main_map.main(code, src), "nearest_two_alive": alive[:2]}

    carry_blocked = [(code, d, v.get("blocked")) for d, eb in B["clog"].items() for code, v in (eb.get("verdicts") or {}).items() if v.get("block_kind") == "carry"]
    match = Counter()
    for nm_, items in (("all_pairs", [(c, d) for c, cc in B["carry"].items() for d in cc if "2026-01-05" <= d <= "2026-11-25"]),
                       ("carry_blocked_in_B", [(c, d) for c, d, _ in carry_blocked])):
        for c, d in items:
            r = ident(c, d)
            if r is None:
                continue
            mc = r["official_main"]
            match[nm_ + ":n"] += 1
            match[nm_ + ":near_identified"] += bool(r["near"])
            match[nm_ + ":near_is_nearest_alive_official"] += bool(r["nearest_two_alive"] and r["nearest_two_alive"][0] in r["near"])
            match[nm_ + ":near_is_official_main"] += bool(mc and mc in r["near"])
            match[nm_ + ":far_is_official_main"] += bool(mc and mc in r["far"])
            match[nm_ + ":pair_contains_official_main"] += bool(mc and (mc in r["near"] or mc in r["far"]))
    ex_pair = []
    for c, d, why in carry_blocked[:: max(1, len(carry_blocked) // 8)][:8]:
        ex_pair.append({"code": c, "day": d, "why": why, **(ident(c, d) or {})})
    seat_info = {"seat_days_B": B["out"]["seat_gate"]["seat_days"],
                 "seat_first_date_B": {c: (min([k for k, v in m.items() if isinstance(v, dict)] or [None]) if m else None) for c, m in B["member"].items()}}
    result = {
        "counts": {"A": len(tA), "B": len(tB), "C": len(tC), "common_A_B": len(common), "only_B": len(only_B), "only_A": len(only_A), "B_not_in_C": sum(1 for t in tB if key(t) not in kC)},
        "only_B_why_absent_in_A": dict(summ_A), "only_B_why_absent_in_C": dict(summ_C),
        "only_A_codes": [(t["code"], t["entry_date"]) for t in only_A], "only_A_why_absent_in_B": dict(Counter(r["B"]["where"] for r in rows_A)), "rows_only_A": rows_A,
        "only_B_fill_flag_kinds": dict(Counter(("hard_window(<=5 sessions)" if r["A"].get("fill_flags", {}).get("delivery_restricted") else "near_only(6-10 sessions)") for r in rows if r["A"]["where"] == "fill_time_quality")),        "quality_blocks": {nm: cells[nm]["out"]["quality_blocks"] for nm in "ABC"},
        "bars_stamped_delivery_restricted": flagged,
        "entries_into_main_contract_inside_no_new_window": {"A_trades": dict(flags_A_main), "B_trades": dict(flags_B_main)},
        "seat_gate": sg, "dce_trades_without_seat_book": dce_trades, "silent_pass_among_trades": sil, "alignment": align,
        "carry_pair_vs_official_contracts": dict(match), "carry_blocked_examples": ex_pair, "seat_info": seat_info,
        "status_concordance_days_both_evaluated": {f"{a}->{b}": n for (a, b), n in sorted(conc.items(), key=lambda x: -x[1])},
        "signal_candidates": {nm: cells[nm]["out"]["signal_candidates"] for nm in "ABC"},
        "blocks": {nm: cells[nm]["out"]["blocks"] for nm in "ABC"},
        "rows": rows,
    }
    (HERE / "ATTRIB" / "trades138.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for k, v in result.items():
        if k != "rows":
            print(k, json.dumps(v, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
