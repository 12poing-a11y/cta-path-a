# -*- coding: utf-8 -*-
"""Eastmoney inventory bypass: every Path-A code must map to a name in the akshare option list.

Regression: L was mapped to 「塑料」 (not an option) so the bypass returned ok=False and L stayed missing.
The option list below is a snapshot of akshare ``futures_inventory_em`` symbols (2026-11-27).
"""
from __future__ import annotations

import json
from pathlib import Path

from warehouse_receipt import _EM_SYMBOL

ROOT = Path(__file__).resolve().parents[1]

_EM_OPTIONS = {
    "玻璃", "丙烯", "菜籽", "短纤", "白糖", "尿素", "玉米", "镍", "豆二", "焦煤", "锡", "郑棉", "纯苯",
    "粳米", "菜油", "豆一", "鸡蛋", "烧碱", "豆粕", "玉米淀粉", "聚乙烯", "乙二醇", "聚丙烯", "锰硅",
    "硅铁", "对二甲苯", "纯碱", "菜粕", "PTA", "苹果", "瓶片", "铸造铝合金", "低硫燃料油", "沥青",
    "20号胶", "不锈钢", "沪铅", "胶版印刷纸", "棉纱", "豆油", "PVC", "螺纹钢", "橡胶", "焦炭", "纸浆",
    "燃油", "热卷", "氧化铝", "甲醇", "沪锌", "碳酸锂", "沪铝", "沪铜", "液化石油气", "工业硅", "棕榈",
    "铁矿石", "红枣", "苯乙烯", "多晶硅", "丁二烯橡胶", "沪金", "沪银", "生猪", "花生", "葵油",
}


def test_l_maps_to_polyethylene():
    assert _EM_SYMBOL["L"] == "聚乙烯"


def test_every_em_symbol_is_a_valid_option():
    bad = {code: name for code, name in _EM_SYMBOL.items() if name not in _EM_OPTIONS}
    assert bad == {}


def test_every_universe_code_has_em_symbol():
    uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    codes = {str(r["code"]).upper() for r in uni.get("symbols") or [] if r.get("code")}
    # Codes without a bypass mapping must be listed as known gaps, not silently absent.
    missing = sorted(codes - set(_EM_SYMBOL))
    assert missing == [], f"universe codes without EM symbol: {missing}"
