# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd

from warehouse_receipt import _normalize_shfe_var_name, _shfe_totals


def test_normalize_shfe_var_name():
    assert _normalize_shfe_var_name("螺纹钢(仓库)") == "螺纹钢仓库"
    assert _normalize_shfe_var_name("石油沥青(厂库)") == "石油沥青厂库"


def test_shfe_totals_sums_warehouse_and_factory_tables():
    wh = pd.DataFrame(
        [
            {
                "VARNAME": "螺纹钢仓库",
                "REGNAME": "江苏",
                "WHABBRNAME": "某库",
                "WRTWGHTS": 100.0,
                "WRTCHANGE": 1.0,
                "ROWSTATUS": "0",
            },
            {
                "VARNAME": "螺纹钢仓库",
                "REGNAME": "",
                "WHABBRNAME": "总计",
                "WRTWGHTS": 100.0,
                "WRTCHANGE": 1.0,
                "ROWSTATUS": "2",
            },
        ]
    )
    fac = pd.DataFrame(
        [
            {
                "VARNAME": "螺纹钢厂库",
                "REGNAME": "",
                "WHABBRNAME": "总计",
                "WRTWGHTS": 40.0,
                "WRTCHANGE": -2.0,
                "ROWSTATUS": "2",
            }
        ]
    )
    out = _shfe_totals({"螺纹钢仓库": wh, "螺纹钢厂库": fac})
    assert out["RB"]["receipt"] == 140.0
    assert out["RB"]["change"] == -1.0
