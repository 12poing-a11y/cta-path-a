# -*- coding: utf-8 -*-
"""R8 evaluation exactly as pre-registered in archive/R8/PREREG.md (no thresholds / definitions changed).

usage: python archive/R8/_evaluate.py --groups C0,A70,A100,B300,B500,B1000,C1[,X] --n-trials 18 [--audit-dir ...]
Reads archive/R8/<group>/result.json (live runs), writes archive/R8/results_table.json and .md
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

R8 = ROOT / "archive" / "R8"
CTRL = {"base_ret": -1.721, "stress_ret": -2.339}  # PREREG section 1 (BASE formal root result)


def jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


def returns_of(curve):
    from lab.validation.trial_matrix import _curve_to_dated_returns
    return _curve_to_dated_returns(curve)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", required=True)
    ap.add_argument("--n-trials", type=int, required=True)
    ap.add_argument("--out-name", default="results_table")
    a = ap.parse_args(argv)
    names = [g for g in a.groups.split(",") if g]

    from lab.validation.dsr import deflated_sharpe_ratio
    from lab.validation.pbo import probability_of_backtest_overfitting
    from lab.validation.psr import probabilistic_sharpe_ratio
    from lab.validation.walk_forward import walk_forward_segments
    import _r8_stats

    base = jload(R8 / "base" / "result.json")
    base_in = {k: base["input_snapshot"][k] for k in ("bars_sha256", "member_sha256", "carry_sha256", "contract_bars_sha256")}
    mx = jload(ROOT / "lab" / "research" / "validation" / "pbo_path_a_matrix.json")
    mdates, mat, tids = mx["dates"], mx["returns"], mx["trial_ids"]
    uni = jload(ROOT / "universe.json")
    mult = {u["code"]: float(u.get("mult") or 1) for u in uni["symbols"]}
    snap_path = ROOT / base["input_snapshot"]["path"]
    base_bt_path = R8 / "base" / "result.json"

    rows, cols = [], {}
    # sanity: baseline 'current' column == base group's returns on the matrix dates
    br = returns_of(base["equity_curve"])
    cur_i = tids.index("s0.8_rr2_m4_6")
    cur_col = [r[cur_i] for r in mat]
    sanity = {"matrix_current_col_equals_base_returns": all(abs(br[d] - c) < 1e-12 for d, c in zip(mdates, cur_col)),
              "matrix_T": len(mdates), "matrix_K": len(tids)}

    for g in ["base"] + names:
        res = jload(R8 / g / "result.json")
        ov = (res.get("r8_overrides") or {}).get("applied") or {}
        ins = {k: res["input_snapshot"][k] for k in base_in}
        data_same = ins == base_in
        st = res["cost_scenario_contrast"]["rows"].get("stress") or {}
        stats, off = _r8_stats.run_stats(
            snap_path=snap_path, bt_path=base_bt_path, equity=ov.get("equity0"), max_gross=ov.get("max_gross_pct"),
            min_lots=ov.get("min_lots"))
        offline_equals_live = (canon(off.get("closed_pnls")) == canon(res.get("closed_pnls"))
                               and canon(off.get("equity_curve")) == canon(res.get("equity_curve")))
        rets = returns_of(res["equity_curve"])
        r_list = [rets[d] for d in mdates]
        cols[g] = r_list
        ra = stats["trade_actual_risk_pct"]
        psr = probabilistic_sharpe_ratio(r_list)
        dsr = deflated_sharpe_ratio(r_list, n_trials=a.n_trials, mean_abs_corr=0.0)
        pbo_g = probability_of_backtest_overfitting([row + [x] for row, x in zip(mat, r_list)], n_groups=8)
        wf = walk_forward_segments(r_list, n_folds=5)
        pos_folds = sum(1 for f in wf.get("folds", []) if (f.get("sharpe") or 0) > 0)
        rows.append({
            "group": g,
            "equity0": res.get("equity_start"),
            "max_gross_pct": res.get("max_gross_exposure_pct"),
            "min_lots": res.get("min_lots"),
            "ret_base": res.get("ret_pct"), "ret_stress": st.get("ret_pct"),
            "dd_base": res.get("max_dd_pct"), "dd_stress": st.get("max_dd_pct"),
            "trades": res.get("closed_trades"), "trades_stress": st.get("closed_trades"),
            "skipped_signals_lots0": stats["skipped_signals_lots0"]["signal_days"],
            "lifted_entries": stats["lifted_to_min_lots"]["entered_candidates_lifted"],
            "pre_caps_lifted_days": stats["lifted_to_min_lots"]["pre_caps_candidate_days_lifted_by_sizing"],
            "lifted_closed_trades": stats["lifted_to_min_lots"]["closed_trades_matched"],
            "lifted_risk_max": stats["lifted_to_min_lots"]["actual_risk_pct"]["max"],
            "risk_max": ra["max"], "risk_median": ra["median"],
            "gross_curve_max": stats["gross"]["curve_gross_pct_max"],
            "caps_entry_gross_max": res.get("caps_entry_gross_max"),
            "psr": round(psr.get("psr"), 4) if psr.get("psr") is not None else None,
            "dsr": round(dsr.get("dsr"), 4) if dsr.get("dsr") is not None else None,
            "pbo_g": pbo_g.get("pbo"), "pbo_g_n_obs": pbo_g.get("n_obs"),
            "wf_positive_folds": pos_folds, "wf_fold_sharpes": [f.get("sharpe") for f in wf.get("folds", [])],
            "cost_yuan": res.get("cost_yuan"),
            "data_same_as_base": data_same, "offline_equals_live": offline_equals_live,
        })

    # family PBO (reference only): 11 baseline columns + every run group column
    fam = [row + [cols[g][i] for g in names] for i, row in enumerate(mat)]
    fam_pbo = probability_of_backtest_overfitting(fam, n_groups=8)
    for r in rows:
        if r["group"] == "base":
            continue
        c1 = (r["ret_base"] is not None and r["ret_base"] > 0 and r["ret_base"] > CTRL["base_ret"]
              and r["ret_stress"] is not None and r["ret_stress"] > 0 and r["ret_stress"] > CTRL["stress_ret"])
        c2 = r["dd_base"] <= 10 and r["dd_stress"] is not None and r["dd_stress"] <= 10
        c3 = r["risk_max"] is not None and r["risk_max"] <= 3.0
        c4 = r["pbo_g"] is not None and r["pbo_g"] <= 0.5
        c5 = r["wf_positive_folds"] >= 3
        r["criteria"] = {"1_returns": c1, "2_drawdown": c2, "3_single_trade_risk": c3, "4_pbo": c4, "5_walk_forward": c5}
        r["numeric_pass_1_5"] = all((c1, c2, c3, c4, c5))
    out = {"prereg": "archive/R8/PREREG.md", "n_trials_for_dsr": a.n_trials, "control": CTRL, "sanity": sanity,
           "family_pbo_reference": {"pbo": fam_pbo.get("pbo"), "K": len(mat[0]) + len(names), "n_obs": fam_pbo.get("n_obs")},
           "rows": rows}
    (R8 / f"{a.out_name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    hdr = ("| 组 | 本金 | 名义帽 | min_lots | Base | Stress | 回撤B/S | 笔数 | 跳过 | 抬手 | 单笔风险 最大/中位 | 名义占用(曲线) | PSR | DSR | PBO | 走步+ | 1-5 | 同数据 | 离线=live |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    md = hdr
    for r in rows:
        md += (f"| {r['group']} | {r['equity0']:.0f} | {r['max_gross_pct']} | {r['min_lots']} | {r['ret_base']}% | "
               f"{r['ret_stress']}% | {r['dd_base']}/{r['dd_stress']} | {r['trades']} | {r['skipped_signals_lots0']} | "
               f"{r['lifted_entries']} | {r['risk_max']}/{r['risk_median']} | {r['gross_curve_max']} | {r['psr']} | "
               f"{r['dsr']} | {r['pbo_g']} | {r['wf_positive_folds']}/5 | "
               f"{'-' if r['group']=='base' else ('PASS' if r['numeric_pass_1_5'] else 'fail')} | "
               f"{r['data_same_as_base']} | {r['offline_equals_live']} |\n")
    (R8 / f"{a.out_name}.md").write_text(md + f"\n全族 PBO（参考，K={out['family_pbo_reference']['K']}）= {fam_pbo.get('pbo')}\n"
                                         f"sanity: {json.dumps(sanity)}\n", encoding="utf-8")
    print(md)
    print("family PBO", out["family_pbo_reference"], "sanity", sanity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
