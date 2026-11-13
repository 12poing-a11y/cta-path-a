# -*- coding: utf-8 -*-
"""Strategy admission checklist — reports only; never auto-promotes."""
from __future__ import annotations

from typing import Any


def evaluate_strategy_gate(
    validation: dict[str, Any] | None,
    *,
    has_oos: bool = False,
    has_cost_stress: bool = False,
    beats_path_a: bool | None = None,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Engineering checklist thresholds — not universal statistical law."""
    v = validation or {}
    psr = (v.get("psr") or {}).get("psr")
    dsr = (v.get("dsr") or {}).get("dsr")
    pbo = (v.get("pbo") or {}).get("pbo")
    checks = [
        {"id": "oos", "ok": bool(has_oos), "detail": "Independent OOS reported"},
        {"id": "cost_stress", "ok": bool(has_cost_stress), "detail": "Base+Stress costs reported"},
        {
            "id": "psr_reported",
            "ok": psr is not None,
            "detail": f"PSR={psr}",
        },
        {
            "id": "dsr_reported",
            "ok": dsr is not None,
            "detail": f"DSR={dsr}",
        },
        {
            "id": "pbo_reported_or_waived",
            "ok": pbo is not None or (v.get("pbo") or {}).get("error") == "trial_matrix_required",
            "detail": f"PBO={pbo} ({(v.get('pbo') or {}).get('error')})",
        },
        {
            "id": "incremental_vs_path_a",
            "ok": beats_path_a is True,
            "detail": "Must beat Path-A or clearly improve risk (manual flag)",
        },
        {
            "id": "human_approval",
            "ok": bool(human_approved),
            "detail": "Approved tier requires human sign-off",
        },
    ]
    hard = {"oos", "cost_stress", "psr_reported", "human_approval"}
    hard_fail = [c for c in checks if c["id"] in hard and not c["ok"]]
    return {
        "schema": "cta-strategy-gate-v1",
        "pass": len(hard_fail) == 0 and human_approved,
        "auto_promote": False,
        "checks": checks,
        "hard_failures": [c["id"] for c in hard_fail],
        "note": "Gate never mutates execution_rules.json or universe.json.",
    }
