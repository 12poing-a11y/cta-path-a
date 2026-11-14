# -*- coding: utf-8 -*-
"""BT-01/CP-01: contract fills must not be managed on continuous OHLC."""
from __future__ import annotations

from research.execution.contract_pack import overlay_contract_fills
from historical_backtest import manage_ohlc_bar, next_open_fill


def test_manage_ohlc_bar_contract_ignores_continuous():
    bar = {
        "date": "2026-05-11",
        "open": 4000,
        "high": 4200,
        "low": 3900,
        "close": 4100,
        "contract_open": 3600,
        "contract_high": 3650,
        "contract_low": 3550,
        "contract_close": 3620,
    }
    m = manage_ohlc_bar(bar, "contract")
    assert m is not None
    assert m["high"] == 3650
    assert m["low"] == 3550
    assert m["close"] == 3620
    # continuous high must not leak
    assert m["high"] != 4200


def test_manage_ohlc_bar_contract_missing_returns_none():
    bar = {"date": "d", "open": 1, "high": 2, "low": 0.5, "close": 1.2}
    assert manage_ohlc_bar(bar, "contract") is None


def test_manage_ohlc_bar_proxy_uses_continuous():
    bar = {
        "date": "d",
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "contract_high": 999,
        "contract_low": 1,
        "contract_close": 500,
    }
    m = manage_ohlc_bar(bar, "continuous_proxy")
    assert m["high"] == 12 and m["close"] == 11


def _seed_calendar(tmp_path):
    import shutil
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "configs" / "calendar" / "delivery_rules.json"
    dest = tmp_path / "configs" / "calendar"
    dest.mkdir(parents=True)
    shutil.copy(src, dest / "delivery_rules.json")


def test_large_basis_forced_to_proxy(tmp_path):
    # Continuous ~4000, calendar contract ~3600 → >3% → no contract_open stamp
    _seed_calendar(tmp_path)
    series = {
        "JD": {
            "meta": {"code": "JD", "mult": 10, "tick": 1},
            "hist": [
                {
                    "date": "2026-05-11",
                    "open": 4000,
                    "high": 4100,
                    "low": 3900,
                    "close": 4050,
                    "volume": 100,
                }
            ],
        }
    }
    # Plant exact-contract cache with large basis
    cdir = tmp_path / ".cache" / "contracts"
    cdir.mkdir(parents=True)
    # active_front for May 2026 eggs is typically JD2606 or similar — stamp via fixed month
    (cdir / "JD2701.json").write_text(
        __import__("json").dumps(
            [
                {
                    "date": "2026-05-11",
                    "open": 3600,
                    "high": 3650,
                    "low": 3550,
                    "close": 3620,
                    "volume": 10,
                }
            ]
        ),
        encoding="utf-8",
    )
    report = overlay_contract_fills(
        series, month="2701", historical=False, root=tmp_path, max_basis_rel=0.03
    )
    row = series["JD"]["hist"][0]
    assert row.get("fill_price_basis") == "continuous_proxy"
    assert "contract_open" not in row
    assert row.get("basis_rejected") is True
    assert report["basis_rejected_n"] >= 1


def test_aligned_contract_kept(tmp_path):
    _seed_calendar(tmp_path)
    series = {
        "CF": {
            "meta": {"code": "CF", "mult": 5, "tick": 5},
            "hist": [
                {
                    "date": "2026-11-05",
                    "open": 15000,
                    "high": 15100,
                    "low": 14900,
                    "close": 15050,
                    "volume": 10,
                }
            ],
        }
    }
    cdir = tmp_path / ".cache" / "contracts"
    cdir.mkdir(parents=True)
    (cdir / "CF2701.json").write_text(
        __import__("json").dumps(
            [
                {
                    "date": "2026-11-05",
                    "open": 15040,
                    "high": 15110,
                    "low": 14980,
                    "close": 15060,  # ~0.07% vs continuous
                    "volume": 10,
                }
            ]
        ),
        encoding="utf-8",
    )
    overlay_contract_fills(
        series, month="2701", historical=False, root=tmp_path, max_basis_rel=0.03
    )
    row = series["CF"]["hist"][0]
    assert row.get("fill_price_basis") == "contract"
    assert row.get("contract_open") == 15040


def test_next_open_no_contract_stamp_uses_proxy():
    hist = [
        {"date": "d0", "open": 9, "close": 10},
        {"date": "d1", "open": 12, "close": 11},  # no contract_open
    ]
    c = next_open_fill({"entry": 10.0, "stop": 8.0, "target": 14.0}, hist, 0)
    assert c["entry"] == 12
    assert c["fill_price_basis"] == "continuous_proxy"


def test_basis_lock_blocks_false_target():
    """Contract entry + continuous high must NOT hit a contract-space target."""
    from wyckoff_pullback import apply_stop_target

    entry, stop, target = 3600.0, 3500.0, 3800.0
    bar = {
        "open": 4000,
        "high": 4200,  # continuous — would falsely hit 3800
        "low": 3900,
        "close": 4100,
        "contract_open": 3600,
        "contract_high": 3650,  # never reaches 3800
        "contract_low": 3550,
        "contract_close": 3620,
    }
    # Bug path (continuous manage):
    reason_bug, _ = apply_stop_target("多", entry, stop, target, bar)
    assert reason_bug == "target"
    # Fixed path:
    mbar = manage_ohlc_bar(bar, "contract")
    reason_ok, px = apply_stop_target("多", entry, stop, target, mbar)
    assert reason_ok is None
    assert px == 3620
