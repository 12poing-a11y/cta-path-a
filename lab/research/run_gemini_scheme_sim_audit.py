# -*- coding: utf-8 -*-
"""Design→simulate Gemini full scheme, then audit."""
from __future__ import annotations

import json
from pathlib import Path

from research.gemini_scheme_audit import audit_scheme_simulation
from research.gemini_scheme_sim import run_full_scheme_simulation

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    sim = run_full_scheme_simulation(ROOT)
    audit = audit_scheme_simulation(sim)
    out = {
        "mode": "gemini_scheme_sim_then_audit",
        "simulation": sim,
        "audit": audit,
    }
    # Compact print view
    compact = {
        "path_a_meta": sim.get("path_a_meta"),
        "P0_portfolio_full_delta": (
            (sim.get("simulation") or {}).get("P0_portfolio") or {}
        ).get("full", {}).get("delta"),
        "P0_per_symbol_full_delta": (
            (sim.get("simulation") or {}).get("P0_per_symbol") or {}
        ).get("full", {}).get("delta"),
        "P0_per_symbol_oos_delta": (
            (sim.get("simulation") or {}).get("P0_per_symbol") or {}
        ).get("oos", {}).get("delta"),
        "P1": {
            "hits": (sim.get("simulation") or {}).get("P1_vrp_sleeve", {}).get("n_opportunity_hits"),
            "metrics": (sim.get("simulation") or {}).get("P1_vrp_sleeve", {}).get("metrics"),
        },
        "P2": {
            "carry_data": (sim.get("simulation") or {}).get("P2_carry_soft", {}).get("carry_data_available"),
            "delta": (sim.get("simulation") or {}).get("P2_carry_soft", {}).get("delta_ret_pct_pts"),
        },
        "combo": (sim.get("simulation") or {}).get("combo_p0_p1"),
        "audit_score": (audit.get("verdict") or {}).get("score"),
        "verdict": audit.get("verdict"),
        "findings": [
            {"id": f["id"], "status": f["status"], "claim": f["claim"]}
            for f in audit.get("findings") or []
        ],
        "summary_zh": audit.get("summary_zh"),
    }
    path = ROOT / "lab" / "research" / "gemini_scheme_sim_audit_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    compact_path = ROOT / "lab" / "research" / "gemini_scheme_sim_audit_compact.json"
    compact_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(path), "compact": str(compact_path), **compact}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
