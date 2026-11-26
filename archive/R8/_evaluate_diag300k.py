# -*- coding: utf-8 -*-
"""R8 PREREG_OOS sec. 8 report for the 300k diagnostic groups.  Report only: no verdict on A/B/C, not in DSR, not compared with
the 1,000k table.  Writes DIAG300K_REPORT.md/.json and DIAG300K_C_POOL.md."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D = HERE / "DIAG300K"
NONFERROUS = ("AG", "AL", "AU", "CU", "NI")


def jl(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main() -> int:
    uni = {u["code"]: u for u in jl(ROOT / "universe.json")["symbols"]}
    rows, cpool = {}, None
    for kind in "ABC":
        g = f"{kind}300k"
        b, st = (jl(D / g / f"result_{s}.json") for s in ("base", "stress"))
        for r in (b, st):
            assert r["start"] >= "2016-01-01" and r["end"] <= "2025-12-31" and r["equity_start"] == 300000.0
        folds = st["folds_year"]
        net = st["equity_end"] - st["equity_start"]
        best = max(st["trades"], key=lambda t: float(t["net"]))
        share = (float(best["net"]) / net) if net > 0 else None
        label = "30 万不适用" if (st["ret_pct"] <= 0 or st["max_dd_pct"] > 15.0) else "30 万可运行，策略结构不同"
        rows[g] = {
            "ret_base": b["ret_pct"], "ret_stress": st["ret_pct"], "dd_base": b["max_dd_pct"], "dd_stress": st["max_dd_pct"],
            "trades_base": b["closed_trades"], "trades_stress": st["closed_trades"],
            "folds_stress": {y: round(v, 5) for y, v in folds.items()}, "folds_positive": sum(1 for v in folds.values() if v > 0),
            "skips_base": b["skips"], "skips_stress": st["skips"], "pool_blocked_base": b.get("pool_blocked_signals") or 0,
            "pool_blocked_stress": st.get("pool_blocked_signals") or 0,
            "stress_net_yuan": round(net, 2),
            "best_trade_stress": {k: best[k] for k in ("code", "entry_date", "date", "net")},
            "best_trade_share": round(share, 4) if share is not None else None,
            "label": label, "open_positions_at_end": len(b.get("final_positions") or {}),
            "roll_shifted_base": b["roll_shifted"],
        }
        if kind == "C":
            cpool = b["pool"]
            rows[g]["pool_stress_months_equal_base"] = None

    months = []
    for m in cpool["months"]:
        buckets = sorted({str(uni[c].get("bucket")) for c in m["pool"]})
        months.append({"month": m["month"], "E": m["E"], "pool": m["pool"], "excluded": m["excluded"], "n_buckets": len(buckets),
                       "buckets": buckets, "nonferrous_in_pool": [c for c in m["pool"] if c in NONFERROUS],
                       "no_prior_bar": m.get("no_prior_bar") or [], "settle_fallback_close": m.get("settle_fallback_close") or []})
    n_bk_all = len({str(u.get("bucket")) for u in uni.values()})
    summ = {"months": len(months), "months_nonferrous_empty": [m["month"] for m in months if not m["nonferrous_in_pool"]],
            "months_nonferrous_empty_stress_path": (jl(D / "C300k" / "result_stress.json")["pool"] or {}).get("months_nonferrous_empty"),
            "settle_fallback_close_total": sum(len(m["settle_fallback_close"]) for m in months),
            "pool_size_min": min(len(m["pool"]) for m in months), "pool_size_max": max(len(m["pool"]) for m in months),
            "n_buckets_min": min(m["n_buckets"] for m in months), "n_buckets_max": max(m["n_buckets"] for m in months), "n_buckets_universe": n_bk_all,
            "months_with_zero_pool": [m["month"] for m in months if not m["pool"]]}
    (HERE / "DIAG300K_REPORT.json").write_text(json.dumps({"rows": rows, "c_pool_summary": summ, "c_pool_months": months}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    f = lambda x: f"{x:.2f}"  # noqa: E731
    md = ["# R8 30 万诊断档报告（PREREG_OOS §8）", "",
          "只报告：**不参与** A/B/C 的任何通过或优劣判定；**不与** 100 万档放在同一张表里比较；**不计入** DSR 试验数；标签只写进运营说明，**不触发任何自动调整**。",
          "长窗口 2016-01-04 → 2025-12-31，官方逐合约数据 + 5% 成交量守卫，基础模式；本金 300,000；一次跑完，未重跑。数据包 sha256 与 100 万档相同。", "",
          "## 1. 读数与标签", "",
          "| 组 | Base 收益 % | Base 回撤 % | Stress 收益 % | Stress 回撤 % | 已平仓(Base/Stress) | 正折(Stress) | 标签 |", "|---|---|---|---|---|---|---|---|"]
    for g, r in rows.items():
        md.append(f"| {g} | {f(r['ret_base'])} | {f(r['dd_base'])} | {f(r['ret_stress'])} | {f(r['dd_stress'])} | {r['trades_base']}/{r['trades_stress']} | {r['folds_positive']}/10 | {r['label']} |")
    md += ["", "标签规则（写死）：Stress 净收益 ≤ 0，或 Stress 最大回撤 > 15% → 「30 万不适用」；否则 → 「30 万可运行，策略结构不同」。", "",
           "### 走步（Stress，自然年收益 %）", "", "| 组 | " + " | ".join(str(y) for y in range(2016, 2026)) + " |", "|---|" + "---|" * 10]
    for g, r in rows.items():
        md.append(f"| {g} | " + " | ".join(f"{r['folds_stress'][str(y)] * 100:.1f}" for y in range(2016, 2026)) + " |")
    md += ["", "## 2. 跳过信号（四类；C 另列池外）", "", "| 组 | 成本 | lots0 | gross_cap_to_0 | positions_full | bucket_full | 池外 |", "|---|---|---|---|---|---|---|"]
    for g, r in rows.items():
        for sc in ("base", "stress"):
            s = r[f"skips_{sc}"]
            pb = r["pool_blocked_base"] if sc == "base" else r["pool_blocked_stress"]
            md.append(f"| {g} | {sc} | {s['lots0']} | {s['gross_cap_to_0']} | {s['positions_full']} | {s['bucket_full']} | {pb} |")
    md += ["", "## 3. 收益最大单笔占比（Stress）", "", "| 组 | 最大单笔 | 金额 元 | Stress 总净盈亏 元 | 占比 |", "|---|---|---|---|---|"]
    for g, r in rows.items():
        t = r["best_trade_stress"]
        share = f"{r['best_trade_share'] * 100:.1f}%" if r["best_trade_share"] is not None else "总盈亏 ≤ 0，占比不适用"
        md.append(f"| {g} | {t['code']} {t['entry_date']}→{t['date']} | {float(t['net']):,.0f} | {r['stress_net_yuan']:,.0f} | {share} |")
    md += ["", "## 4. C300k 品种池（Base 路径；逐月清单见 `DIAG300K_C_POOL.md`）", "",
           f"- 月数 {summ['months']}；池大小 {summ['pool_size_min']}–{summ['pool_size_max']}；覆盖板块数 {summ['n_buckets_min']}–{summ['n_buckets_max']}（全品种池共 {summ['n_buckets_universe']} 个板块）。",
           f"- **有色板块（AG/AU/CU/AL/NI）全部不在池内的月数：{len(summ['months_nonferrous_empty'])}**（Stress 路径同口径：{len(summ['months_nonferrous_empty_stress_path'] or [])}）。",
           f"- 池为空的月数：{len(summ['months_with_zero_pool'])}；settle→close 兜底条数：{summ['settle_fallback_close_total']}。"]
    if summ["months_nonferrous_empty"]:
        ne = summ["months_nonferrous_empty"]
        md.append(f"- 有色为空的月份：{ne[0]} … {ne[-1]}（完整清单见 JSON `c_pool_summary.months_nonferrous_empty`）。")
    md += ["", "## 5. 披露", "", "- 窗口末仍持仓（不强平）：" + "、".join(f"{g} {r['open_positions_at_end']}" for g, r in rows.items()) + "。",
           "- 偏离沿用附录 1（预热在窗口内消耗、成交取主力合约、守卫仅官方路径、当前乘数/手续费套全部年份）。", ""]
    (HERE / "DIAG300K_REPORT.md").write_text("\n".join(md), encoding="utf-8")
    pm = ["# C300k 每月品种池（Base 路径；E = 上月末权益，首月 = 初始本金）", "", "| 月 | E 元 | 池大小 | 板块数 | 有色在池 | 池内品种 | 池外品种 |", "|---|---|---|---|---|---|---|"]
    for m in months:
        pm.append(f"| {m['month']} | {m['E']:,.0f} | {len(m['pool'])} | {m['n_buckets']} | {','.join(m['nonferrous_in_pool']) or '无'} | {' '.join(m['pool'])} | {' '.join(m['excluded'])} |")
    (HERE / "DIAG300K_C_POOL.md").write_text("\n".join(pm) + "\n", encoding="utf-8")
    print(json.dumps({g: {k: r[k] for k in ("ret_base", "ret_stress", "dd_base", "dd_stress", "label", "best_trade_share")} for g, r in rows.items()} | {"pool": summ | {"months_nonferrous_empty": len(summ["months_nonferrous_empty"])}}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
