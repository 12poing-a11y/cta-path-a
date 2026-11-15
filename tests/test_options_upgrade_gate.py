# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from research.options.chain_store import build_snapshot, write_snapshot
from research.options.upgrade_gate import (
    NEXT_UPGRADE_ID,
    assess_upgrade_readiness,
    write_gate,
)


def _snap(code: str, asof: str, *, bidask: bool) -> dict:
    rows = []
    for k in range(14400, 15601, 200):
        mid = 80.0
        rows.append(
            {
                "合约代码": f"{code}701P{k}",
                "今结算": mid,
                "持仓量": 10,
                "隐含波动率": 20,
                **({"买价": mid - 1, "卖价": mid + 1} if bidask else {}),
            }
        )
        rows.append(
            {
                "合约代码": f"{code}701C{k}",
                "今结算": mid,
                "持仓量": 10,
                "隐含波动率": 20,
                **({"买价": mid - 1, "卖价": mid + 1} if bidask else {}),
            }
        )
    return build_snapshot(
        code=code,
        asof=asof,
        futures_contract=f"{code}2701",
        underlying_settle=15000.0,
        option_rows=rows,
        source="tq_live_fast" if bidask else "fixture",
        futures_date=asof,
    )


def test_gate_not_ready_and_locked_next(tmp_path: Path) -> None:
    write_snapshot(tmp_path, _snap("CF", "2026-11-15", bidask=True))
    rep = assess_upgrade_readiness(tmp_path)
    assert rep["ready"] is False
    assert rep["next_upgrade_id"] == NEXT_UPGRADE_ID
    assert "F2" in rep["reminder"]
    assert "bidask_days" in rep["reminder"]


def test_gate_ready_when_cf_hits_primary(tmp_path: Path) -> None:
    for i in range(10):
        d = f"2026-11-{i+1:02d}"
        write_snapshot(tmp_path, _snap("CF", d, bidask=True))
    rep = write_gate(tmp_path)
    assert rep["ready"] is True
    assert "样本已够" in rep["reminder"]
    assert (tmp_path / "data/options/upgrade_gate_latest.json").is_file()
