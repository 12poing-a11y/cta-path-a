# -*- coding: utf-8 -*-
"""Soft refresh for desk research artifacts after post-market minute/bars.

Research / Shadow only. Never writes paper_book, formal seats densify promotion,
or Path-A formal BT promotion (scorecard / weekly).

Packs (split sync — isolate slow/network from fast desk pages):
  core  ~6–8s   LSP / P4 / Gamma research / IC / OOS / portfolio / NPD
  heavy ~12s+   ablation+blend; optional gamma_wall_collect (network)
  all           core then heavy

Local probe (2026-11-18, no gamma collect): total ~19s; ablation alone ~12s.
Artifact bulk: lab/research/lsp ~5MB; other research packs <<1MB each.
Minute cache (~14MB) stays in main daily_update path, not here.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TZ = ZoneInfo("Asia/Shanghai")

# Explicitly not auto-run here (policy / external / heavy formal).
SKIPPED_BY_POLICY: tuple[dict[str, str], ...] = (
    {
        "id": "formal_scorecard",
        "reason": "rewrites formal historical_backtest + PBO; needs explicit order",
    },
    {
        "id": "weekly_backtest",
        "reason": "weekly.yml Saturday formal PnL path",
    },
    {
        "id": "option_hedge_historical_bt",
        "reason": "heavy observe BT; desk button / historical_backtest --observe",
    },
    {
        "id": "equity_timing",
        "reason": "external/equity_timing_latest.json is manual input",
    },
    {
        "id": "cotton_events_ingest",
        "reason": "data/cotton/cotton_events.csv stays human-audited; only reminders snapshot refreshes",
    },
)

# Write boundary map: what each step may touch (Research only).
WRITE_BOUNDS: dict[str, dict[str, Any]] = {
    "lsp": {
        "writes": ["lab/research/lsp/lsp_*_{15m,60m}_{latest,events}.json"],
        "reads": [".cache/akshare/minute/*"],
        "mutates_formal": False,
        "typical_s": 1.3,
        "pack": "core",
    },
    "p4_light": {
        "writes": ["lab/research/ml/p4_light_latest.json"],
        "reads": ["lab/research/lsp/*", ".cache/history or daily bars"],
        "mutates_formal": False,
        "typical_s": 2.0,
        "pack": "core",
    },
    "gamma_research": {
        "writes": ["lab/research/gamma/gamma_*_latest.json"],
        "reads": ["data/gamma_wall/<contract>/*.json"],
        "mutates_formal": False,
        "typical_s": 0.2,
        "pack": "core",
    },
    "ic_groups": {
        "writes": ["lab/research/ic/ic_groups_latest.json"],
        "reads": ["lab panel / factors"],
        "mutates_formal": False,
        "typical_s": 1.5,
        "pack": "core",
    },
    "oos_vs_path_a": {
        "writes": ["lab/research/oos/oos_vs_path_a_latest.json", "lab/research/runs/oos_*"],
        "reads": ["lab factors", "historical_backtest_latest.json (read-only)"],
        "mutates_formal": False,
        "typical_s": 1.1,
        "pack": "core",
    },
    "portfolio_risk": {
        "writes": ["lab/research/portfolio/portfolio_risk_latest.json"],
        "reads": ["historical_backtest_latest.json (read-only)"],
        "mutates_formal": False,
        "typical_s": 0.1,
        "pack": "core",
    },
    "npd_reminders": {
        "writes": ["data/cotton/npd_reminders_latest.json"],
        "reads": ["data/cotton/cotton_events.csv (no invent)", "bars"],
        "mutates_formal": False,
        "typical_s": 0.1,
        "pack": "core",
    },
    "ablation": {
        "writes": ["data/ablation/strategy_indicator_ablation_latest.json"],
        "reads": ["bars", "seats cache", "carry curves"],
        "mutates_formal": False,
        "typical_s": 12.0,
        "pack": "heavy",
        "note": "mode=ablation only (not full_grid)",
    },
    "strategy_blend": {
        "writes": ["data/ablation/strategy_blend_latest.json"],
        "reads": ["data/ablation/strategy_indicator_ablation_latest.json", "equity curves"],
        "mutates_formal": False,
        "typical_s": 0.5,
        "pack": "heavy",
    },
    "gamma_wall_collect": {
        "writes": ["data/gamma_wall/<contract>/<asof>.json", ".cache/gamma_wall/raw/*"],
        "reads": ["AkShare/CZCE option day tables", "exact-contract futures"],
        "mutates_formal": False,
        "typical_s": None,
        "pack": "heavy",
        "note": "network; often not-ready at 15:30; gamma_wall_daily.yml@16:35 backup",
    },
}

CORE_STEPS: tuple[str, ...] = (
    "lsp",
    "p4_light",
    "gamma_research",
    "ic_groups",
    "oos_vs_path_a",
    "portfolio_risk",
    "npd_reminders",
)
HEAVY_STEPS: tuple[str, ...] = (
    "ablation",
    "strategy_blend",
    "gamma_wall_collect",
)


def _now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _step(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    t0 = time.time()
    bound = WRITE_BOUNDS.get(name) or {}
    row: dict[str, Any] = {
        "id": name,
        "ok": False,
        "at": _now(),
        "pack": bound.get("pack"),
        "writes": bound.get("writes"),
        "mutates_formal": bool(bound.get("mutates_formal")),
    }
    try:
        out = fn()
        row["ok"] = True
        if isinstance(out, dict):
            row["detail"] = {
                k: out.get(k)
                for k in (
                    "ok",
                    "n_ok",
                    "n_skip",
                    "n",
                    "path",
                    "contracts",
                    "n_events",
                    "asof",
                    "ready",
                    "status",
                )
                if k in out
            }
            if "path" in out:
                row["path"] = out["path"]
        elif isinstance(out, str):
            row["path"] = out
    except Exception as exc:  # noqa: BLE001
        row["ok"] = False
        row["error"] = str(exc)[:400]
        row["trace"] = traceback.format_exc()[-500:]
    row["seconds"] = round(time.time() - t0, 2)
    return row


def _run_script(
    root: Path,
    rel: str,
    args: list[str] | None = None,
    *,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    cmd = [sys.executable, str(root / rel), *(args or [])]
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-500:]
        raise RuntimeError(f"{rel} exit={proc.returncode}: {err}")
    return {"ok": True, "path": rel, "tail": (proc.stdout or "")[-240:]}


def _refresh_lsp(root: Path) -> dict[str, Any]:
    from lab.lsp.pipeline import refresh_lsp_universe

    return refresh_lsp_universe(root, period="both")


def _refresh_p4(root: Path) -> dict[str, Any]:
    from lab.ml.train import run_p4_light, save_p4_light

    payload = run_p4_light(root)
    path = save_p4_light(payload, root)
    return {"ok": bool(payload.get("ok")), "path": path, "n": (payload.get("sample_counts") or {})}


def _refresh_gamma_research(root: Path) -> dict[str, Any]:
    from gamma_wall import OBSERVE_MONTH, supported_contracts
    from lab.gamma.pipeline import run_gamma_research, save_gamma_research

    contracts = list(supported_contracts(OBSERVE_MONTH))
    hist = root / "data" / "gamma_wall"
    with_hist = [c for c in contracts if (hist / c).is_dir()]
    targets = with_hist or contracts
    paths: list[str] = []
    for contract in targets:
        payload = run_gamma_research(contract, root=root)
        paths.append(save_gamma_research(payload, root=root))
    return {
        "ok": bool(paths),
        "n_ok": len(paths),
        "contracts": targets,
        "path": paths[-1] if paths else None,
    }


def _refresh_gamma_wall_collect(root: Path) -> dict[str, Any]:
    asof = datetime.now(TZ).strftime("%Y-%m-%d")
    return _run_script(
        root,
        "scripts/gamma_wall_daily_collect.py",
        ["--date", asof],
        timeout_s=420.0,
    )


def _refresh_ablation(root: Path) -> dict[str, Any]:
    return _run_script(
        root,
        "scripts/strategy_indicator_ablation.py",
        ["--mode", "ablation"],
        timeout_s=600.0,
    )


def _refresh_blend(root: Path) -> dict[str, Any]:
    return _run_script(root, "scripts/strategy_blend_grid.py", timeout_s=120.0)


def _refresh_ic(root: Path) -> dict[str, Any]:
    return _run_script(root, "lab/scripts/run_ic_groups.py", timeout_s=180.0)


def _refresh_oos(root: Path) -> dict[str, Any]:
    return _run_script(root, "lab/scripts/run_oos_vs_path_a.py", timeout_s=180.0)


def _refresh_portfolio(root: Path) -> dict[str, Any]:
    return _run_script(root, "lab/scripts/run_portfolio_risk.py", timeout_s=120.0)


def _refresh_npd_reminders(root: Path) -> dict[str, Any]:
    from cotton_npd import shadow_reminders_for_root

    pack = shadow_reminders_for_root(root)
    out = root / "data" / "cotton" / "npd_reminders_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **(pack if isinstance(pack, dict) else {"raw": pack}),
        "schema": "cta-npd-reminders-v1",
        "generated_at": _now(),
        "live_trading": False,
        "status": "Research",
        "note": "Snapshot only; cotton_events.csv remains human-audited.",
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "path": str(out.relative_to(root)),
        "asof": payload.get("asof"),
        "n": len(payload.get("reminders") or []),
    }


_STEP_FNS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "lsp": _refresh_lsp,
    "p4_light": _refresh_p4,
    "gamma_research": _refresh_gamma_research,
    "ic_groups": _refresh_ic,
    "oos_vs_path_a": _refresh_oos,
    "portfolio_risk": _refresh_portfolio,
    "npd_reminders": _refresh_npd_reminders,
    "ablation": _refresh_ablation,
    "strategy_blend": _refresh_blend,
    "gamma_wall_collect": _refresh_gamma_wall_collect,
}


def _steps_for_pack(
    pack: str,
    *,
    include_gamma_wall_collect: bool,
) -> list[str]:
    pack_l = (pack or "all").strip().lower()
    if pack_l == "core":
        return list(CORE_STEPS)
    if pack_l == "heavy":
        ids = ["ablation", "strategy_blend"]
        if include_gamma_wall_collect:
            ids.append("gamma_wall_collect")
        return ids
    if pack_l == "all":
        ids = list(CORE_STEPS) + ["ablation", "strategy_blend"]
        if include_gamma_wall_collect:
            ids.append("gamma_wall_collect")
        return ids
    raise ValueError(f"unknown pack={pack!r}; use core|heavy|all")


def refresh_desk_research(
    root: Path,
    *,
    pack: str = "all",
    include_lsp: bool = True,
    include_gamma_wall_collect: bool = True,
    include_ablation: bool = True,
) -> dict[str, Any]:
    """Run soft desk research refresh for one pack. Step failures do not abort siblings."""
    step_ids = _steps_for_pack(pack, include_gamma_wall_collect=include_gamma_wall_collect)
    if not include_lsp:
        step_ids = [s for s in step_ids if s != "lsp"]
    if not include_ablation:
        step_ids = [s for s in step_ids if s not in ("ablation", "strategy_blend")]

    t_all = time.time()
    steps: list[dict[str, Any]] = []
    for sid in step_ids:
        fn = _STEP_FNS[sid]
        steps.append(_step(sid, lambda f=fn: f(root)))

    n_ok = sum(1 for s in steps if s.get("ok"))
    seconds_total = round(time.time() - t_all, 2)
    summary = {
        "ok": n_ok > 0,
        "schema": "cta-desk-daily-refresh-v1",
        "pack": pack,
        "generated_at": _now(),
        "n_ok": n_ok,
        "n_fail": len(steps) - n_ok,
        "seconds_total": seconds_total,
        "steps": steps,
        "write_bounds": {sid: WRITE_BOUNDS.get(sid) for sid in step_ids},
        "skipped_by_policy": list(SKIPPED_BY_POLICY),
        "live_trading": False,
        "status": "Research",
    }
    out_name = (
        "desk_daily_refresh_latest.json"
        if pack == "all"
        else f"desk_daily_refresh_{pack}_latest.json"
    )
    out = root / "lab" / "research" / out_name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Always maintain merged pointer when running packs separately.
    if pack in ("core", "heavy"):
        merged = root / "lab" / "research" / "desk_daily_refresh_latest.json"
        prev: dict[str, Any] = {}
        if merged.is_file():
            try:
                prev = json.loads(merged.read_text(encoding="utf-8"))
            except Exception:
                prev = {}
        prev_steps = {
            str(s.get("id")): s
            for s in (prev.get("steps") or [])
            if isinstance(s, dict) and s.get("id")
        }
        for s in steps:
            prev_steps[str(s.get("id"))] = s
        merged_steps = list(prev_steps.values())
        merged_payload = {
            "ok": any(s.get("ok") for s in merged_steps),
            "schema": "cta-desk-daily-refresh-v1",
            "pack": "merged",
            "generated_at": _now(),
            "n_ok": sum(1 for s in merged_steps if s.get("ok")),
            "n_fail": sum(1 for s in merged_steps if not s.get("ok")),
            "seconds_total": round(
                sum(float(s.get("seconds") or 0) for s in merged_steps), 2
            ),
            "steps": merged_steps,
            "packs_run": sorted(
                {
                    *(prev.get("packs_run") or []),
                    pack,
                }
            ),
            "write_bounds": WRITE_BOUNDS,
            "skipped_by_policy": list(SKIPPED_BY_POLICY),
            "live_trading": False,
            "status": "Research",
        }
        merged.write_text(
            json.dumps(merged_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary["merged_path"] = str(merged.relative_to(root))
    summary["path"] = str(out.relative_to(root))
    return summary


def refresh_desk_research_split(
    root: Path,
    *,
    include_gamma_wall_collect: bool = True,
) -> dict[str, Any]:
    """Run core then heavy as two soft packs (recommended for daily_update)."""
    core = refresh_desk_research(
        root, pack="core", include_gamma_wall_collect=False
    )
    heavy = refresh_desk_research(
        root,
        pack="heavy",
        include_gamma_wall_collect=include_gamma_wall_collect,
    )
    return {
        "ok": bool(core.get("ok") or heavy.get("ok")),
        "schema": "cta-desk-daily-refresh-split-v1",
        "core": core,
        "heavy": heavy,
        "seconds_total": round(
            float(core.get("seconds_total") or 0) + float(heavy.get("seconds_total") or 0),
            2,
        ),
        "path": heavy.get("merged_path") or core.get("merged_path") or core.get("path"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="Soft desk research daily refresh")
    ap.add_argument(
        "--pack",
        default="all",
        choices=("core", "heavy", "all", "split"),
        help="core=fast desk; heavy=ablation(+gamma collect); split=core then heavy",
    )
    ap.add_argument("--skip-gamma-collect", action="store_true")
    ap.add_argument("--skip-ablation", action="store_true")
    ap.add_argument("--skip-lsp", action="store_true")
    args = ap.parse_args(argv)

    if args.pack == "split":
        pack = refresh_desk_research_split(
            root, include_gamma_wall_collect=not args.skip_gamma_collect
        )
        print(
            f"[desk-refresh] split ok={pack.get('ok')} "
            f"seconds={pack.get('seconds_total')} → {pack.get('path')}"
        )
        for label in ("core", "heavy"):
            sub = pack.get(label) or {}
            print(
                f"  [{label}] n_ok={sub.get('n_ok')} n_fail={sub.get('n_fail')} "
                f"{sub.get('seconds_total')}s"
            )
            for s in sub.get("steps") or []:
                flag = "ok" if s.get("ok") else "FAIL"
                print(
                    f"    [{flag}] {s.get('id')} {s.get('seconds')}s "
                    f"{s.get('error') or s.get('path') or ''}"
                )
    else:
        pack = refresh_desk_research(
            root,
            pack=args.pack,
            include_lsp=not args.skip_lsp,
            include_gamma_wall_collect=not args.skip_gamma_collect,
            include_ablation=not args.skip_ablation,
        )
        print(
            f"[desk-refresh] pack={args.pack} ok={pack.get('ok')} "
            f"n_ok={pack.get('n_ok')} n_fail={pack.get('n_fail')} "
            f"seconds={pack.get('seconds_total')} → {pack.get('path')}"
        )
        for s in pack.get("steps") or []:
            flag = "ok" if s.get("ok") else "FAIL"
            print(
                f"  [{flag}] {s.get('id')} {s.get('seconds')}s "
                f"{s.get('error') or s.get('path') or ''}"
            )
    for sk in SKIPPED_BY_POLICY:
        print(f"  [skip] {sk['id']}: {sk['reason']}")
    print("  [bounds] see WRITE_BOUNDS / lab/research/desk_daily_refresh_*_latest.json")
    return 0 if pack.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
