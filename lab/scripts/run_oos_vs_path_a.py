# -*- coding: utf-8 -*-
"""OOS factor composite equity (fee haircut) vs Path-A curve on overlapping dates.

Also builds a local Path-A-like TSMOM proxy on lab bars for long-window OOS
(so comparison is not limited to the short historical_backtest_latest window).
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS.parents[1]))
from lab_common import (  # noqa: E402
    LAB,
    ROOT,
    attach_fwd_ret,
    load_closes,
    load_json,
    load_panel_rows,
    max_dd,
    mean_std,
    oos_split,
    run_meta,
    save_json,
    window_mask,
)

# One-way cost approx on each rebalance leg (bps of notional).
# Path-A uses 1 tick slip + posted fee; CS daily turn ≈ high → keep conservative.
COST_BPS_ONE_WAY = 3.0


def _equity_stats(rets: list[float], dates: list[str]) -> dict:
    if not rets:
        return {"ok": False}
    eq = [1.0]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    mu, sd = mean_std(rets)
    ann = None if mu is None else mu * 252 * 100.0
    vol = None if sd is None else sd * (252**0.5) * 100.0
    sharpe = None if (mu is None or sd in (None, 0)) else (mu * 252) / (sd * (252**0.5))
    return {
        "ok": True,
        "n_days": len(rets),
        "start": dates[0],
        "end": dates[-1],
        "ret_pct": round((eq[-1] / eq[0] - 1.0) * 100.0, 3),
        "ann_pct": None if ann is None else round(ann, 3),
        "vol_ann_pct": None if vol is None else round(vol, 3),
        "sharpe": None if sharpe is None else round(sharpe, 3),
        "max_dd_pct": round(max_dd(eq), 3),
        "equity_end": round(eq[-1], 6),
        "curve": [{"date": d, "equity": round(e, 6)} for d, e in zip(dates, eq[1:])],
    }


def _zscore(vals: dict[str, float]) -> dict[str, float]:
    if len(vals) < 3:
        return {k: 0.0 for k in vals}
    xs = list(vals.values())
    mu = sum(xs) / len(xs)
    var = sum((x - mu) ** 2 for x in xs) / len(xs)
    sd = math.sqrt(var) if var > 1e-18 else 0.0
    if sd <= 0:
        return {k: 0.0 for k in vals}
    return {k: (v - mu) / sd for k, v in vals.items()}


MemberSpec = tuple[str, float, float]  # factor, sign (+1/-1), weight (>=0)


def _normalize_members(members: list[tuple] | list[MemberSpec]) -> list[MemberSpec]:
    out: list[MemberSpec] = []
    for item in members:
        if len(item) == 2:
            fac, sign = item[0], float(item[1])
            w = 1.0
        else:
            fac, sign, w = item[0], float(item[1]), float(item[2])
        out.append((str(fac), sign, w))
    return out


def composite_cs_rets(
    rows: list[dict],
    *,
    members: list[tuple] | list[MemberSpec],
    top_frac: float = 0.2,
    cost_bps: float = COST_BPS_ONE_WAY,
) -> tuple[list[float], list[str], dict]:
    """Cross-sectional long top / short bottom on weighted sum of factor z-scores.

    members: (factor, sign[, weight]). sign=+1 keep, -1 flip; weight scales z.
    Daily rebalance cost ≈ turnover * 2 * cost_bps.
    """
    specs = _normalize_members(members)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("fwd_ret") is None:
            continue
        by_day[r["date"]].append(r)

    rets: list[float] = []
    dates: list[str] = []
    prev_long: set[str] = set()
    prev_short: set[str] = set()
    turns = 0.0
    for day in sorted(by_day):
        bucket = by_day[day]
        scores: dict[str, float] = defaultdict(float)
        present = 0
        active_n = sum(1 for _, _, w in specs if w != 0)
        min_present = 1 if active_n < 2 else 2
        for fac, sign, weight in specs:
            if weight == 0:
                continue
            raw = {
                str(r["code"]): float(r[fac])
                for r in bucket
                if r.get(fac) is not None
            }
            if len(raw) < 5:
                continue
            present += 1
            for code, z in _zscore(raw).items():
                scores[code] += sign * weight * z
        if present < min_present or len(scores) < 10:
            continue
        ranked = sorted(scores.items(), key=lambda kv: kv[1])
        k = max(1, int(len(ranked) * top_frac))
        short_codes = {c for c, _ in ranked[:k]}
        long_codes = {c for c, _ in ranked[-k:]}
        fwd = {str(r["code"]): float(r["fwd_ret"]) for r in bucket if r.get("fwd_ret") is not None}
        long_r = [fwd[c] for c in long_codes if c in fwd]
        short_r = [fwd[c] for c in short_codes if c in fwd]
        if not long_r or not short_r:
            continue
        gross = sum(long_r) / len(long_r) - sum(short_r) / len(short_r)
        turn = (
            len(long_codes - prev_long) / max(1, len(long_codes))
            + len(short_codes - prev_short) / max(1, len(short_codes))
        ) / 2.0
        cost = turn * 2.0 * (cost_bps / 10000.0)
        turns += turn
        rets.append(gross - cost)
        dates.append(day)
        prev_long, prev_short = long_codes, short_codes
    info = {
        "members": [{"factor": f, "sign": s, "weight": round(w, 6)} for f, s, w in specs],
        "top_frac": top_frac,
        "cost_bps_one_way": cost_bps,
        "avg_turnover": round(turns / max(1, len(rets)), 4),
    }
    return rets, dates, info


CANDIDATE_FACTORS = (
    "mom_20",
    "mom_60",
    "vol_ratio_sl",
    "carry_gap_pct",
    "basis_mom_20",
    "skew_60",
    "mom_vol_20",
    "hedge_pressure",
)


def select_is_members(ic_rep: dict) -> tuple[list[MemberSpec], list[MemberSpec], dict]:
    """IS-only screen + ICIR weights. Returns (weighted, equal_weight, audit)."""
    fac = ((ic_rep.get("in_sample") or {}).get("factors") or {})
    kept: list[tuple[str, float, float]] = []  # name, sign, |icir|
    rejected: list[dict] = []
    for name in CANDIDATE_FACTORS:
        body = fac.get(name) or {}
        mu = body.get("ic_mean")
        icir = body.get("icir_ann")
        n = body.get("n_ic_days")
        ls = body.get("quintile_ls") or {}
        raw_ls = ls.get("ret_pct")
        reason = None
        if mu is None or icir is None:
            reason = "missing_ic"
        elif n is None or int(n) < 120:
            reason = "n_ic_days<120"
        elif abs(float(icir)) < 0.2:
            reason = "|icir|<0.2"
        elif raw_ls is None:
            reason = "missing_quintile_ls"
        else:
            # long_high LS; after freezing sign(IC), edge ≈ sign * raw_ls
            signed_ls = float(raw_ls) if float(mu) > 0 else -float(raw_ls)
            if signed_ls <= 0:
                reason = "signed_is_ls_ret<=0"
            else:
                kept.append((name, 1.0 if float(mu) > 0 else -1.0, abs(float(icir))))
                continue
        rejected.append(
            {
                "factor": name,
                "reason": reason,
                "ic_mean": mu,
                "icir_ann": icir,
                "n_ic_days": n,
                "raw_ls_ret_pct": raw_ls,
            }
        )
    if not kept:
        return [], [], {"selected": [], "rejected": rejected, "note": "no_is_survivors"}
    icir_sum = sum(a for _, _, a in kept) or 1.0
    weighted: list[MemberSpec] = [
        (name, sign, abs_icir / icir_sum) for name, sign, abs_icir in kept
    ]
    equal: list[MemberSpec] = [(name, sign, 1.0 / len(kept)) for name, sign, _ in kept]
    audit = {
        "rule": "n_ic_days>=120 & |icir_ann|>=0.2 & signed_IS_quintile_ls_ret>0; weight∝|ICIR|",
        "selected": [
            {
                "factor": n,
                "sign": s,
                "weight": round(w, 6),
                "abs_icir": round(a, 6),
            }
            for (n, s, w), (_, _, a) in zip(weighted, kept)
        ],
        "rejected": rejected,
    }
    return weighted, equal, audit


def path_a_proxy_tsmom(rows: list[dict], *, min_r20: float = 3.0, min_r60: float = 5.0) -> tuple[list[float], list[str]]:
    """Equal-weight among codes with aligned mom_20/60 above thresholds; else flat."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
    rets: list[float] = []
    dates: list[str] = []
    for day in sorted(by_day):
        legs = []
        for r in by_day[day]:
            m20, m60, fwd = r.get("mom_20"), r.get("mom_60"), r.get("fwd_ret")
            if m20 is None or m60 is None or fwd is None:
                continue
            if abs(m20) < min_r20 or abs(m60) < min_r60:
                continue
            if (m20 > 0 and m60 > 0) or (m20 < 0 and m60 < 0):
                legs.append(float(fwd) if m20 > 0 else -float(fwd))
        if not legs:
            continue
        rets.append(sum(legs) / len(legs))
        dates.append(day)
    return rets, dates


def load_path_a_official_curve() -> dict[str, float]:
    path = ROOT / "historical_backtest_latest.json"
    if not path.is_file():
        return {}
    try:
        bt = load_json(path)
    except Exception:
        return {}
    curve = bt.get("equity_curve") or []
    out: dict[str, float] = {}
    for pt in curve:
        d = str(pt.get("date") or "")
        e = pt.get("equity")
        if d and e is not None:
            out[d] = float(e)
    return out


def overlap_stats(lab_curve: list[dict], path_a: dict[str, float]) -> dict:
    if not lab_curve or not path_a:
        return {"ok": False, "reason": "missing curve"}
    pairs = [(p["date"], p["equity"], path_a[p["date"]]) for p in lab_curve if p["date"] in path_a]
    if len(pairs) < 5:
        return {"ok": False, "reason": "overlap too short", "n": len(pairs)}
    # rebase both to 1 at first overlap
    e0_l, e0_p = pairs[0][1], pairs[0][2]
    lab_rets = []
    pa_rets = []
    for i in range(1, len(pairs)):
        lab_rets.append(pairs[i][1] / pairs[i - 1][1] - 1.0)
        pa_rets.append(pairs[i][2] / pairs[i - 1][2] - 1.0)
    lab_eq = [1.0]
    pa_eq = [1.0]
    for a, b in zip(lab_rets, pa_rets):
        lab_eq.append(lab_eq[-1] * (1.0 + a))
        pa_eq.append(pa_eq[-1] * (1.0 + b))
    return {
        "ok": True,
        "n_days": len(pairs),
        "start": pairs[0][0],
        "end": pairs[-1][0],
        "lab_ret_pct": round((lab_eq[-1] - 1.0) * 100.0, 3),
        "path_a_official_ret_pct": round((pa_eq[-1] - 1.0) * 100.0, 3),
        "lab_max_dd_pct": round(max_dd(lab_eq), 3),
        "path_a_official_max_dd_pct": round(max_dd(pa_eq), 3),
        "note": "同重叠日 rebase；官方 Path-A 曲线窗可能短于 lab OOS。",
    }


def main() -> int:
    split = oos_split()
    oos_start = split["out_of_sample"]["start"]
    oos_end = split["out_of_sample"].get("end")
    rows = attach_fwd_ret(load_panel_rows(), load_closes())
    oos_rows = [r for r in rows if window_mask(r["date"], oos_start, oos_end)]

    # A) Prior belief composite (momentum long / vol-expand short / contango caution)
    members_prior: list[MemberSpec] = [
        ("mom_20", 1.0, 1.0),
        ("mom_60", 1.0, 1.0),
        ("vol_ratio_sl", -1.0, 1.0),
        ("carry_gap_pct", -0.5, 1.0),
    ]
    # B) IS screen + ICIR weights (no OOS peeking)
    ic_path = LAB / "research" / "ic" / "ic_groups_latest.json"
    ic_rep = load_json(ic_path) if ic_path.is_file() else {}
    members_w, members_eq, is_audit = select_is_members(ic_rep)
    if not members_w:
        members_w = list(members_prior)
        members_eq = list(members_prior)
        is_audit = {
            **is_audit,
            "note": "fallback_to_prior_belief",
            "selected": [
                {"factor": f, "sign": s, "weight": w} for f, s, w in members_prior
            ],
        }

    def _pack(
        members: list[MemberSpec] | list[tuple], tag: str
    ) -> tuple[dict, list[dict], list[float], list[str]]:
        rets, dates, info = composite_cs_rets(oos_rows, members=members)
        stats = _equity_stats(rets, dates)
        curve = stats.pop("curve", []) if stats.get("ok") else []
        return {**stats, "build": info, "tag": tag}, curve, rets, dates

    lab_prior, curve_prior, rets_prior, dates_prior = _pack(members_prior, "prior_belief")
    lab_is, curve_is, rets_is, dates_is = _pack(members_w, "is_screen_icir_weight")
    lab_is_eq, _, _, _ = _pack(members_eq, "is_screen_equal_weight")

    # Leave-one-out contribution on OOS (evaluation only; weights frozen from IS)
    loo_rows: list[dict] = []
    full_ret = float(lab_is.get("ret_pct") or 0.0)
    full_dd = float(lab_is.get("max_dd_pct") or 0.0)
    full_sh = lab_is.get("sharpe")
    for drop_name, _, _ in members_w:
        sub = [m for m in members_w if m[0] != drop_name]
        if len(sub) < 2:
            loo_rows.append(
                {
                    "factor": drop_name,
                    "ok": False,
                    "reason": "need>=2_members_after_drop",
                }
            )
            continue
        # re-normalize remaining weights
        wsum = sum(w for _, _, w in sub) or 1.0
        sub_n = [(f, s, w / wsum) for f, s, w in sub]
        dropped_stats, _, _, _ = _pack(sub_n, f"loo_drop_{drop_name}")
        if not dropped_stats.get("ok"):
            loo_rows.append({"factor": drop_name, "ok": False, "reason": "oos_empty"})
            continue
        d_ret = float(dropped_stats.get("ret_pct") or 0.0)
        d_dd = float(dropped_stats.get("max_dd_pct") or 0.0)
        d_sh = dropped_stats.get("sharpe")
        loo_rows.append(
            {
                "factor": drop_name,
                "ok": True,
                "oos_ret_pct_without": d_ret,
                "oos_max_dd_pct_without": d_dd,
                "oos_sharpe_without": d_sh,
                "delta_ret_pct": round(full_ret - d_ret, 3),
                "delta_max_dd_pct": round(full_dd - d_dd, 3),
                "delta_sharpe": (
                    None
                    if full_sh is None or d_sh is None
                    else round(float(full_sh) - float(d_sh), 3)
                ),
                "contributes": (full_ret - d_ret) > 0,
            }
        )

    proxy_rets, proxy_dates = path_a_proxy_tsmom(oos_rows)
    proxy_stats = _equity_stats(proxy_rets, proxy_dates)
    proxy_curve = proxy_stats.pop("curve", []) if proxy_stats.get("ok") else []

    official = load_path_a_official_curve()
    overlap_prior = overlap_stats(curve_prior, official)
    overlap_is = overlap_stats(curve_is, official)
    overlap_proxy = overlap_stats(proxy_curve, official)

    def _align(lab_rets: list[float], lab_dates: list[str]) -> dict | None:
        lab_map = {d: r for d, r in zip(lab_dates, lab_rets)}
        proxy_map = {d: r for d, r in zip(proxy_dates, proxy_rets)}
        common = sorted(set(lab_map) & set(proxy_map))
        if len(common) < 5:
            return None
        lr = [lab_map[d] for d in common]
        pr = [proxy_map[d] for d in common]
        a = {
            "n_days": len(common),
            "start": common[0],
            "end": common[-1],
            "lab": _equity_stats(lr, common),
            "path_a_proxy_tsmom": _equity_stats(pr, common),
        }
        if a["lab"].get("ok"):
            a["lab"].pop("curve", None)
        if a["path_a_proxy_tsmom"].get("ok"):
            a["path_a_proxy_tsmom"].pop("curve", None)
        return a

    aligned_prior = _align(rets_prior, dates_prior)
    aligned_is = _align(rets_is, dates_is)

    def _gate(aligned: dict | None, overlap: dict) -> dict:
        """Desk-discussion gate (still does not auto-change entry_filter).

        Pass if either:
        A) risk-first: DD ≤ proxy AND ret ≥ proxy−1pp, overlap ok
        B) reward/risk: ret ≥ proxy−1pp, ret/DD ≥ 2×, and lab ret/DD beats
           proxy ret/DD, with DD not >1.25× proxy (or +5pp), overlap ok
        """
        if not aligned or not aligned.get("lab", {}).get("ok"):
            return {"pass": False, "reason": "no aligned stats"}
        lab = aligned["lab"]
        prox = aligned["path_a_proxy_tsmom"]
        lab_ret = float(lab.get("ret_pct") or 0.0)
        lab_dd = float(lab.get("max_dd_pct") or 0.0)
        prox_ret = float(prox.get("ret_pct") or 0.0)
        prox_dd = float(prox.get("max_dd_pct") or 0.0)
        better_dd = lab_dd <= prox_dd
        not_worse_ret = lab_ret >= prox_ret - 1.0
        lab_rr = lab_ret / max(lab_dd, 1e-6)
        prox_rr = prox_ret / max(prox_dd, 1e-6)
        # 「收益远大于回撤」：绝对倍数 + 相对代理更优 + 回撤不失控
        dd_tolerable = lab_dd <= max(prox_dd * 1.25, prox_dd + 5.0)
        strong_rr = (
            not_worse_ret
            and lab_rr >= 2.0
            and lab_rr > prox_rr
            and dd_tolerable
        )
        overlap_ok = True
        if overlap.get("ok"):
            # lab overlap ret not worse than official by >5pp absolute
            overlap_ok = float(overlap.get("lab_ret_pct") or 0) >= float(
                overlap.get("path_a_official_ret_pct") or 0
            ) - 5.0
        path_a = better_dd and not_worse_ret and overlap_ok
        path_b = strong_rr and overlap_ok
        passed = path_a or path_b
        if passed:
            reason = (
                "pass(risk-first)"
                if path_a
                else f"pass(reward/risk ret/DD={lab_rr:.2f} vs proxy {prox_rr:.2f})"
            )
        else:
            reason = "OOS 未过回撤或收益/回撤门槛；保持 Path-A entry_filter"
        return {
            "pass": bool(passed),
            "better_dd": better_dd,
            "not_worse_ret": not_worse_ret,
            "strong_ret_over_dd": strong_rr,
            "lab_ret_over_dd": round(lab_rr, 3),
            "proxy_ret_over_dd": round(prox_rr, 3),
            "overlap_ok": overlap_ok,
            "path": "risk_first" if path_a else ("reward_risk" if path_b else None),
            "reason": reason,
        }

    contribution = {
        "is_screen": is_audit,
        "full_oos": {
            "tag": lab_is.get("tag"),
            "ret_pct": lab_is.get("ret_pct"),
            "max_dd_pct": lab_is.get("max_dd_pct"),
            "sharpe": lab_is.get("sharpe"),
        },
        "equal_weight_oos": {
            "tag": lab_is_eq.get("tag"),
            "ret_pct": lab_is_eq.get("ret_pct"),
            "max_dd_pct": lab_is_eq.get("max_dd_pct"),
            "sharpe": lab_is_eq.get("sharpe"),
        },
        "leave_one_out": loo_rows,
        "note": "delta_ret_pct>0 表示去掉该因子后 OOS 收益变差 → 该因子有正贡献（仅 OOS 验收）。",
    }

    report = {
        "ok": True,
        "meta": run_meta({"script": "run_oos_vs_path_a.py", "cost_bps_one_way": COST_BPS_ONE_WAY}),
        "oos_window": {
            "start": oos_start,
            "end": oos_end or (dates_is[-1] if dates_is else None),
        },
        "lab_composite_prior": lab_prior,
        "lab_composite_is_sign": lab_is,
        "lab_composite_is_equal": lab_is_eq,
        "contribution": contribution,
        "path_a_proxy_tsmom_oos": proxy_stats,
        "overlap_vs_official_path_a": {
            "lab_prior": overlap_prior,
            "lab_is_sign": overlap_is,
            "path_a_proxy": overlap_proxy,
            "official_curve_points": len(official),
        },
        "aligned_lab_vs_proxy": {
            "prior": aligned_prior,
            "is_sign": aligned_is,
        },
        "gates": {
            "prior": _gate(aligned_prior, overlap_prior),
            "is_sign": _gate(aligned_is, overlap_is),
        },
        "equity_curves": {
            "lab_prior": curve_prior,
            "lab_is_sign": curve_is,
            "path_a_proxy_tsmom": proxy_curve,
        },
        "pass_gate_note": (
            "建议门槛（研究用，过线仅供策略台讨论，不自动改 entry_filter）："
            "(A) 对齐窗回撤≤代理且收益≥代理−1pp；或 "
            "(B) 收益≥代理−1pp 且 ret/DD≥2 并优于代理、回撤不超过代理×1.25（或+5pp）；"
            "且官方短窗重叠收益不差于 −5pp。"
            "合成成员仅 IS 入选（n≥120、|ICIR|≥0.2、符号后五分组 IS 收益>0），权重∝|ICIR|。"
        ),
        "disclaimer": (
            "纸面费后近似（换手×3bps）；非实盘。仓单因子仍缺失。"
            "入选/符号/权重仅用样本内；OOS 只做验收与 leave-one-out。"
        ),
    }
    out = LAB / "research" / "oos" / "oos_vs_path_a_latest.json"
    save_json(out, report)
    # also stamp a run folder
    stamp = report["meta"]["created_at"][:19].replace(":", "").replace("-", "")
    run_dir = LAB / "research" / "runs" / f"oos_{stamp}"
    save_json(run_dir / "report.json", report)
    save_json(run_dir / "meta.json", report["meta"])

    keys = ("ok", "n_days", "start", "end", "ret_pct", "ann_pct", "sharpe", "max_dd_pct")
    print("=== OOS lab prior ===")
    print(json.dumps({k: lab_prior.get(k) for k in keys}, ensure_ascii=False))
    print("=== OOS lab IS-screen ICIR-weight ===")
    print(json.dumps({k: lab_is.get(k) for k in keys}, ensure_ascii=False))
    print("=== OOS lab IS-screen equal-weight ===")
    print(json.dumps({k: lab_is_eq.get(k) for k in keys}, ensure_ascii=False))
    print("=== OOS Path-A proxy TSMOM ===")
    print(json.dumps({k: proxy_stats.get(k) for k in keys}, ensure_ascii=False))
    print("=== IS screen selected ===")
    print(json.dumps(is_audit.get("selected"), ensure_ascii=False, indent=2))
    print("=== leave-one-out ===")
    print(json.dumps(loo_rows, ensure_ascii=False, indent=2))
    print("=== gates ===")
    print(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    print("=== aligned is_sign ===")
    print(json.dumps(aligned_is, ensure_ascii=False, indent=2))
    print(f"[oos] wrote {out}")
    print(f"[oos] run {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
