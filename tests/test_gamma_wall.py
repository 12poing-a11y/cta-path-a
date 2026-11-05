import pytest
from gamma_wall import (
    assess_data_quality, black76_gamma, calculate_gamma_rows, czce_option_month,
    load_history, migration_rows,
)


def test_czce_month_mapping():
    assert czce_option_month("CF2701") == "CF701"
    assert czce_option_month("SR2701") == "SR701"


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
    quality = assess_data_quality([{}] * 10, [{}] * 10, [{}] * 6, "2026-11-04", "2026-11-05")
    assert quality["status"] == "REJECT"
    assert any("日期不一致" in x for x in quality["issues"])


def test_quality_rejects_thin_chain():
    quality = assess_data_quality([{}] * 8, [{}] * 8, [{}] * 3, "2026-11-05", "2026-11-05")
    assert quality["status"] == "REJECT"
    assert quality["valid_strikes"] == 3


def test_quality_passes_sufficient_chain():
    quality = assess_data_quality([{}] * 10, [{}] * 10, [{}] * 8, "2026-11-05", "2026-11-05")
    assert quality["status"] == "PASS"
    assert quality["valid_contract_coverage"] == 0.8


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
