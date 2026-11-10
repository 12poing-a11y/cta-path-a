# -*- coding: utf-8 -*-
"""Capital blend grid (A after B) — unit tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.strategy_blend_grid import (  # noqa: E402
    MAX_DD_PCT,
    OBSERVE_CAP,
    OBSERVE_ID,
    blend_daily_returns,
    default_schemes,
    filter_quality_rows,
    metrics_from_returns,
    passes_quality,
    run_blend_grid,
    validate_weights,
)
from desk.ablation_panel import blend_rows_frame, load_blend  # noqa: E402


def test_validate_observe_cap():
    assert validate_weights({"path_a": 0.9, OBSERVE_ID: 0.1}) is None
    assert validate_weights({"path_a": 0.85, OBSERVE_ID: 0.15}) is not None
    assert "10%" in (validate_weights({OBSERVE_ID: 0.25, "proxy_cwft": 0.75}) or "")


def test_equal_weight_blend_is_mean_return():
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    rets = pd.DataFrame(
        {
            "a": [0.01, 0.02, -0.01, 0.0, 0.03],
            "b": [0.03, 0.0, 0.01, -0.02, 0.01],
        },
        index=idx,
    )
    blended = blend_daily_returns(rets, {"a": 0.5, "b": 0.5})
    expected = (rets["a"] + rets["b"]) / 2.0
    assert (blended - expected).abs().max() < 1e-12
    m = metrics_from_returns(blended)
    assert m["n_days"] == 5
    assert m["ret_pct"] is not None


def test_proxy4_scheme_rejected_by_observe_cap():
    schemes = default_schemes()
    proxy4 = next(s for s in schemes if s["id"] == "proxy4_ew")
    assert float(proxy4["weights"][OBSERVE_ID]) > OBSERVE_CAP
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    cols = ["path_a", "proxy_cwft", "proxy_long_short_cwft", "proxy_frontnext_st", OBSERVE_ID]
    rets = pd.DataFrame({c: 0.001 for c in cols}, index=idx)
    rows = {r["blend_id"]: r for r in run_blend_grid(rets, schemes)}
    assert rows["proxy4_ew"]["ok"] is False
    assert "观察袖套" in (rows["proxy4_ew"]["error"] or "")
    assert rows["pa90_obs10"]["ok"] is True
    assert rows["path_a_100"]["ok"] is True


def test_quality_filter_drops_neg_ret_and_bad_dd():
    rows = [
        {"blend_id": "good", "ok": True, "ret_pct": 5.0, "max_dd_pct": 4.0, "calmar": 1.2},
        {"blend_id": "neg", "ok": True, "ret_pct": -1.0, "max_dd_pct": 3.0, "calmar": None},
        {"blend_id": "dd", "ok": True, "ret_pct": 8.0, "max_dd_pct": MAX_DD_PCT + 1, "calmar": 0.4},
        {"blend_id": "fail", "ok": False, "ret_pct": None, "max_dd_pct": None, "error": "帽"},
    ]
    kept = filter_quality_rows(rows)
    assert [r["blend_id"] for r in kept] == ["good"]
    assert passes_quality(rows[0]) and not passes_quality(rows[1]) and not passes_quality(rows[2])


def test_desk_blend_loader_and_zh_headers():
    # Repo artifact from script run (soft if missing in bare CI without regen).
    payload = load_blend(ROOT)
    if payload is None:
        stub = {
            "rows": [
                {
                    "blend_id": "path_a_100",
                    "label": "100% 路径A",
                    "weights_zh": "路径A 100%",
                    "ret_pct": 1.0,
                    "max_dd_pct": 2.0,
                    "calmar": 0.5,
                    "n_days": 10,
                    "ok": True,
                    "error": "",
                    "risk_note": "",
                }
            ]
        }
        df = blend_rows_frame(stub)
    else:
        art = ROOT / "data" / "ablation" / "strategy_blend_latest.json"
        assert art.is_file()
        data = json.loads(art.read_text(encoding="utf-8"))
        assert data.get("observe_cap") == OBSERVE_CAP
        # Failed / sub-bar schemes are omitted from rows; listed under dropped.
        assert all(r.get("ok") is not False for r in (data.get("rows") or []))
        dropped_ids = {r.get("blend_id") for r in (data.get("dropped") or [])}
        assert "proxy4_ew" in dropped_ids or data.get("n_dropped", 0) >= 1
        df = blend_rows_frame(payload)
        assert df.empty or (df["收益%"] > 0).all()
    assert "组合" in list(df.columns)
    assert "权重" in list(df.columns)
