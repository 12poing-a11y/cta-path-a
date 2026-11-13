# -*- coding: utf-8 -*-
"""Gamma wall research: migration / touch / IV×OI (Research only)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.gamma.pipeline import run_gamma_research, save_gamma_research  # noqa: E402
from research.governance import register_experiment  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", default="CF2701")
    args = ap.parse_args(argv)
    payload = run_gamma_research(args.contract, root=ROOT)
    path = save_gamma_research(payload, root=ROOT)
    mig = payload.get("migration") or {}
    touch = payload.get("touch") or {}
    ivoi = payload.get("iv_oi") or {}
    print(
        f"[gamma] {args.contract} migration_events={mig.get('n_events')} "
        f"labels={mig.get('label_counts')} touch={touch.get('n_events')} "
        f"touch_probs={touch.get('outcome_probs')} iv_oi_days={ivoi.get('n_days')} "
        f"regimes={ivoi.get('regime_counts')}"
    )
    print(f"[gamma] wrote {path}")
    register_experiment(
        name=f"gamma_research_{args.contract}",
        kind="gamma_structure",
        params={"contract": args.contract},
        metrics={
            "migration_labels": mig.get("label_counts"),
            "touch_probs": touch.get("outcome_probs"),
            "iv_oi_regimes": ivoi.get("regime_counts"),
        },
        validation={"migration": mig.get("ok"), "touch": touch.get("ok")},
        artifact=path,
        status="Research",
        notes="Gamma structure research; no Path-A signal.",
        root=ROOT,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
