# -*- coding: utf-8 -*-
"""Strategy × indicator grids: leave-one-out ablation or full combinatorial sweep.

Paper research only. Writes data/ablation/strategy_indicator_ablation_latest.json.

Usage:
  python scripts/strategy_indicator_ablation.py              # default: full_grid (1A+2D)
  python scripts/strategy_indicator_ablation.py --mode ablation
  python scripts/strategy_indicator_ablation.py --mode full_grid
  python scripts/strategy_indicator_ablation.py --proxy-only
  python scripts/strategy_indicator_ablation.py --path-a-only
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "data" / "ablation" / "strategy_indicator_ablation_latest.json"
TZ = ZoneInfo("Asia/Shanghai")

DISCLAIMER = (
    "纸面研究：本地代理非东证原版因子库；W(权证)本地恒为0不可辨识；"
    "不改正式 entry_filter / universe.json；不构成交易建议。"
)

# Factor names per proxy mode (W excluded — always 0).
PROXY_FACTORS: dict[str, tuple[str, ...]] = {
    "cwft": ("C", "F", "T"),
    "long_short_cwft": ("C", "F", "LONG_MOM", "SHORT_MOM"),
    "frontnext_st": ("C", "ST"),
}

FACTOR_LABEL = {
    "C": "升贴水C",
    "F": "期现F",
    "T": "动量T",
    "ST": "短趋势ST",
    "LONG_MOM": "长端动量",
    "SHORT_MOM": "短端动量",
}

# Leave-one-out style grids (mode=ablation)
PROXY_GRIDS_ABLATION: dict[str, list[tuple[str, str, frozenset[str]]]] = {
    "cwft": [
        ("full", "完整", frozenset()),
        ("no_C", "关C升贴水", frozenset({"C"})),
        ("no_F", "关F期现", frozenset({"F"})),
        ("no_T", "关T动量", frozenset({"T"})),
        ("only_T", "仅T(关C+F)", frozenset({"C", "F"})),
    ],
    "long_short_cwft": [
        ("full", "完整", frozenset()),
        ("no_C", "关C升贴水", frozenset({"C"})),
        ("no_F", "关F期现", frozenset({"F"})),
        ("no_long_mom", "关长端动量", frozenset({"LONG_MOM"})),
        ("no_short_mom", "关短端动量", frozenset({"SHORT_MOM"})),
    ],
    "frontnext_st": [
        ("full", "完整", frozenset()),
        ("no_C", "关C升贴水", frozenset({"C"})),
        ("no_ST", "关短趋势r5", frozenset({"ST"})),
    ],
}

PROXY_META = (
    ("proxy_cwft", "本地代理·CWFT", "cwft"),
    ("proxy_long_short_cwft", "本地代理·Long/Short CWFT", "long_short_cwft"),
    ("proxy_frontnext_st", "本地代理·C_frontnext&ShortTrend", "frontnext_st"),
)


def _calmar(ret, dd) -> float | None:
    try:
        r, d = float(ret), float(dd)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    return round(r / d, 3)


def _kept_label(factors: tuple[str, ...], ablate: frozenset[str]) -> str:
    kept = [FACTOR_LABEL.get(f, f) for f in factors if f not in ablate]
    if not ablate:
        return "完整(全开)"
    if not kept:
        return "全关"
    return "仅" + "+".join(kept)


def proxy_grid_for_mode(mode: str, grid_mode: str) -> list[tuple[str, str, frozenset[str]]]:
    if grid_mode == "ablation":
        return list(PROXY_GRIDS_ABLATION[mode])
    factors = PROXY_FACTORS[mode]
    out: list[tuple[str, str, frozenset[str]]] = []
    for r in range(len(factors) + 1):
        for combo in itertools.combinations(factors, r):
            ablate = frozenset(combo)
            if not ablate:
                vid, vlabel = "full", "完整(全开)"
            else:
                vid = "no_" + "_".join(sorted(ablate)).lower()
                vlabel = _kept_label(factors, ablate)
            out.append((vid, vlabel, ablate))
    # stable: full first, then by #ablated, then id
    out.sort(key=lambda t: (0 if t[0] == "full" else 1, len(t[2]), t[0]))
    return out


def path_a_grid_for_mode(grid_mode: str, *, base_r20: float, base_r60: float, base_bypass: dict) -> list[tuple[str, str, str, dict]]:
    """Return (variant_id, label, entry_filter, cfg_overrides)."""
    from path_a_filters import carry_bypass_cfg

    if grid_mode == "ablation":
        return [
            ("full", "完整 seats", "seats", {}),
            ("no_seats", "关席位→base", "base", {}),
            ("no_r20", "关 min_r20", "seats", {"min_r20": 0.0}),
            ("no_r60", "关 min_r60", "seats", {"min_r60": 0.0}),
            ("no_momentum", "关动量门槛", "seats", {"min_r20": 0.0, "min_r60": 0.0}),
            (
                "no_carry_bypass",
                "关 carry_bypass",
                "seats",
                {"carry_bypass": carry_bypass_cfg({"enabled": False})},
            ),
            ("carry_filter", "过滤改 carry", "carry", {}),
        ]

    # Full product: filter × momentum × carry_bypass
    filters = (
        ("seats", "席位"),
        ("base", "无席位"),
        ("carry", "升贴水过滤"),
    )
    moms = (
        ((base_r20, base_r60), "动量开"),
        ((0.0, base_r60), "关r20"),
        ((base_r20, 0.0), "关r60"),
        ((0.0, 0.0), "动量关"),
    )
    bypasses = (
        (dict(base_bypass), "bypass开" if base_bypass.get("enabled") else "bypass关(配置本就关)"),
        (carry_bypass_cfg({"enabled": False}), "bypass关"),
    )
    # Deduplicate bypass if already disabled in config
    if not base_bypass.get("enabled"):
        bypasses = ((dict(base_bypass), "bypass关"),)

    out: list[tuple[str, str, str, dict]] = []
    for (filt, flab), ((r20, r60), mlab), (bypass, blab) in itertools.product(
        filters, moms, bypasses
    ):
        vid = f"{filt}_r{r20:g}_{r60:g}_bp{1 if bypass.get('enabled') else 0}"
        vlabel = f"{flab}+{mlab}+{blab}"
        overrides: dict = {
            "min_r20": float(r20),
            "min_r60": float(r60),
            "carry_bypass": bypass,
        }
        # Mark canonical full
        if (
            filt == "seats"
            and r20 == base_r20
            and r60 == base_r60
            and bool(bypass.get("enabled")) == bool(base_bypass.get("enabled"))
        ):
            vid, vlabel = "full", f"完整 seats+动量开+{blab}"
        out.append((vid, vlabel, filt, overrides))
    # full first
    out.sort(key=lambda t: (0 if t[0] == "full" else 1, t[0]))
    return out


def _kpi_row(
    *,
    strategy_id: str,
    strategy_name: str,
    variant: str,
    variant_label: str,
    ablated: list[str],
    ret_pct,
    max_dd_pct,
    calmar=None,
    n_trades=None,
    start=None,
    end=None,
    ok: bool = True,
    error: str = "",
    baseline_ret=None,
    baseline_dd=None,
) -> dict:
    cal = calmar if calmar is not None else _calmar(ret_pct, max_dd_pct)
    d_ret = d_dd = None
    if baseline_ret is not None and ret_pct is not None:
        try:
            d_ret = round(float(ret_pct) - float(baseline_ret), 3)
        except (TypeError, ValueError):
            d_ret = None
    if baseline_dd is not None and max_dd_pct is not None:
        try:
            d_dd = round(float(max_dd_pct) - float(baseline_dd), 3)
        except (TypeError, ValueError):
            d_dd = None
    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "variant": variant,
        "variant_label": variant_label,
        "ablated": list(ablated),
        "ret_pct": ret_pct,
        "max_dd_pct": max_dd_pct,
        "calmar": cal,
        "delta_ret_vs_full": d_ret,
        "delta_dd_vs_full": d_dd,
        "n_trades": n_trades,
        "start": start,
        "end": end,
        "ok": ok,
        "error": error,
    }


def run_proxy_grid(series: dict, curves: dict, *, grid_mode: str) -> list[dict]:
    from proxy_cta import _simulate_cs

    rows: list[dict] = []
    for sid, label, mode in PROXY_META:
        grid = proxy_grid_for_mode(mode, grid_mode)
        full_ret = full_dd = None
        for vid, vlabel, ablate in grid:
            print(f"[ablation] proxy {sid} / {vid}…")
            t0 = time.time()
            out = _simulate_cs(series, curves, name=sid, mode=mode, ablate=ablate)
            elapsed = round(time.time() - t0, 2)
            if not out.get("ok"):
                rows.append(
                    _kpi_row(
                        strategy_id=sid,
                        strategy_name=label,
                        variant=vid,
                        variant_label=vlabel,
                        ablated=sorted(ablate),
                        ret_pct=None,
                        max_dd_pct=None,
                        ok=False,
                        error=str(out.get("error") or "fail"),
                    )
                )
                print(f"  FAIL {out.get('error')} ({elapsed}s)")
                continue
            if vid == "full":
                full_ret, full_dd = out.get("ret_pct"), out.get("max_dd_pct")
            row = _kpi_row(
                strategy_id=sid,
                strategy_name=label,
                variant=vid,
                variant_label=vlabel,
                ablated=sorted(ablate),
                ret_pct=out.get("ret_pct"),
                max_dd_pct=out.get("max_dd_pct"),
                calmar=out.get("calmar"),
                n_trades=len(out.get("trade_log") or []),
                start=out.get("start"),
                end=out.get("end"),
                baseline_ret=full_ret if vid != "full" else None,
                baseline_dd=full_dd if vid != "full" else None,
            )
            row["elapsed_sec"] = elapsed
            row["kept"] = [
                f for f in PROXY_FACTORS[mode] if f not in ablate
            ]
            rows.append(row)
            print(
                f"  ret={row['ret_pct']} dd={row['max_dd_pct']} "
                f"Δret={row['delta_ret_vs_full']} ({elapsed}s)"
            )
    return rows


def run_path_a_grid(*, grid_mode: str) -> list[dict]:
    from historical_backtest import _fetch_pack, _load_cfg, _simulate_cfg

    p0 = _load_cfg()
    p0["equity0"] = float(p0["cfg"].get("equity") or 200_000)
    p0["min_lots"] = 0
    p0["option_hedge"] = False
    p0["observe_mode"] = False
    base_r20 = float(p0["min_r20"])
    base_r60 = float(p0["min_r60"])
    base_bypass = dict(p0.get("carry_bypass") or {})

    print("[ablation] Path-A fetch pack once…")
    pack = _fetch_pack(p0["cfg"]["symbols"])
    variants = path_a_grid_for_mode(
        grid_mode, base_r20=base_r20, base_r60=base_r60, base_bypass=base_bypass
    )
    print(f"[ablation] Path-A grid size={len(variants)} mode={grid_mode}")

    rows: list[dict] = []
    full_ret = full_dd = None
    for vid, vlabel, mode, overrides in variants:
        print(f"[ablation] path_a / {vid}…")
        cfg = dict(p0)
        cfg["min_r20"] = base_r20
        cfg["min_r60"] = base_r60
        cfg["carry_bypass"] = dict(base_bypass)
        cfg.update(overrides)
        t0 = time.time()
        try:
            out = _simulate_cfg(cfg, mode, pack=pack, option_hedge=False)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                _kpi_row(
                    strategy_id="path_a",
                    strategy_name="路径A seats",
                    variant=vid,
                    variant_label=vlabel,
                    ablated=[vid] if vid != "full" else [],
                    ret_pct=None,
                    max_dd_pct=None,
                    ok=False,
                    error=f"{type(exc).__name__}:{exc}",
                )
            )
            print(f"  FAIL {exc}")
            continue
        elapsed = round(time.time() - t0, 2)
        if vid == "full":
            full_ret, full_dd = out.get("ret_pct"), out.get("max_dd_pct")
        ablated = [] if vid == "full" else [vid]
        row = _kpi_row(
            strategy_id="path_a",
            strategy_name="路径A seats",
            variant=vid,
            variant_label=vlabel,
            ablated=ablated,
            ret_pct=out.get("ret_pct"),
            max_dd_pct=out.get("max_dd_pct"),
            n_trades=out.get("closed_trades"),
            start=out.get("start") or out.get("asof"),
            end=out.get("end") or out.get("asof"),
            ok=bool(out.get("ok", True)),
            error=""
            if out.get("ok", True)
            else str(out.get("error") or out.get("conclusion") or ""),
            baseline_ret=full_ret if vid != "full" else None,
            baseline_dd=full_dd if vid != "full" else None,
        )
        row["entry_filter"] = mode
        row["min_r20"] = cfg["min_r20"]
        row["min_r60"] = cfg["min_r60"]
        row["carry_bypass_enabled"] = bool((cfg.get("carry_bypass") or {}).get("enabled"))
        row["elapsed_sec"] = elapsed
        rows.append(row)
        print(
            f"  ret={row['ret_pct']} dd={row['max_dd_pct']} "
            f"Δret={row['delta_ret_vs_full']} ({elapsed}s)"
        )
    return rows


def _summarize(rows: list[dict], *, grid_mode: str) -> dict:
    fulls = [r for r in rows if r.get("variant") == "full" and r.get("ok")]
    fulls_sorted = sorted(
        fulls,
        key=lambda r: (
            float(r["ret_pct"]) if r.get("ret_pct") is not None else -1e18,
            float(r["calmar"]) if r.get("calmar") is not None else -1e18,
        ),
        reverse=True,
    )
    ablations = [
        r
        for r in rows
        if r.get("variant") != "full" and r.get("ok") and r.get("delta_ret_vs_full") is not None
    ]
    by_hurt = sorted(ablations, key=lambda r: float(r["delta_ret_vs_full"]))
    by_help = sorted(ablations, key=lambda r: float(r["delta_ret_vs_full"]), reverse=True)

    ok_rows = [r for r in rows if r.get("ok") and r.get("ret_pct") is not None]
    top_ret = sorted(ok_rows, key=lambda r: float(r["ret_pct"]), reverse=True)[:10]
    top_calmar = sorted(
        [r for r in ok_rows if r.get("calmar") is not None],
        key=lambda r: float(r["calmar"]),
        reverse=True,
    )[:10]

    return {
        "grid_mode": grid_mode,
        "best_full_strategies": [
            {
                "strategy_id": r["strategy_id"],
                "strategy_name": r["strategy_name"],
                "ret_pct": r["ret_pct"],
                "max_dd_pct": r["max_dd_pct"],
                "calmar": r["calmar"],
            }
            for r in fulls_sorted
        ],
        "top_pairs_by_ret": [
            {
                "strategy_id": r["strategy_id"],
                "variant": r["variant"],
                "variant_label": r["variant_label"],
                "kept": r.get("kept"),
                "ret_pct": r["ret_pct"],
                "max_dd_pct": r["max_dd_pct"],
                "calmar": r["calmar"],
            }
            for r in top_ret
        ],
        "top_pairs_by_calmar": [
            {
                "strategy_id": r["strategy_id"],
                "variant": r["variant"],
                "variant_label": r["variant_label"],
                "kept": r.get("kept"),
                "ret_pct": r["ret_pct"],
                "max_dd_pct": r["max_dd_pct"],
                "calmar": r["calmar"],
            }
            for r in top_calmar
        ],
        "most_valuable_indicators": [
            {
                "strategy_id": r["strategy_id"],
                "variant": r["variant"],
                "variant_label": r["variant_label"],
                "delta_ret_vs_full": r["delta_ret_vs_full"],
                "delta_dd_vs_full": r["delta_dd_vs_full"],
                "note": "相对完整配置Δ收益最负 → 关掉的部分贡献大",
            }
            for r in by_hurt[:10]
        ],
        "redundant_or_harmful": [
            {
                "strategy_id": r["strategy_id"],
                "variant": r["variant"],
                "variant_label": r["variant_label"],
                "delta_ret_vs_full": r["delta_ret_vs_full"],
                "delta_dd_vs_full": r["delta_dd_vs_full"],
                "note": "相对完整配置Δ收益≥0 → 该组合不更差",
            }
            for r in by_help
            if float(r["delta_ret_vs_full"]) >= -0.05
        ][:10],
        "warrant_note": "W(权证)本地恒为0，本轮不可辨识，未纳入网格。",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Strategy × indicator ablation / full grid")
    ap.add_argument(
        "--mode",
        choices=("ablation", "full_grid"),
        default="full_grid",
        help="ablation=leave-one-out; full_grid=all indicator combinations (1A+2D)",
    )
    ap.add_argument("--proxy-only", action="store_true")
    ap.add_argument("--path-a-only", action="store_true")
    args = ap.parse_args()
    grid_mode = args.mode

    t_all = time.time()
    rows: list[dict] = []

    if not args.path_a_only:
        from historical_backtest import _fetch_pack, _load_cfg
        from public_curve import load_curves

        p = _load_cfg()
        print("[ablation] fetch proxy bars…")
        series, errors, _ = _fetch_pack(p["cfg"]["symbols"])
        if errors:
            print("[ablation] fetch errors", list(errors)[:5])
        print("[ablation] carry curves…")
        curves = load_curves(list(series.keys()))
        rows.extend(run_proxy_grid(series, curves, grid_mode=grid_mode))

    if not args.proxy_only:
        rows.extend(run_path_a_grid(grid_mode=grid_mode))

    summary = _summarize(rows, grid_mode=grid_mode)
    payload = {
        "ok": True,
        "asof": datetime.now(tz=TZ).strftime("%Y-%m-%d %H:%M"),
        "grid_mode": grid_mode,
        "disclaimer": DISCLAIMER,
        "n_rows": len(rows),
        "elapsed_sec": round(time.time() - t_all, 1),
        "rows": rows,
        "summary": summary,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n[ablation] wrote {OUT_PATH.relative_to(ROOT)} ({len(rows)} rows, mode={grid_mode})")
    print("[ablation] best full strategies:")
    for r in summary["best_full_strategies"]:
        print(f"  {r['strategy_name']}: ret={r['ret_pct']} dd={r['max_dd_pct']} calmar={r['calmar']}")
    print("[ablation] top pairs by ret:")
    for r in summary["top_pairs_by_ret"][:5]:
        print(f"  {r['strategy_id']} | {r['variant_label']}: ret={r['ret_pct']} calmar={r['calmar']}")
    print("[ablation] top pairs by calmar:")
    for r in summary["top_pairs_by_calmar"][:5]:
        print(f"  {r['strategy_id']} | {r['variant_label']}: calmar={r['calmar']} ret={r['ret_pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
