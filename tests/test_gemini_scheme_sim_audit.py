# -*- coding: utf-8 -*-
from __future__ import annotations

from research.gemini_scheme_audit import audit_scheme_simulation
from research.gemini_scheme_sim import scheme_design


def test_scheme_design_has_three_layers():
    d = scheme_design()
    assert "P0_tvs" in d["layers"]
    assert "P1_vrp_sleeve" in d["layers"]
    assert "P2_carry_friction" in d["layers"]
    assert d["governance"]["writes_paper_book"] is False


def test_audit_blocks_promotion_on_wiring_fail():
    fake = {
        "design": scheme_design(),
        "path_a_meta": {"max_dd_pct": 6.7, "ret_pct": 4.0},
        "simulation": {
            "P0_portfolio": {
                "full": {"delta": {"ret_pct_pts": 0.1, "dd_pct_pts": -0.5}},
                "oos_acceptance": {"pass": True},
            },
            "P0_per_symbol": {
                "full": {
                    "delta": {"ret_pct_pts": 0.2, "dd_pct_pts": -1.0},
                    "tvs_shadow": {"max_dd_pct": 4.0},
                },
                "oos": {"delta": {"ret_pct_pts": 0.1, "dd_pct_pts": -0.5}},
            },
            "P1_vrp_sleeve": {"ok": True, "n_opportunity_hits": 3, "metrics": {}, "note": "x"},
            "P2_carry_soft": {"ok": True, "carry_data_available": False, "delta_ret_pct_pts": 0.0},
            "combo_p0_p1": {"baseline_ret_pct": 4.0, "combo_p0_p1_ret_pct": 4.2},
        },
    }
    a = audit_scheme_simulation(fake)
    assert a["verdict"]["promote_path_a"] is False
    assert any(f["id"] == "F1_p0_wiring" and f["status"] == "FAIL" for f in a["findings"])
