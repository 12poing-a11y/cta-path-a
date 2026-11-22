# -*- coding: utf-8 -*-
"""Run per-symbol Gemini TVS shadow + independent OOS."""
from __future__ import annotations

import json
from pathlib import Path

from research.gemini_tvs_per_symbol import run_per_symbol_oos

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    studies = {
        "frac_60_40": run_per_symbol_oos(root=ROOT, is_frac=0.60),
        "split_20260630": run_per_symbol_oos(root=ROOT, split_date="2026-06-30"),
    }
    out = {
        "mode": "gemini_per_symbol_tvs_oos_bundle",
        "disclaimer": (
            "分品种下行HV TVS；IS选参冻结后评OOS；不晋级Path-A。"
        ),
        "studies": studies,
        "summary": {
            name: {
                "ok": s.get("ok"),
                "split": s.get("split"),
                "frozen_params": s.get("frozen_params"),
                "full_delta": (s.get("full_sample") or {}).get("delta"),
                "full_tracking": (s.get("full_sample") or {}).get("tracking"),
                "is_delta": (s.get("is_eval") or {}).get("delta"),
                "oos_delta": (s.get("oos_eval") or {}).get("delta"),
                "oos_acceptance": s.get("oos_acceptance"),
            }
            for name, s in studies.items()
        },
    }
    path = ROOT / "lab" / "research" / "gemini_tvs_per_symbol_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(path), "summary": out["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
