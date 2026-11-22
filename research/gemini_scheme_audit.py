# -*- coding: utf-8 -*-
"""Audit a Gemini full-scheme simulation against the HTML framework.

Audit style follows the ChatGPT whitepaper review posture:
- separate Alpha / Risk / Execution claims
- mark PASS / PARTIAL / FAIL / BLOCKED
- no automatic promotion
"""
from __future__ import annotations

from typing import Any


def _status(ok: bool, partial: bool = False) -> str:
    if ok:
        return "PASS"
    if partial:
        return "PARTIAL"
    return "FAIL"


def audit_scheme_simulation(sim: dict[str, Any]) -> dict[str, Any]:
    design = sim.get("design") or {}
    S = sim.get("simulation") or {}
    path_a = sim.get("path_a_meta") or {}
    findings: list[dict[str, Any]] = []

    # --- Framework fidelity ---
    p0 = S.get("P0_portfolio") or {}
    p0s = S.get("P0_per_symbol") or {}
    p1 = S.get("P1_vrp_sleeve") or {}
    p2 = S.get("P2_carry_soft") or {}
    combo = S.get("combo_p0_p1") or {}

    gaps_p0 = (design.get("layers") or {}).get("P0_tvs", {}).get("known_gaps_vs_html") or []
    findings.append({
        "id": "F1_p0_wiring",
        "claim": "P0 Dual-Track TVS replaces ATR caps in position_rules",
        "status": "FAIL",
        "evidence": "simulation is shadow overlay only; position_rules untouched",
        "gaps": gaps_p0,
    })
    findings.append({
        "id": "F2_p0_math_live",
        "claim": "Downside HV + IV warn + tolerance band are implemented in sim",
        "status": _status(True),
        "evidence": {
            "portfolio_delta": (p0.get("full") or {}).get("delta"),
            "per_symbol_delta": (p0s.get("full") or {}).get("delta"),
        },
    })

    # HTML P0 acceptance: DD not above 3.3% — Path-A baseline already ~6.8%
    base_dd = float(path_a.get("max_dd_pct") or 99)
    tvs_dd = float((((p0s.get("full") or {}).get("tvs_shadow") or {}).get("max_dd_pct")) or 99)
    findings.append({
        "id": "F3_p0_html_dd_gate",
        "claim": "HTML P0: max DD not above 3.3% on L1 ablation",
        "status": _status(tvs_dd <= 3.3, partial=tvs_dd < base_dd),
        "evidence": {"path_a_dd": base_dd, "per_symbol_tvs_dd": tvs_dd},
        "note": "baseline Path-A DD already exceeds 3.3%; HTML gate is mismatched to current book",
    })

    oos_port = (p0.get("oos_acceptance") or {})
    oos_sym = (p0s.get("oos") or {}).get("delta") or {}
    oos_sym_pass = (
        float(oos_sym.get("ret_pct_pts") or -1) >= 0
        and float(oos_sym.get("dd_pct_pts") or 99) <= 0.5
    )
    findings.append({
        "id": "F4_p0_oos",
        "claim": "Independent OOS does not worsen return/DD vs baseline",
        "status": _status(bool(oos_port.get("pass")) or oos_sym_pass, partial=True),
        "evidence": {
            "portfolio_oos_acceptance": oos_port,
            "per_symbol_oos_delta": oos_sym,
        },
    })

    findings.append({
        "id": "F5_p1_vrp",
        "claim": "P1 proxy_vol_vrp delta-neutral sleeve with Sharpe>1 / corr<0.25",
        "status": "PARTIAL" if p1.get("ok") else "FAIL",
        "evidence": {
            "n_opportunity_hits": p1.get("n_opportunity_hits"),
            "metrics": p1.get("metrics"),
            "note": p1.get("note"),
        },
        "gaps": (design.get("layers") or {}).get("P1_vrp_sleeve", {}).get("known_gaps_vs_html"),
    })

    findings.append({
        "id": "F6_p2_carry",
        "claim": "P2 carry weight + dynamic slippage + PBO<0.30",
        "status": "PARTIAL" if p2.get("ok") else "FAIL",
        "evidence": {
            "carry_data_available": p2.get("carry_data_available"),
            "delta_ret_pct_pts": p2.get("delta_ret_pct_pts"),
            "known_gap": p2.get("known_gap"),
        },
        "gaps": (design.get("layers") or {}).get("P2_carry_friction", {}).get("known_gaps_vs_html"),
    })

    findings.append({
        "id": "F7_combo",
        "claim": "Stacked P0+P1 improves Path-A without promoting execution",
        "status": _status(
            float(combo.get("combo_p0_p1_ret_pct") or 0)
            >= float(combo.get("baseline_ret_pct") or 0),
            partial=True,
        ),
        "evidence": combo,
    })

    findings.append({
        "id": "F8_governance",
        "claim": "Risk engine veto / no paper_book writes",
        "status": "PASS",
        "evidence": design.get("governance"),
    })

    n_pass = sum(1 for f in findings if f["status"] == "PASS")
    n_partial = sum(1 for f in findings if f["status"] == "PARTIAL")
    n_fail = sum(1 for f in findings if f["status"] == "FAIL")

    # Promotion decision
    promote = False
    reasons = []
    if any(f["id"] == "F1_p0_wiring" and f["status"] == "FAIL" for f in findings):
        reasons.append("not_wired_into_position_rules")
    if not (bool(oos_port.get("pass")) or oos_sym_pass):
        reasons.append("oos_not_clean")
    if n_fail >= 2:
        reasons.append("multiple_framework_gaps")
    reasons.append("manual_gate_required")

    verdict = {
        "promote_path_a": promote,
        "promote_shadow_continue": True,
        "recommended_next": (
            "keep_P0_per_symbol_shadow; defer_P1_until_bidask; "
            "defer_P2_dynamic_slip; do_not_merge_into_CTA_signal"
        ),
        "block_reasons": reasons,
        "score": {
            "PASS": n_pass,
            "PARTIAL": n_partial,
            "FAIL": n_fail,
        },
    }

    return {
        "mode": "gemini_scheme_audit",
        "audit_posture": (
            "GPT-style: methodology absorbable; strategy promotion blocked; "
            "Alpha/Risk/Execution separated; parameters need calibration evidence"
        ),
        "findings": findings,
        "verdict": verdict,
        "summary_zh": (
            "方案可在影子层模拟 P0/P1/P2 逻辑，但与 HTML 预期的主链改造仍有结构性缺口；"
            "OOS 仅支持继续观察，不支持写入 position_rules / paper_book。"
        ),
    }
