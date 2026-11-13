# -*- coding: utf-8 -*-
from pathlib import Path

from research.data_quality import classify_bar, config_version_stamp
from research.data_quality.masks import data_valid_mask, tradability_mask
from research.execution.cost_model import list_cost_scenarios, load_cost_scenario, scenario_slippage_ticks
from path_a_filters import load_slippage_ticks

ROOT = Path(__file__).resolve().parents[1]


def test_limit_day_valid_only_not_rejected():
    bar = {
        "code": "CF",
        "open": 14000,
        "high": 14000,
        "low": 14000,
        "close": 14000,
        "atr": 100,
        "volume": 5000,
        "bar_date": "20261027",
        "limit_status": "涨停",
        "price_basis": "contract",
    }
    q = classify_bar(bar, asof="20261027", side="空")
    assert q["status"] == "VALID_ONLY"
    assert q["data_valid"] is True
    assert q["tradable"] is False
    assert "limit_flag" in q["reasons"]


def test_reject_bad_ohlc():
    bar = {
        "code": "CF",
        "open": 100,
        "high": 90,
        "low": 95,
        "close": 92,
        "atr": 5,
        "bar_date": "20261027",
    }
    ok, reasons = data_valid_mask(bar, asof="20261027")
    assert ok is False
    assert "high_lt_low" in reasons
    assert classify_bar(bar, asof="20261027")["status"] == "REJECT"


def test_continuous_not_executable_by_default():
    bar = {
        "code": "CF",
        "open": 15000,
        "high": 15100,
        "low": 14900,
        "close": 15050,
        "atr": 120,
        "volume": 1000,
        "bar_date": "20261027",
        "price_basis": "continuous",
    }
    ok, reasons = tradability_mask(bar)
    assert ok is False
    assert "continuous_not_executable" in reasons
    assert classify_bar(bar, asof="20261027")["status"] == "VALID_ONLY"


def test_pass_contract_bar():
    bar = {
        "code": "CF",
        "open": 15000,
        "high": 15100,
        "low": 14900,
        "close": 15050,
        "atr": 120,
        "volume": 1000,
        "bar_date": "20261027",
        "price_basis": "contract",
    }
    q = classify_bar(bar, asof="20261027")
    assert q["status"] == "PASS"
    assert q["tradable"] is True
    assert q["quality_score"] >= 0.9


def test_degraded_incomplete_ohlc():
    bar = {
        "code": "CF",
        "close": 15000,
        "atr": 120,
        "volume": 1000,
        "bar_date": "20261027",
        "price_basis": "contract",
    }
    q = classify_bar(bar, asof="20261027")
    assert q["status"] == "DEGRADED"
    assert "incomplete_ohlc" in q["reasons"]


def test_cost_scenarios_base_stress_extreme():
    assert set(list_cost_scenarios(ROOT)) >= {"base", "stress", "extreme"}
    base = load_cost_scenario("base", root=ROOT)
    stress = load_cost_scenario("stress", root=ROOT)
    extreme = load_cost_scenario("extreme", root=ROOT)
    assert base["slippage_ticks"] == 1.0
    assert stress["slippage_ticks"] == 2.0
    assert extreme["slippage_ticks"] == 4.0
    assert scenario_slippage_ticks("stress", root=ROOT) == 2.0
    assert load_slippage_ticks(ROOT, scenario="stress") == 2.0
    # default path unchanged
    assert load_slippage_ticks(ROOT) == 1.0


def test_config_version_stamp_has_hashes():
    stamp = config_version_stamp(ROOT)
    assert stamp["schema"] == "cta-config-version-v1"
    assert stamp["execution_rules_sha256"]
    assert stamp["universe_sha256"]
    assert stamp["research_cost_sha256"]
