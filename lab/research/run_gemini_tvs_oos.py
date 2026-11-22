# -*- coding: utf-8 -*-
"""Run Gemini P0 TVS independent OOS study on Path-A equity curve."""
from __future__ import annotations

import json
from pathlib import Path

from research.gemini_tvs_shadow import run_independent_oos_from_historical

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    studies = {
        "frac_60_40": run_independent_oos_from_historical(ROOT, is_frac=0.60),
        "split_20260630": run_independent_oos_from_historical(
            ROOT, split_date="2026-06-30",
        ),
    }
    out = {
        "mode": "gemini_p0_tvs_independent_oos_bundle",
        "disclaimer": (
            "IS 选参冻结后评 OOS；不晋级 Path-A。两个切分互证稳健性。"
        ),
        "studies": studies,
        "summary": {
            name: {
                "ok": s.get("ok"),
                "split": s.get("split"),
                "frozen_params": s.get("frozen_params"),
                "is_delta": (s.get("is_frozen_eval") or {}).get("delta"),
                "oos_delta": (s.get("oos_eval") or {}).get("delta"),
                "oos_acceptance": s.get("oos_acceptance"),
            }
            for name, s in studies.items()
        },
    }
    path = ROOT / "lab" / "research" / "gemini_tvs_oos_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(path), "summary": out["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
