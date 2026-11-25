# -*- coding: utf-8 -*-
"""Read-only probe #4: how far back does sina per-contract daily history reach (expired contracts)? Is eastmoney list usable?"""
import re
import time
import warnings

warnings.filterwarnings("ignore")
import akshare as ak

res = {}
for code in ("M", "V", "AG", "CF"):
    ok = {}
    for yy in range(16, 26):
        for mm in ("01", "05", "09"):
            sym = f"{code}{yy}{mm}"
            try:
                df = ak.futures_zh_daily_sina(symbol=sym)
                ok[sym] = (len(df), str(df["date"].iloc[0])[:10], str(df["date"].iloc[-1])[:10]) if df is not None and len(df) else None
            except Exception:  # noqa: BLE001
                ok[sym] = None
            time.sleep(0.4)
    res[code] = ok
    got = [k for k, v in ok.items() if v]
    print(code, "available", len(got), "of", len(ok), "earliest:", got[0] if got else None, got[:3])
    print("   missing:", [k for k, v in ok.items() if not v])
try:
    t = ak.futures_hist_table_em()
    print("em table", t.shape, list(t.columns))
    print(t[t.iloc[:, 0].astype(str).str.contains("聚氯乙烯|豆粕")].head(8).to_string())
except Exception as e:  # noqa: BLE001
    print("em table ERR", repr(e)[:150])
