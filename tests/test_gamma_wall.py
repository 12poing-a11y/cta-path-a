import pytest
from gamma_wall import black76_gamma, calculate_gamma_rows, czce_option_month

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
