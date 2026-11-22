# -*- coding: utf-8 -*-
"""Run Gemini P0 TVS shadow overlay grid on Path-A historical equity."""
from __future__ import annotations

import json
from pathlib import Path

from research.gemini_tvs_shadow import run_from_historical_backtest

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    grid = []
    for tv in (0.10, 0.15, 0.20):
        for band in (0.05, 0.0):
            r = run_from_historical_backtest(
                ROOT,
                target_vol=tv,
                tolerance_band=band,
                max_leverage=1.0,
            )
            grid.append({
                "target_vol": tv,
                "tolerance_band": band,
                "baseline": r.get("baseline"),
                "tvs_shadow": r.get("tvs_shadow"),
                "delta": r.get("delta"),
            })
    primary = run_from_historical_backtest(ROOT, target_vol=0.15, tolerance_band=0.05)
    out = {
        "mode": "gemini_p0_tvs_shadow_grid",
        "disclaimer": primary.get("disclaimer"),
        "primary": primary,
        "grid": grid,
        "verdict_hint": (
            "若 tvs 费后/回撤相对 baseline 无改善，则 Gemini P0 不宜晋级 Path-A；"
            "仅作影子旁路研究。"
        ),
    }
    path = ROOT / "lab" / "research" / "gemini_tvs_shadow_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Drop long leverage path from primary for compact artifact
    if isinstance(out["primary"], dict):
        out["primary"] = {k: v for k, v in out["primary"].items() if k != "leverage_tail"}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "wrote": str(path),
        "baseline": primary.get("baseline"),
        "primary_tvs": primary.get("tvs_shadow"),
        "delta": primary.get("delta"),
        "grid": [
            {
                "target_vol": g["target_vol"],
                "band": g["tolerance_band"],
                "ret": (g.get("tvs_shadow") or {}).get("ret_pct"),
                "dd": (g.get("tvs_shadow") or {}).get("max_dd_pct"),
                "d_ret": (g.get("delta") or {}).get("ret_pct_pts"),
                "d_dd": (g.get("delta") or {}).get("dd_pct_pts"),
                "adj": (g.get("tvs_shadow") or {}).get("n_leverage_adjust"),
                "iv_warn": (g.get("tvs_shadow") or {}).get("n_iv_warn"),
            }
            for g in grid
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
