import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from gamma_wall import (
    assess_data_quality,
    black76_gamma,
    build_gamma_structure,
    calculate_gamma_rows,
    czce_option_month,
    demo_gamma_snapshot,
    load_history,
    migration_rows,
    resolve_snapshot_asof,
)


def test_czce_month_mapping():
    assert czce_option_month("CF2701") == "CF701"
    assert czce_option_month("SR2701") == "SR701"
    assert czce_option_month("MA2701") == "MA701"
    assert czce_option_month("TA2701") == "TA701"


def test_supported_observation_contracts():
    from gamma_wall import PRODUCTS, supported_contracts

    contracts = supported_contracts()
    assert contracts[0] == "CF2701"
    assert "MA2701" in contracts and "TA2701" in contracts and "SA2701" in contracts
    assert "RM2701" in contracts and "OI2701" in contracts and "FG2701" in contracts
    assert set(c[:-4] for c in contracts) == set(PRODUCTS)


def test_resolve_asof_explicit():
    assert resolve_snapshot_asof("2026-11-05") == "2026-11-05"


def test_resolve_asof_before_session_close_uses_prior_weekday():
    sh = ZoneInfo("Asia/Shanghai")
    # Friday 00:32 → last closed day-session is Thursday 2026-11-05
    now = datetime(2026, 11, 6, 0, 32, tzinfo=sh)
    assert resolve_snapshot_asof(now=now) == "2026-11-05"
    # Friday 15:00 → Friday itself
    now_close = datetime(2026, 11, 6, 15, 0, tzinfo=sh)
    assert resolve_snapshot_asof(now=now_close) == "2026-11-06"


def test_black76_gamma_positive():
    assert black76_gamma(16000,16000,30/365,0.02,0.20) > 0


def test_call_put_symmetric_display():
    rows=[{"合约代码":"CF701C16000","空盘量":100,"隐含波动率":20},
          {"合约代码":"CF701P16000","空盘量":120,"隐含波动率":21}]
    out=calculate_gamma_rows(rows,product_month="CF701",futures_price=16000,
        expiry="2027-01-05",asof="2026-11-05",multiplier=5)
    assert len(out)==1 and out[0]["call_gex"]>0 and out[0]["put_gex"]<0


def test_expired_rejected():
    with pytest.raises(ValueError):
        calculate_gamma_rows([],product_month="CF701",futures_price=16000,
            expiry="2026-11-01",asof="2026-11-05",multiplier=5)


def test_quality_rejects_stale_underlying():
    valid = [{"空盘量": 10, "隐含波动率": 20} for _ in range(8)]
    quality = assess_data_quality(valid, valid, [{}] * 6, "2026-11-04", "2026-11-05")
    assert quality["status"] == "REJECT"
    assert any("日期不一致" in x for x in quality["issues"])


def test_quality_rejects_thin_chain():
    matching = [{"空盘量": 10, "隐含波动率": 20} for _ in range(8)]
    quality = assess_data_quality(matching, matching, [{}] * 3, "2026-11-05", "2026-11-05")
    assert quality["status"] == "REJECT"
    assert quality["valid_strikes"] == 3


def test_quality_passes_sufficient_chain():
    matching = [{"空盘量": 10, "隐含波动率": 20} for _ in range(10)]
    quality = assess_data_quality(matching, matching, [{}] * 8, "2026-11-05", "2026-11-05")
    assert quality["status"] == "PASS"
    assert quality["valid_contract_coverage"] == 1.0


def test_history_ignores_unvalidated_snapshots(tmp_path):
    folder = tmp_path / "data" / "gamma_wall" / "CF2701"
    folder.mkdir(parents=True)
    (folder / "2026-11-04.json").write_text(
        '{"asof":"2026-11-04","data_quality":{"status":"REJECT"}}', encoding="utf-8")
    (folder / "2026-11-05.json").write_text(
        '{"asof":"2026-11-05","data_quality":{"status":"PASS"},"futures_price":16000,'
        '"call_wall":16100,"put_wall":15900,"call_wall_gex":1,"put_wall_gex":2}', encoding="utf-8")
    assert len(load_history("CF2701", root=tmp_path)) == 1
    assert len(migration_rows("CF2701", root=tmp_path)) == 1


def test_build_gamma_structure_flip_and_net():
    rows = [
        {"strike": 100.0, "call_gex": 10.0, "put_gex": -40.0},
        {"strike": 110.0, "call_gex": 20.0, "put_gex": -25.0},
        {"strike": 120.0, "call_gex": 35.0, "put_gex": -10.0},
        {"strike": 130.0, "call_gex": 40.0, "put_gex": -5.0},
    ]
    s = build_gamma_structure(rows, futures_price=115.0)
    assert s["call_wall"]["strike"] == 130.0
    assert s["put_wall"]["strike"] == 100.0
    assert s["gamma_flip"] is not None
    assert 100.0 < s["gamma_flip"] < 130.0
    assert abs(s["net_gex"] - sum(r["call_gex"] + r["put_gex"] for r in rows)) < 1e-9
    assert len(s["cum_net_gex"]) == 4
    assert s["cum_net_gex"][-1]["cum_net_gex"] == s["net_gex"]


def test_demo_gamma_snapshot_has_layout_fields():
    d = demo_gamma_snapshot(contract="CF2701")
    assert d["demo"] is True
    assert d["call_wall"] > d["put_wall"]
    assert d["gamma_flip"] is not None
    assert d["cum_net_gex"]
    assert d["data_quality"]["status"] == "DEMO"


def test_migration_includes_flip_when_rows_present(tmp_path):
    folder = tmp_path / "data" / "gamma_wall" / "CF2701"
    folder.mkdir(parents=True)
    rows = [
        {"strike": 15900, "call_gex": 5, "put_gex": -40},
        {"strike": 16000, "call_gex": 20, "put_gex": -20},
        {"strike": 16100, "call_gex": 45, "put_gex": -5},
    ]
    import json
    (folder / "2026-11-05.json").write_text(
        json.dumps(
            {
                "asof": "2026-11-05",
                "data_quality": {"status": "PASS"},
                "futures_price": 16000,
                "call_wall": 16100,
                "put_wall": 15900,
                "call_wall_gex": 45,
                "put_wall_gex": 40,
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    mig = migration_rows("CF2701", root=tmp_path)
    assert len(mig) == 1
    assert mig[0]["gamma_flip"] is not None
    assert mig[0]["net_gex"] is not None
    assert mig[0]["call_dist_pct"] is not None
