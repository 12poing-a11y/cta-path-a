# -*- coding: utf-8 -*-
"""Build Path-A param trial matrix and estimate PBO (research only; no formal promote).

Usage (repo root):
  python lab/scripts/run_pbo_path_a.py
  python lab/scripts/run_pbo_path_a.py --mode seats --groups 8
"""
from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Allow offline import of historical_backtest without IFIND token
if "ifind_call" not in sys.modules:
    stub = types.ModuleType("ifind_call")
    stub.active_slot = lambda *a, **k: None
    stub.call = lambda *a, **k: {}
    stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = stub

import historical_backtest as hb  # noqa: E402
from lab.validation.trial_matrix import (  # noqa: E402
    build_trial_return_matrix,
    compute_pbo_report,
    path_a_trial_specs,
    save_pbo_artifacts,
)
from research.governance import register_experiment  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Path-A PBO trial matrix")
    ap.add_argument("--mode", default=None, help="base|seats|… (default: universe entry_filter)")
    ap.add_argument("--groups", type=int, default=8, help="CSCV even group count")
    ap.add_argument("--max-trials", type=int, default=0, help="optional cap for smoke runs")
    args = ap.parse_args(argv)

    p = hb._load_cfg()
    mode = args.mode or (
        p["entry_filter"]
        if p.get("entry_filter") in ("base", "p0", "carry", "oi", "member", "climax", "seats")
        else "base"
    )
    print(f"[pbo] fetch pack mode={mode}")
    pack = hb._fetch_pack(p["cfg"]["symbols"])
    specs = path_a_trial_specs(ROOT)
    if args.max_trials and args.max_trials > 0:
        specs = specs[: args.max_trials]
    print(f"[pbo] trials={len(specs)}")

    def _sim(cfg, m, pack=None):
        return hb._simulate_cfg(cfg, m, pack=pack)

    matrix = build_trial_return_matrix(
        simulate_fn=_sim,
        base_cfg=p,
        pack=pack,
        mode=mode,
        specs=specs,
        root=ROOT,
    )
    report = compute_pbo_report(matrix, n_groups=args.groups)
    if matrix.get("ok"):
        # attach full returns into saved matrix file only
        paths = save_pbo_artifacts(report, matrix, root=ROOT)
        print(f"[pbo] wrote {paths['report']} + {paths['matrix']}")
        print(
            f"[pbo] T={matrix['n_obs']} K={matrix['n_trials']} "
            f"~{matrix.get('bytes_estimate', 0)} bytes float64; "
            f"PBO={(report.get('pbo') or {}).get('pbo')}"
        )
        register_experiment(
            name="pbo_path_a_trial_matrix",
            kind="validation_pbo",
            params={"mode": mode, "n_groups": args.groups, "n_trials": matrix["n_trials"]},
            metrics={
                "pbo": (report.get("pbo") or {}).get("pbo"),
                "n_obs": matrix.get("n_obs"),
                "n_eff": (report.get("effective_trials") or {}).get("n_eff"),
            },
            validation=report,
            artifact=paths["report"],
            status="Research",
            notes="Param-grid PBO; does not change execution_rules.",
            root=ROOT,
        )
        return 0
    print(f"[pbo] FAIL {matrix.get('error') or report.get('error')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
