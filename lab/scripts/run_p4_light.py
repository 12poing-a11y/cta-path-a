# -*- coding: utf-8 -*-
"""P4 light: LSP reversal / trend fail / breakout continue (Research only)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.ml.train import run_p4_light, save_p4_light  # noqa: E402
from research.governance import register_experiment  # noqa: E402


def main() -> int:
    payload = run_p4_light(ROOT)
    path = save_p4_light(payload, ROOT)
    print(f"[p4] samples={payload.get('sample_counts')}")
    for name, task in (payload.get("tasks") or {}).items():
        if not task.get("ok"):
            print(f"[p4] {name}: FAIL {task.get('error')}")
            continue
        oos = task.get("oos") or {}
        print(
            f"[p4] {name}: backend={task.get('backend')} "
            f"n={task.get('n')} oos_auc={oos.get('auc')} oos_f1={oos.get('f1')} "
            f"top={[(x['feature'], x['importance']) for x in (task.get('importance_top') or [])[:3]]}"
        )
    print(f"[p4] wrote {path}")
    register_experiment(
        name="p4_light_cf",
        kind="ml_light",
        params={"symbol": "CF"},
        metrics={
            k: (v.get("oos") if isinstance(v, dict) else None)
            for k, v in (payload.get("tasks") or {}).items()
        },
        validation=payload,
        artifact=path,
        status="Research",
        notes="P4 light trio; does not change Path-A.",
        root=ROOT,
    )
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
