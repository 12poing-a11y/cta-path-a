# -*- coding: utf-8 -*-
"""R8 evaluation exactly as pre-registered in archive/R8/PREREG.md (no threshold / definition changed).

usage: python archive/R8/_evaluate.py            (groups fixed by PREREG: base, E100k..E1000k, F1, F2, F1F2)
Reads archive/R8/<group>/result.json (live runs); replays each group offline on the frozen snapshot of the control run
(all groups share its bars_sha256) to get skip categories / candidate attributes and to prove offline == live.
Writes archive/R8/results_table.json and results_table.md.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
R8 = ROOT / "archive" / "R8"

R8A = ["E100k", "E300k", "E500k", "E1000k"]
R8B = ["F1", "F2", "F1F2"]
CONTROL_R8B = "E1000k"
N_TRIALS_MAIN, N_TRIALS_DISCLOSURE = 18, 21


def jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


def price_pnl(t, mult):
    d = 1.0 if str(t["direction"]) in ("多", "long", "buy") else -1.0
    return d * (float(t["exit"]) - float(t["entry"])) * int(t["lots"]) * mult.get(t["code"], 1.0)


def main() -> int:
    from lab.validation.dsr import deflated_sharpe_ratio
    from lab.validation.pbo import probability_of_backtest_overfitting
    from lab.validation.psr import probabilistic_sharpe_ratio
    from lab.validation.trial_matrix import _curve_to_dated_returns as returns_of
    from lab.validation.walk_forward import walk_forward_segments
    from research.execution import entry_filters as ef
    import _r8_lib

    names = ["base"] + R8A + R8B
    res = {g: jload(R8 / g / "result.json") for g in names if (R8 / g / "result.json").is_file()}
    base = res["base"]
    base_in = {k: base["input_snapshot"][k] for k in ("bars_sha256", "member_sha256", "carry_sha256", "contract_bars_sha256")}
    snap_path = ROOT / base["input_snapshot"]["path"]
    bt_path = R8 / "base" / "result.json"
    mx = jload(ROOT / "lab" / "research" / "validation" / "pbo_path_a_matrix.json")
    mdates, mat = mx["dates"], mx["returns"]
    mult = {u["code"]: float(u.get("mult") or 1) for u in jload(ROOT / "universe.json")["symbols"]}

    # ---- replays + per-group metrics ---------------------------------------------------------
    rp, rows, cols = {}, {}, {}
    for g, r in res.items():
        ov = (r.get("r8_overrides") or {}).get("applied") or {}
        rp[g] = _r8_lib.replay_group(snap_path, bt_path, ov)
        off = rp[g]["out"]
        st = r["cost_scenario_contrast"]["rows"].get("stress") or {}
        curve = r["equity_curve"]
        eq_by_day = {x["date"]: float(x["equity"]) for x in curve}
        dates = [x["date"] for x in curve]
        risks = []
        for t in r["closed_pnls"]:
            prev = [d for d in dates if d < t["entry_date"]]
            e0 = eq_by_day.get(prev[-1]) if prev else r.get("equity_start")
            if e0:
                risks.append(abs(float(t["entry"]) - float(t["stop"])) * int(t["lots"]) * mult.get(t["code"], 1.0) / e0 * 100.0)
        rets = returns_of(curve)
        r_list = [rets[d] for d in mdates]
        cols[g] = r_list
        wf = walk_forward_segments(r_list, n_folds=5)
        fold_sh = [f.get("sharpe") for f in wf.get("folds", [])]
        psr = probabilistic_sharpe_ratio(r_list)
        live_hits = (r.get("entry_filters") or {}).get("hits")
        rows[g] = {
            "group": g, "equity0": r.get("equity_start"),
            "filters": [k for k in ("filter_unit_risk", "filter_atr_spike") if ov.get(k)],
            "ret_base": r.get("ret_pct"), "ret_stress": st.get("ret_pct"),
            "dd_base": r.get("max_dd_pct"), "dd_stress": st.get("max_dd_pct"),
            "trades": r.get("closed_trades"), "trades_stress": st.get("closed_trades"),
            "skips": rp[g]["skips"], "filter_hits": rp[g]["filter_hits"],
            "selected_entries": rp[g]["selected_entries"],
            "days_positions_full": len(dates) - rp[g]["candidate_days"],
            "held_distribution": dict(sorted(Counter(int(x.get("held") or 0) for x in curve).items())),
            "risk_max": round(max(risks), 3) if risks else None,
            "risk_median": round(statistics.median(risks), 3) if risks else None,
            "gross_curve_max": max(float(x.get("gross_pct") or 0) for x in curve),
            "caps_entry_gross_max": r.get("caps_entry_gross_max"),
            "psr": psr.get("psr"),
            "dsr18": deflated_sharpe_ratio(r_list, n_trials=N_TRIALS_MAIN, mean_abs_corr=0.0).get("dsr"),
            "dsr21": deflated_sharpe_ratio(r_list, n_trials=N_TRIALS_DISCLOSURE, mean_abs_corr=0.0).get("dsr"),
            "pbo": probability_of_backtest_overfitting([row + [x] for row, x in zip(mat, r_list)], n_groups=8).get("pbo"),
            "wf_fold_sharpes": fold_sh, "wf_positive": sum(1 for s in fold_sh if (s or 0) > 0),
            "cost_yuan": r.get("cost_yuan"),
            "same_bars_as_base": {k: r["input_snapshot"][k] for k in base_in} == base_in,
            "offline_equals_live": canon(off.get("closed_pnls")) == canon(r.get("closed_pnls"))
                                   and canon(off.get("equity_curve")) == canon(r.get("equity_curve")),
            "live_filter_hits": live_hits,
            "filters_hits_match_live": (rp[g]["filter_hits"] == live_hits) if ov.get("filter_unit_risk") or ov.get("filter_atr_spike") else None,
            "role": "control" if g == "base" else ("R8a (diagnostic)" if g in R8A else "R8b"),
        }

    # per-fold vs control (R8b control = E1000k)
    ctrl_sh = rows[CONTROL_R8B]["wf_fold_sharpes"]
    for g in R8B:
        if g in rows:
            rows[g]["wf_vs_control"] = ["better" if (a or 0) > (b or 0) else ("worse" if (a or 0) < (b or 0) else "equal")
                                        for a, b in zip(rows[g]["wf_fold_sharpes"], ctrl_sh)]

    # ---- filtered-out trades (PREREG sec. 4): control trades whose entry candidate the filter would stop -------
    ctrl = res[CONTROL_R8B]
    cdates = [x["date"] for x in ctrl["equity_curve"]]
    half = len(cdates) // 2
    h1_dates = set(cdates[:half])
    attr = rp[CONTROL_R8B]["cand_attr"]
    pct = float(rp[CONTROL_R8B]["p"]["max_gross_pct"])

    def blocked(a, kind):
        n = ef.unit_notional_exceeds(a["close"], a["mult"], a["sizing_eq"], pct)
        s = ef.atr_spike(a["atr14"], a["atr100"]) is True
        return {"F1": n, "F2": s, "F1F2": n or s}[kind]

    ctrl_keys = {(t["code"], t["entry_date"]): t for t in ctrl["closed_pnls"]}
    missing = 0
    for g in R8B:
        if g not in res:
            continue
        half_rec = {"H1": {"n": 0, "pnl": 0.0, "R": 0.0, "trades": []}, "H2": {"n": 0, "pnl": 0.0, "R": 0.0, "trades": []}}
        for t in ctrl["closed_pnls"]:
            prev = [d for d in cdates if d < t["entry_date"]]
            a = attr.get((prev[-1], t["code"])) if prev else None
            if a is None:
                missing += 1
                continue
            if blocked(a, g):
                h = "H1" if t["entry_date"] in h1_dates else "H2"
                pnl = price_pnl(t, mult)
                half_rec[h]["n"] += 1
                half_rec[h]["pnl"] += pnl
                half_rec[h]["R"] += float(t.get("R") or 0)
                half_rec[h]["trades"].append({"code": t["code"], "entry_date": t["entry_date"], "pnl": round(pnl, 2), "R": t.get("R")})
        for h in half_rec.values():
            h["pnl"], h["R"] = round(h["pnl"], 2), round(h["R"], 3)
        grp_keys = {(t["code"], t["entry_date"]): t for t in res[g]["closed_pnls"]}
        gone = [ctrl_keys[k] for k in ctrl_keys if k not in grp_keys]
        new = [grp_keys[k] for k in grp_keys if k not in ctrl_keys]
        rows[g]["filtered_trades"] = {
            "split_at_trade_date_index": half, "first_half_through": cdates[half - 1],
            "H1": half_rec["H1"], "H2": half_rec["H2"],
            "path_view_control_trades_absent_in_group": {"n": len(gone), "price_pnl": round(sum(price_pnl(t, mult) for t in gone), 2)},
            "path_view_new_trades_in_group": {"n": len(new), "price_pnl": round(sum(price_pnl(t, mult) for t in new), 2)},
        }
    # ---- criteria (R8b only) ------------------------------------------------------------------
    c0 = rows[CONTROL_R8B]
    for g in R8B:
        if g not in rows:
            continue
        r = rows[g]
        ft = r["filtered_trades"]
        crit = {
            "1_returns": bool(r["ret_base"] > 0 and r["ret_base"] > c0["ret_base"] and r["ret_stress"] > 0 and r["ret_stress"] > c0["ret_stress"]),
            "2_drawdown_le_10": bool(r["dd_base"] <= 10 and r["dd_stress"] <= 10),
            "3_single_trade_risk_le_3": bool(r["risk_max"] is not None and r["risk_max"] <= 3.0),
            "4_pbo_le_0.5": bool(r["pbo"] is not None and r["pbo"] <= 0.5),
            "5_walk_forward_ge_3": bool(r["wf_positive"] >= 3),
            "6_filtered_net_losing_both_halves": bool(ft["H1"]["n"] > 0 and ft["H1"]["pnl"] < 0 and ft["H2"]["n"] > 0 and ft["H2"]["pnl"] < 0),
        }
        r["criteria"] = crit
        r["numeric_pass_1_6"] = all(crit.values())
    for g in R8A:
        r = rows[g]
        r["info_not_judged"] = {"dd_le_10": bool(r["dd_base"] <= 10 and r["dd_stress"] <= 10), "risk_le_3": bool(r["risk_max"] <= 3.0),
                                "pbo_le_0.5": bool(r["pbo"] <= 0.5), "wf_ge_3": bool(r["wf_positive"] >= 3)}

    fam = [row + [cols[g][i] for g in names[1:]] for i, row in enumerate(mat)]
    fam_pbo = probability_of_backtest_overfitting(fam, n_groups=8)
    out = {"prereg": "archive/R8/PREREG.md", "n_trials_main": N_TRIALS_MAIN, "n_trials_disclosure": N_TRIALS_DISCLOSURE,
           "r8b_control": CONTROL_R8B, "trade_attr_missing_for_control_trades": missing,
           "family_pbo_reference": {"pbo": fam_pbo.get("pbo"), "K": len(mat[0]) + len(names) - 1},
           "stop_rule_r8a": {"all_base_le_0": all(rows[g]["ret_base"] <= 0 for g in R8A)}, "rows": rows}
    (R8 / "results_table.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def sk(r):
        s = r["skips"]
        t = (f"0手{s.get('lots0', 0)}/名义帽→0 {s.get('gross_cap_to_0', 0)}/持仓满{s.get('positions_full', 0)}"
             f"(满仓日{r['days_positions_full']}天)/板块满{s.get('bucket_full', 0)}")
        h = r["filter_hits"]
        if h and (h.get("unit_notional") or h.get("atr_spike") or h.get("evaluated")):
            t += f"/过滤拦下 名义{h.get('unit_notional', 0)} 波动{h.get('atr_spike', 0)}"
        return t

    def ftxt(g):
        ft = rows[g].get("filtered_trades")
        if not ft:
            return "-"
        a, b = ft["H1"], ft["H2"]
        return f"前{a['n']}笔 {a['pnl']:+,.0f}元 / 后{b['n']}笔 {b['pnl']:+,.0f}元"

    md = ["| 组名 | 本金 | 过滤 | Base | Stress | 回撤 B/S | 笔数 | 跳过信号(信号日) | 被过滤笔数及盈亏 | 单笔风险 最大/中位 | 最高名义占用 | PSR | DSR(18) | PBO | 走步+ | 是否通过 |",
          "|" + "---|" * 16]
    for g in names:
        if g not in rows:
            continue
        r = rows[g]
        verdict = "对照" if g == "base" else ("诊断,不判定" if g in R8A else ("**通过**" if r["numeric_pass_1_6"] else "未通过"))
        md.append(f"| {g} | {r['equity0']:,.0f} | {'+'.join(r['filters']) or '无'} | {r['ret_base']}% | {r['ret_stress']}% | "
                  f"{r['dd_base']}/{r['dd_stress']} | {r['trades']} | {sk(r)} | {ftxt(g)} | {r['risk_max']}/{r['risk_median']} | "
                  f"{r['gross_curve_max']} | {r['psr']:.3f} | {r['dsr18']:.3f} | {r['pbo']:.3f} | {r['wf_positive']}/5 | {verdict} |")
    md += ["", "实际持仓数分布（日末 0/1/2/3 笔的天数）与其他：", "",
           "| 组名 | 持仓分布 | 入场请求(selected) | DSR(21) | offline=live | bars同base | 过滤命中与live一致 |", "|---|---|---|---|---|---|---|"]
    for g in names:
        if g in rows:
            r = rows[g]
            md.append(f"| {g} | {r['held_distribution']} | {r['selected_entries']} | {r['dsr21']:.3f} | {r['offline_equals_live']} | "
                      f"{r['same_bars_as_base']} | {r['filters_hits_match_live']} |")
    md += ["", "R8b 通过标准逐项（只对 F1/F2/F1F2）：", ""]
    for g in R8B:
        if g in rows:
            md.append(f"- {g}: {json.dumps(rows[g]['criteria'], ensure_ascii=False)}；走步每折 vs 对照 {rows[g]['wf_vs_control']}")
    md += ["", f"全族 PBO（参考，K={out['family_pbo_reference']['K']}）= {fam_pbo.get('pbo')}；R8a 停止规则（四档 Base 均≤0）= {out['stop_rule_r8a']['all_base_le_0']}",
           f"对照组交易中无法匹配候选属性的笔数 = {missing}"]
    (R8 / "results_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
