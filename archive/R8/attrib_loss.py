# -*- coding: utf-8 -*-
"""R8 closeout appendix A.2: loss attribution of the long-sample A1000k (read-only; reads the committed OOS result + seed data)."""
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

DCE = ("V", "EG", "M", "EB", "PP", "L", "JD", "P", "I", "JM")
PERIODS = {"2016": ("2016", "2016"), "2017-2021": ("2017", "2021"), "2022-2025": ("2022", "2025")}


def per_of(y):
    for k, (a, b) in PERIODS.items():
        if a <= y <= b:
            return k


def main() -> int:
    uni = {u["code"]: u for u in json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))["symbols"]}
    res = {s: json.loads((HERE / "OOS" / "A1000k" / f"result_{s}.json").read_text(encoding="utf-8")) for s in ("base", "stress")}
    out = {}
    for sc in ("base", "stress"):
        tr = res[sc]["trades"]
        yb, ys, yr = defaultdict(float), defaultdict(float), defaultdict(float)
        n_yb = Counter()
        for t in tr:
            y = t["entry_date"][:4]
            b = uni[t["code"]].get("bucket")
            yb[(y, b)] += t["net"]; ys[(y, t["code"])] += t["net"]; n_yb[(y, b)] += 1
        reason = defaultdict(lambda: [0, 0.0])
        for t in tr:
            k = (per_of(t["entry_date"][:4]), t["reason"]); reason[k][0] += 1; reason[k][1] += t["net"]
        roll = defaultdict(lambda: [0, 0.0, 0.0])
        for t in tr:
            k = (per_of(t["entry_date"][:4]), "rolled" if t["n_rolls"] else "no_roll")
            roll[k][0] += 1; roll[k][1] += t["net"]
        # exit-reason / roll cost: re-cost the roll fills only
        import historical_backtest as hb
        rc = defaultdict(float)
        for t in tr:
            if not t["n_rolls"]:
                continue
            m = uni[t["code"]]
            # cost of a trade minus its entry+exit cost = roll cost
            kw = dict(slippage_ticks=float(res[sc]["slippage_ticks"]), fee_mult=float(res[sc]["fee_mult"]))
            base_c = hb.fill_cost(m, float(t["entry_orig"] if t.get("entry_orig") is not None else t["entry"]), int(t["lots"]), **kw) + hb.fill_cost(m, float(t["exit"]), int(t["lots"]), **kw)
            rc[per_of(t["entry_date"][:4])] += float(t["cost"]) - base_c
        per_sym = defaultdict(lambda: defaultdict(float))
        per_bucket = defaultdict(lambda: defaultdict(float))
        for t in tr:
            p = per_of(t["entry_date"][:4])
            per_sym[p][t["code"]] += t["net"]; per_bucket[p][uni[t["code"]].get("bucket")] += t["net"]
        conc = {}
        for p, d in per_sym.items():
            tot = sum(d.values()); losers = sorted((v, c) for c, v in d.items() if v < 0)
            neg = sum(v for v, _ in losers)
            conc[p] = {"net": round(tot), "gross_loss_symbols": round(neg), "top5_loss": [(c, round(v)) for v, c in losers[:5]],
                       "top5_share_of_symbol_losses": round(sum(v for v, _ in losers[:5]) / neg, 3) if neg else None,
                       "n_losing_symbols": len(losers), "n_symbols": len(d)}
        out[sc] = {
            "by_year_bucket": {f"{y}|{b}": [n_yb[(y, b)], round(v)] for (y, b), v in sorted(yb.items(), key=lambda x: (x[0][0], str(x[0][1])))},
            "by_year_symbol": {f"{y}|{c}": round(v) for (y, c), v in sorted(ys.items())},
            "by_period_reason": {f"{p}|{r}": [v[0], round(v[1])] for (p, r), v in sorted(reason.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))},
            "by_period_roll": {f"{p}|{r}": [v[0], round(v[1])] for (p, r), v in sorted(roll.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))},
            "roll_cost_by_period": {p: round(v) for p, v in rc.items()},
            "by_period_bucket": {p: {b: round(v) for b, v in d.items()} for p, d in per_bucket.items()},
            "by_period_symbol": {p: {c: round(v) for c, v in sorted(d.items(), key=lambda x: x[1])} for p, d in per_sym.items()},
            "concentration": conc,
        }

    # ---- DCE settle gap (from seed data) ---------------------------------------------------------------------------------
    from contract_loader import load_all
    import re

    by = load_all()
    def code_of(c):
        m = re.match(r"([A-Za-z]+)", c); return m.group(1).upper() if m else c
    miss = defaultdict(lambda: [0, 0])  # month -> [missing, total] for DCE
    for c, rows in by.items():
        if code_of(c) not in DCE:
            continue
        for d, r in rows.items():
            if not (r.get("volume") or 0) > 0:
                continue
            k = d[:7]
            miss[k][1] += 1
            if not (r.get("settle") or 0) > 0:
                miss[k][0] += 1
    official_missing_months = {k: round(v[0] / v[1], 3) for k, v in sorted(miss.items()) if v[1] and v[0]}
    # the registered settle gap lives in the LOCAL cached continuous series (LONG_COVERAGE_REPORT): measure it there
    lmiss = defaultdict(lambda: [0, 0])
    for code in DCE:
        for b in json.loads((ROOT / ".cache" / "history" / f"{code}0.json").read_text(encoding="utf-8")):
            k = str(b["date"])[:7]
            lmiss[k][1] += 1
            if not (b.get("settle") or 0) > 0:
                lmiss[k][0] += 1
    gap_months = {k: round(v[0] / v[1], 3) for k, v in sorted(lmiss.items()) if v[1] and v[0] / v[1] > 0.5}
    share_by_month = {k: round(v[0] / v[1], 3) for k, v in sorted(lmiss.items()) if v[1] and v[0]}
    gm = sorted(k for k in gap_months if "2019-12" <= k <= "2020-12")  # the 2019-12 .. 2020-08 gap asked about
    gap = (gm[0] + "-01", gm[-1] + "-31") if gm else None
    # engine: does A read settle at all?
    import re as _re
    src = "".join((ROOT / f).read_text(encoding="utf-8") for f in ("book_core.py", "signal_core.py", "position_rules.py") if (ROOT / f).exists())
    reads_settle = bool(_re.search(r"settle", src))
    dce_trades = {}
    if gap:
        for sc in ("base", "stress"):
            tr = res[sc]["trades"]
            inside = [t for t in tr if (gap[0] <= t["entry_date"] <= gap[1]) or (gap[0] <= t["date"] <= gap[1])]
            dce_in = [t for t in inside if t["code"] in DCE]
            oth_in = [t for t in inside if t["code"] not in DCE]
            tot = [t for t in tr if "2019" <= t["entry_date"][:4] <= "2021"]
            loss1921 = sum(t["net"] for t in tot)
            dce1921 = sum(t["net"] for t in tot if t["code"] in DCE)
            dce_trades[sc] = {"dce_in_gap_n": len(dce_in), "dce_in_gap_net": round(sum(t["net"] for t in dce_in)),
                              "other_in_gap_n": len(oth_in), "other_in_gap_net": round(sum(t["net"] for t in oth_in)),
                              "all_2019_2021_net": round(loss1921), "dce_2019_2021_net": round(dce1921), "dce_2019_2021_n": sum(1 for t in tot if t["code"] in DCE)}
    out["dce_settle_gap"] = {"months_over_50pct_missing_local_cache": gap_months, "interval": gap, "months_with_any_missing_local_cache": share_by_month,
                             "official_months_with_missing_settle": official_missing_months,
                             "engine_modules_mention_settle": reads_settle, "trades": dce_trades}

    # ---- positions_full by year (needs the event categories: re-run A1000k Base; identical to the committed result) --------
    pack, mm, store, info = ls.build_official_pack()
    r = ls.run_long("A", 1_000_000.0, "base", pack, mm, store)
    ev = r["ev_cat"]
    yc = defaultdict(Counter)
    for (d, c), k in ev.items():
        yc[d[:4]][k] += 1
    curve = r["out"]["equity_curve"]
    days_y = Counter(x["date"][:4] for x in curve)
    clog = r["clog_days"]
    free_y = Counter(d[:4] for d in clog)  # days on which A evaluated candidates (slots_left > 0)
    out["positions_full_by_year"] = {y: {"trade_days": days_y[y], "days_with_free_slot": free_y[y], **dict(yc[y])} for y in sorted(days_y)}
    tot_pf = sum(v.get("positions_full", 0) for v in out["positions_full_by_year"].values())
    out["positions_full_total"] = tot_pf
    (HERE / "ATTRIB").mkdir(exist_ok=True)
    (HERE / "ATTRIB" / "loss_attribution.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("gap interval", gap, "reads settle", reads_settle, "positions_full total", tot_pf)
    print(json.dumps(out["dce_settle_gap"]["trades"], ensure_ascii=False))
    print(json.dumps({sc: out[sc]["concentration"] for sc in ("base",)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
