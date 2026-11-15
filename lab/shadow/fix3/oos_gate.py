"""fix3 gates on the formal engine (freeze_fix on), snapshot bt_input_20261113.

1) Truncation lookahead: cut at 3/31, 6/30, 8/31, 10/15 -> entries on/before cut identical to full run.
2) Locked OOS: train <=2026-08-31 (grid chosen on truncated data only), test 2026-09-01 -> end.
   Reports best-by-train, formal 0.8/2R, train/test rank corr, trade counts, PBO (CSCV on full-period daily returns).
Shadow only; reads formal files, writes nothing outside lab/shadow/fix3/ (only when run as script).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import replay as R  # noqa: E402
import variants as V  # noqa: E402
import historical_backtest as hb  # noqa: E402

CUTS = ("2026-03-31", "2026-06-30", "2026-08-31", "2026-10-15")
TR_END, TE_A = "2026-08-31", "2026-09-01"


def trunc(bars, end):
    return {c: [b for b in h if b["date"] <= end] for c, h in bars.items()}


def entries(out):
    a = {(t["code"], t["entry_date"], t["direction"], round(t["entry"], 2)) for t in out["closed_pnls"]}
    b = {(c, q["entry_date"], q["direction"], round(q["entry"], 2)) for c, q in (out.get("final_positions") or {}).items()}
    return a | b


def lookahead(bars=None, **kw):
    bars = bars or R.snap["bars"]
    p, pack = R.make_pack(bars)
    fe = entries(R.run(p, pack, **kw))
    res = {}
    for cut in CUTS:
        p, pack = R.make_pack(trunc(bars, cut))
        te = entries(R.run(p, pack, **kw))
        a = {x for x in fe if x[1] <= cut}
        b = {x for x in te if x[1] <= cut}
        res[cut] = {"full_entries": len(a), "trunc_entries": len(b), "only_full": sorted(a - b), "only_trunc": sorted(b - a), "ok": a == b}
    return res


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    for k, i in enumerate(order):
        r[i] = float(k)
    return r


def _corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((x - mb) ** 2 for x in b) ** 0.5
    return None if not va or not vb else sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb)


def daily_returns(out):
    cur = out["equity_curve"]
    return {cur[i]["date"]: cur[i]["equity"] / cur[i - 1]["equity"] - 1 for i in range(1, len(cur))}


def oos(bars=None, **kw):
    bars = bars or R.snap["bars"]
    end = max(b["date"] for h in bars.values() for b in h)
    train_bars = trunc(bars, TR_END)
    assert max(b["date"] for h in train_bars.values() for b in h) <= TR_END
    rows, rets = [], {}
    for s in hb.STOP_GRID:
        for rr in hb.RR_GRID:
            p, pack = R.make_pack(train_bars)
            tr = R.run(p, pack, stop_atr_mult=s, reward_rr=rr, **kw)  # selection input: train only
            p, pack = R.make_pack(bars)
            fu = R.run(p, pack, stop_atr_mult=s, reward_rr=rr, **kw)  # evaluation only
            te = V.seg_ret(fu, TE_A, end)
            rows.append({"stop": s, "rr": rr, "train_ret": tr["ret_pct"], "train_dd": tr["max_dd_pct"], "train_n": tr["closed_trades"],
                         "train_calmar": round(tr["ret_pct"] / tr["max_dd_pct"], 3) if tr["max_dd_pct"] else None,
                         "test_ret": te[0], "test_dd": te[1], "test_n": te[2]})
            rets[f"{s}/{rr}"] = daily_returns(fu)
    best = max(rows, key=lambda r: (r["train_calmar"] if r["train_calmar"] is not None else -99, r["train_ret"]))
    formal = next(r for r in rows if r["stop"] == 0.8 and r["rr"] == 2.0)
    rc = _corr(_rank([r["train_ret"] for r in rows]), _rank([r["test_ret"] for r in rows]))
    names = list(rets)
    dates = sorted(set().union(*[set(v) for v in rets.values()]))
    mat = [[rets[n].get(d, 0.0) for n in names] for d in dates]
    from lab.validation.pbo import probability_of_backtest_overfitting

    pbo = probability_of_backtest_overfitting(mat, n_groups=8)
    return {"train_end": TR_END, "test": [TE_A, end], "rows": rows, "best_by_train_calmar": best, "formal_0.8_2": formal,
            "train_test_rank_corr": None if rc is None else round(rc, 3),
            "pbo": {k: pbo.get(k) for k in ("ok", "pbo", "n_combos", "n_groups", "error") if k in pbo},
            "test_trades_best": best["test_n"], "test_trades_formal": formal["test_n"], "n_trials": len(rows)}


if __name__ == "__main__":
    res = {"lookahead": lookahead(), "oos": oos()}
    print(json.dumps({"lookahead": {k: (v["full_entries"], v["ok"]) for k, v in res["lookahead"].items()},
                      "best": res["oos"]["best_by_train_calmar"], "formal": res["oos"]["formal_0.8_2"],
                      "rank_corr": res["oos"]["train_test_rank_corr"], "pbo": res["oos"]["pbo"]}, ensure_ascii=False, indent=1))
    (HERE / "oos_gate_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
