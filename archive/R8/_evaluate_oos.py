# -*- coding: utf-8 -*-
"""R8 long-sample verdict: PREREG_OOS sec. 3-7 + Appendix 1 sec. 4/6 reporting.  Reads archive/R8/OOS/<group>/, writes
OOS_VERDICT.json and OOS_VERDICT.md.  Only the sec. 7 criteria produce verdicts; DSR/PSR are reported, never a condition."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

OOS = HERE / "OOS"
LEVELS = {"800k": 800_000.0, "1000k": 1_000_000.0, "1200k": 1_200_000.0}
N_TRIALS = 30


def jl(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main() -> int:
    import historical_backtest as hb
    from lab.validation.dsr import deflated_sharpe_ratio
    from lab.validation.psr import probabilistic_sharpe_ratio
    from lab.validation.trial_matrix import _curve_to_dated_returns as returns_of
    from research.execution import entry_filters as ef

    uni = {u["code"]: u for u in jl(ROOT / "universe.json")["symbols"]}
    R, info = {}, jl(OOS / "A1000k" / "run_info.json")
    for kind in "ABC":
        for lvl in LEVELS:
            g = f"{kind}{lvl}"
            R[g] = {s: jl(OOS / g / f"result_{s}.json") for s in ("base", "stress")}
            for s in ("base", "stress"):
                r = R[g][s]
                assert r["start"] >= "2016-01-01" and r["end"] <= "2025-12-31", (g, s, r["start"], r["end"])
    assert info["max_loaded_date"] <= "2025-12-31"

    # ---- per-group metrics ------------------------------------------------------------------------------------------
    rows = {}
    for g, d in R.items():
        b, st = d["base"], d["stress"]
        folds = st["folds_year"]
        rets = returns_of(b["equity_curve"])
        r_list = [rets[k] for k in sorted(rets)]
        rc = {}
        for sc in ("base", "stress"):
            tot = 0.0
            for t in d[sc]["trades"]:
                m = uni[t["code"]]
                kw = dict(slippage_ticks=float(d[sc]["slippage_ticks"]), fee_mult=float(d[sc]["fee_mult"]))
                base_cost = hb.fill_cost(m, float(t["entry_orig"] if t.get("entry_orig") is not None else t["entry"]), int(t["lots"]), **kw) + \
                    hb.fill_cost(m, float(t["exit"]), int(t["lots"]), **kw)
                tot += float(t["cost"]) - base_cost
            rc[sc] = round(tot, 2)
        rows[g] = {
            "equity0": LEVELS[g[1:]],
            "ret_base": b["ret_pct"], "ret_stress": st["ret_pct"], "dd_base": b["max_dd_pct"], "dd_stress": st["max_dd_pct"],
            "net_yuan_base": round(b["equity_end"] - b["equity_start"], 2), "net_yuan_stress": round(st["equity_end"] - st["equity_start"], 2),
            "trades_base": b["closed_trades"], "trades_stress": st["closed_trades"],
            "folds_stress": {y: round(v, 5) for y, v in folds.items()}, "folds_positive": sum(1 for v in folds.values() if v > 0),
            "skips_base": b["skips"], "pool_blocked_base": b.get("pool_blocked_signals") or 0,
            "pool_blocked_total": int(b.get("pool_blocked_signals") or 0),
            "roll_shifted_base": b["roll_shifted"], "roll_cost_yuan_base": rc["base"], "roll_cost_yuan_stress": rc["stress"],
            "roll_unpriced_cont": b["roll_unpriced_cont"], "held_contract_missing": b["held_contract_missing"],
            "open_positions_at_end": len(b.get("final_positions") or {}),
            "cost_yuan_base": b["cost_yuan"], "cost_yuan_stress": st["cost_yuan"],
            "start": b["start"], "end": b["end"],
            "psr": probabilistic_sharpe_ratio(r_list).get("psr"),
            "dsr30": deflated_sharpe_ratio(r_list, n_trials=N_TRIALS, mean_abs_corr=0.0).get("dsr"),
            "exits": b.get("exits"),
        }

    # ---- sec. 7: "A passes" (same 4 conditions for every candidate) -------------------------------------------------
    def passes(kind):
        g1 = rows[f"{kind}1000k"]
        c = {
            "1_stress_ret_1000k_gt0": g1["ret_stress"] > 0,
            "2_dd_base_and_stress_le10_1000k": g1["dd_base"] <= 10.0 and g1["dd_stress"] <= 10.0,
            "3_folds_positive_ge6_1000k": g1["folds_positive"] >= 6,
            "4_stress_ret_gt0_all_three_levels": all(rows[f"{kind}{lv}"]["ret_stress"] > 0 for lv in LEVELS),
        }
        return {"conditions": c, "pass": all(c.values())}

    P = {k: passes(k) for k in "ABC"}
    A, B, C = rows["A1000k"], rows["B1000k"], rows["C1000k"]

    # ---- B better than A --------------------------------------------------------------------------------------------
    bt = R["B1000k"]["stress"]["trades"]
    best = max(bt, key=lambda t: float(t["net"]))
    b_cond = {
        "1_B_passes_A_criteria": P["B"]["pass"],
        "2_stress_ret_diff_ge_3pp": (B["ret_stress"] - A["ret_stress"]) >= 3.0,
        "3_ex_best_trade_still_beats_A": (B["net_yuan_stress"] - float(best["net"])) > A["net_yuan_stress"],
    }
    # 4: A(1000k) closed trades whose entry candidate F2 would block, by ENTRY year, Stress net, A's own stress path
    attr = jl(OOS / "A1000k" / "stress_cand_attr.json")
    a_st = R["A1000k"]["stress"]
    cdates = [x["date"] for x in a_st["equity_curve"]]
    by_year, missing, nblk = {str(y): {"n": 0, "net": 0.0} for y in range(2016, 2026)}, 0, 0
    for t in a_st["trades"]:
        prev = [d for d in cdates if d < t["entry_date"]]
        a = attr.get(f"{prev[-1]}|{t['code']}") if prev else None
        if a is None:
            missing += 1
            continue
        if ef.atr_spike(a["atr14"], a["atr100"]) is True:
            y = t["entry_date"][:4]
            by_year[y]["n"] += 1
            by_year[y]["net"] += float(t["net"])
            nblk += 1
    neg_years = sum(1 for v in by_year.values() if v["n"] > 0 and v["net"] < 0)
    b_cond["4_filtered_trades_negative_in_ge7_of_10_years"] = neg_years >= 7
    B_better = all(b_cond.values())

    # ---- C better than A --------------------------------------------------------------------------------------------
    rng = {k: max(rows[f"{k}{lv}"]["ret_stress"] for lv in LEVELS) - min(rows[f"{k}{lv}"]["ret_stress"] for lv in LEVELS) for k in "ABC"}
    c_cond = {
        "1_C_passes_A_criteria": P["C"]["pass"],
        "2_stress_range_C_lt_A": rng["C"] < rng["A"],
        "3_C_stress_ret_ge_A_minus_1pp": C["ret_stress"] >= A["ret_stress"] - 1.0,
    }
    C_better = all(c_cond.values())

    # ---- Appendix 1 sec. 6 degrade rule + C pool report -------------------------------------------------------------
    ident = {c: 1 - (info["unidentified_symbol_days_carried"].get(c, 0) / info["bars"][c]) for c in info["symbols"]}
    below99 = {c: round(v, 5) for c, v in ident.items() if v < 0.99}
    bucket = {c: uni[c].get("bucket") for c in info["symbols"]}
    a_trades_by_bucket = Counter(bucket[t["code"]] for t in R["A1000k"]["base"]["trades"])
    empty_buckets = sorted(b for b in set(bucket.values()) if a_trades_by_bucket.get(b, 0) == 0)
    pools = {}
    for lv in LEVELS:
        pr = R[f"C{lv}"]["base"]["pool"]
        pools[lv] = {"months": pr["months_n"], "months_nonferrous_empty": pr["months_nonferrous_empty"],
                     "settle_fallback_close": pr["settle_fallback_close"], "no_prior_bar_total": sum(len(m.get("no_prior_bar") or []) for m in pr["months"]),
                     "min_pool_size": min(len(m["pool"]) for m in pr["months"]), "max_pool_size": max(len(m["pool"]) for m in pr["months"])}
    degrade = {"symbols_below_99pct_identified": below99, "empty_buckets_in_A1000k_trades": empty_buckets,
               "rule": "remove failing symbols one by one; > 3 removed or any bucket empty throughout => diagnostic only",
               "n_failing": len(below99), "triggered": len(below99) > 3 or bool(empty_buckets)}

    out = {"prereg": "archive/R8/PREREG_OOS.md + APPENDIX_1.md", "n_trials": N_TRIALS, "guard_pct": info["guard_pct"],
           "pack_sha256": info["pack_sha256"], "max_loaded_date": info["max_loaded_date"], "rows": rows, "criteria_A_pass": P,
           "B_better_than_A": {"conditions": b_cond, "verdict": B_better, "B_best_trade_stress": {k: best[k] for k in ("code", "entry_date", "date", "net")},
                               "filtered_by_year": {y: {"n": v["n"], "net": round(v["net"], 2)} for y, v in by_year.items()},
                               "filtered_n": nblk, "filtered_missing_attr": missing, "years_negative": neg_years},
           "C_better_than_A": {"conditions": c_cond, "verdict": C_better, "stress_range_pp": {k: round(v, 3) for k, v in rng.items()}},
           "degrade_rule": degrade, "c_pool": pools}
    (HERE / "OOS_VERDICT.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---- markdown ---------------------------------------------------------------------------------------------------
    f = lambda x: f"{x:.2f}"  # noqa: E731
    md = ["# R8 长样本判定（OOS_VERDICT）", "",
          "只含 `PREREG_OOS.md` §7 的判定与证据；不产生\"建议改正式口径\"。长窗口 2016-01-04 → 2025-12-31（结束日硬截断，最大加载日期 "
          f"{info['max_loaded_date']}），官方逐合约数据 + 5% 成交量守卫（附录 1），基础模式。DSR n_trials={N_TRIALS}，只报告。", "",
          "## 1. 三个判定", "",
          f"- **A 通过？** {'是' if P['A']['pass'] else '否'}；**B 通过？** {'是' if P['B']['pass'] else '否'}；**C 通过？** {'是' if P['C']['pass'] else '否'}（\"通过\" = §7 的 4 条）",
          f"- **B 优于 A？** {'是' if B_better else '否'}；**C 优于 A？** {'是' if C_better else '否'}", "",
          "## 2. 九组读数（收益 % / 最大回撤 %）", "",
          "| 组 | Base 收益 | Base 回撤 | Stress 收益 | Stress 回撤 | 已平仓(Base) | 正折(Stress) | 换月次数(Base,每次 2 笔成交) | 换月成本 元(Base/Stress) | PSR | DSR(30) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g, r in rows.items():
        md.append(f"| {g} | {f(r['ret_base'])} | {f(r['dd_base'])} | {f(r['ret_stress'])} | {f(r['dd_stress'])} | {r['trades_base']} | {r['folds_positive']}/10 | "
                  f"{r['roll_shifted_base']} | {r['roll_cost_yuan_base']:,.0f} / {r['roll_cost_yuan_stress']:,.0f} | {r['psr']:.3f} | {r['dsr30']:.3f} |")
    md += ["", "## 3. \"通过\"四条逐条（各候选）", "", "| 条件 | A | B | C |", "|---|---|---|---|"]
    for k in P["A"]["conditions"]:
        md.append(f"| {k} | " + " | ".join("✓" if P[x]["conditions"][k] else "✗" for x in "ABC") + " |")
    md += ["", "### 三档 Stress 收益 % 与极差（pp）", "", "| 候选 | 80万 | 100万 | 120万 | 极差 |", "|---|---|---|---|---|"]
    for k in "ABC":
        md.append(f"| {k} | " + " | ".join(f(rows[f'{k}{lv}']['ret_stress']) for lv in LEVELS) + f" | {rng[k]:.2f} |")
    md += ["", "### 走步（Stress，10 个自然年）", "", "| 组(100万) | " + " | ".join(str(y) for y in range(2016, 2026)) + " |", "|---|" + "---|" * 10]
    for k in "ABC":
        fy = rows[f"{k}1000k"]["folds_stress"]
        md.append(f"| {k} | " + " | ".join(f"{fy[str(y)] * 100:.1f}" for y in range(2016, 2026)) + " |")
    md += ["", "## 4. B 优于 A", "", "| 条件 | 满足 |", "|---|---|"] + [f"| {k} | {'✓' if v else '✗'} |" for k, v in b_cond.items()]
    md += ["", f"- B−A Stress 收益差 = {B['ret_stress'] - A['ret_stress']:.2f} pp；B 盈利最大一笔（Stress）= {best['code']} {best['entry_date']}→{best['date']} {float(best['net']):,.0f} 元；"
           f"B 净盈亏 {B['net_yuan_stress']:,.0f} 元，扣该笔后 {B['net_yuan_stress'] - float(best['net']):,.0f} 元，A 净盈亏 {A['net_yuan_stress']:,.0f} 元。",
           f"- 被过滤交易（A 100万、Stress、按入场年；F2 会拦下的已平仓笔数 {nblk}，归因缺失 {missing}）：",
           "", "| 年 | " + " | ".join(by_year) + " |", "|---|" + "---|" * len(by_year),
           "| 笔数 | " + " | ".join(str(v["n"]) for v in by_year.values()) + " |",
           "| 合计 元 | " + " | ".join(f"{v['net']:,.0f}" for v in by_year.values()) + " |", f"- 合计为负的年份 = {neg_years}/10（需 ≥ 7）。"]
    md += ["", "## 5. C 优于 A", "", "| 条件 | 满足 |", "|---|---|"] + [f"| {k} | {'✓' if v else '✗'} |" for k, v in c_cond.items()]
    md += ["", "## 6. 跳过信号（Base；四类 + C 池外）", "", "| 组 | lots0 | gross_cap_to_0 | positions_full | bucket_full | 池外 |", "|---|---|---|---|---|---|"]
    for g, r in rows.items():
        s = r["skips_base"]
        md.append(f"| {g} | {s['lots0']} | {s['gross_cap_to_0']} | {s['positions_full']} | {s['bucket_full']} | {r['pool_blocked_total']} |")
    md += ["", "## 7. C 品种池（附录 1 §2.7）", "", "| 档 | 月数 | 有色为空的月 | settle→close 兜底条数 | 无上月末 bar 的品种月 | 池大小(最小–最大) |", "|---|---|---|---|---|---|"]
    for lv, p in pools.items():
        md.append(f"| {lv} | {p['months']} | {len(p['months_nonferrous_empty'])} | {len(p['settle_fallback_close'])} | {p['no_prior_bar_total']} | {p['min_pool_size']}–{p['max_pool_size']} |")
    md += ["", "## 8. 降级规则（附录 1 §6）", "",
           f"- 主力识别率 < 99% 的品种：{below99 or '无'}（共 {len(below99)} 个；规则：剔除 > 3 个或任一板块全程为空 → 整体降级为仅诊断）。",
           f"- A(100万) 全程无交易的板块：{empty_buckets or '无'}。**降级触发：{'是' if degrade['triggered'] else '否'}**。", "",
           "## 9. 换月与数据（附录 1 §4）", "",
           f"- 官方主力序列换月事件 {info['roll_events']} 次（5% 守卫）；各组实际换月成交笔数与成本见 §2。`roll_unpriced_cont` / `held_contract_missing` 全部为 "
           f"{sorted({rows[g]['roll_unpriced_cont'] for g in rows} | {rows[g]['held_contract_missing'] for g in rows})}。",
           f"- 窗口末仍持仓（不强平）：" + "、".join(f"{g} {rows[g]['open_positions_at_end']}" for g in rows) + "。",
           "- 偏离与披露沿用附录 1：预热在窗口内消耗（2016 折不足一年）、长样本成交取主力合约开盘价（与 216 天日历前月口径不同）、守卫仅官方路径。", ""]
    (HERE / "OOS_VERDICT.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"A_pass": P["A"], "B_pass": P["B"]["pass"], "C_pass": P["C"]["pass"], "B_better": B_better, "C_better": C_better,
                      "degrade": degrade["triggered"], "below99": below99, "empty_buckets": empty_buckets}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
