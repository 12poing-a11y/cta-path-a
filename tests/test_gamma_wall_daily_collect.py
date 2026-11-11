# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from scripts.gamma_wall_daily_collect import (
    expiry_from_snapshot,
    is_data_not_ready,
    resolve_expiry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_is_data_not_ready_empty_czce():
    assert is_data_not_ready(RuntimeError("郑商所期权日行情在 2026-11-11 无返回行；勿用其他日期期权表顶替"))
    assert is_data_not_ready(RuntimeError("新浪/扶摇/天勤均未返回 CF2701 在 2026-11-11 的单合约日线（最新有 2026-11-10）；日盘未收/未结算前请改快照日为已收盘交易日；禁止用主连或前一日价格替代。"))
    assert not is_data_not_ready(RuntimeError("数据质量校验未通过，未保存快照：missing strikes"))
    assert not is_data_not_ready(ValueError("到期日必须晚于快照日期；请核实郑商所规则后再计算"))


def test_expiry_from_repo_snapshot_cf():
    # Real PASS snapshot should yield a future expiry relative to 2026-11-09.
    exp = expiry_from_snapshot("CF2701", "2026-11-09", root=ROOT)
    assert exp == "2026-12-11"


def test_resolve_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GAMMA_CF2701_EXPIRY", "2027-01-15")
    exp, src = resolve_expiry("CF2701", "2026-11-09", root=tmp_path)
    assert exp == "2027-01-15" and src == "env"


def test_resolve_snapshot_fallback(tmp_path):
    d = tmp_path / "data" / "gamma_wall" / "MA2701"
    d.mkdir(parents=True)
    (d / "2026-11-09.json").write_text(
        json.dumps(
            {
                "asof": "2026-11-09",
                "expiry": "2026-12-11",
                "data_quality": {"status": "PASS"},
            }
        ),
        encoding="utf-8",
    )
    exp, src = resolve_expiry("MA2701", "2026-11-09", root=tmp_path)
    assert exp == "2026-12-11" and src == "snapshot"
