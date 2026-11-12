# -*- coding: utf-8 -*-
"""Seat board prefers Eastmoney when exchange product table omits foreign seats."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.seat_board import _snapshot_uncached  # noqa: E402


def test_cf_prefers_em_foreign_when_czce_omits_gaosheng(tmp_path: Path):
    member = tmp_path / ".cache" / "member"
    member.mkdir(parents=True)
    # Thin CZCE product table: no 高盛 → foreign_net 0
    czce = (
        "郑州商品交易所期货持仓排名表(2026-11-12)\n"
        "品种：棉花CF              日期：2026-11-12\n"
        "名次  |会员简称        |交易量（手）|增减量    |会员简称        |持买仓量  |增减量    |会员简称        |持卖仓量  |增减量\n"
    )
    # 15+ ranked rows without 高盛
    for i in range(1, 17):
        czce += (
            f"{i}     |中信期货（代客）    |1000        |0         "
            f"|中信期货（代客）    |1000        |0         "
            f"|国泰君安（代客）    |1000        |0         \n"
        )
    (member / "czce-20261112.txt").write_text(czce, encoding="utf-8")
    # EM CF2701 includes 高盛净多 9008
    em = {
        "ymd": "20261112",
        "source": "eastmoney",
        "products": {
            "CF": {
                "contract": "CF2701",
                "n": 20,
                "exchange": "CZCE",
                "longs": [["中信期货", 10000.0], ["高盛期货", 9008.0]],
                "shorts": [["中信期货", 8000.0]],
                "long_total": 19008.0,
                "short_total": 8000.0,
            }
        },
    }
    # pad to n>=15 longs for _dce_snapshot gate (len longs/shorts >=10 OR)
    for i in range(18):
        em["products"]["CF"]["longs"].append([f"席位{i}", 100.0 + i])
        em["products"]["CF"]["shorts"].append([f"空席{i}", 90.0 + i])
    em["products"]["CF"]["n"] = 20
    (member / "em-20261112.json").write_text(json.dumps(em, ensure_ascii=False), encoding="utf-8")

    snap = _snapshot_uncached(tmp_path, "CF", "CZCE", "20261112")
    assert snap.get("ok")
    assert snap.get("seat_source") == "eastmoney"
    assert abs(float(snap.get("foreign_net") or 0) - 9008.0) < 1.0
    names = {r.get("name") for r in (snap.get("nets") or [])}
    assert any("高盛" in str(n) for n in names)
