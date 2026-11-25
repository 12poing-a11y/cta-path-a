# -*- coding: utf-8 -*-
"""Read-only probe #3: why DCE returns 412; AKShare wrapper routes for DCE per-contract daily history."""
import re
import warnings

warnings.filterwarnings("ignore")
import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Referer": "http://www.dce.com.cn/"}
r = requests.get("http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html", headers=H, timeout=25)
txt = r.content.decode("utf-8", "ignore")
print("DCE 412 body (text only):", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt))[:300])

import akshare as ak

# candidate wrappers (names only if they exist)
names = [n for n in dir(ak) if re.search(r"futures.*(hist|daily|zh_daily|contract)", n)]
print("akshare futures wrappers:", names)

tests = [
    ("futures_zh_daily_sina V2005", lambda: ak.futures_zh_daily_sina(symbol="V2005")),
    ("futures_zh_daily_sina V1609", lambda: ak.futures_zh_daily_sina(symbol="V1609")),
    ("futures_zh_daily_sina M1709", lambda: ak.futures_zh_daily_sina(symbol="M1709")),
    ("futures_hist_em v2005", lambda: ak.futures_hist_em(symbol="聚氯乙烯2005", period="daily", start_date="20190101", end_date="20200630")),
]
for label, fn in tests:
    try:
        df = fn()
        print(label, "->", None if df is None else df.shape, None if df is None or not len(df) else (str(df.iloc[0].to_dict())[:200], str(df.iloc[-1].to_dict())[:200]))
    except Exception as e:  # noqa: BLE001
        print(label, "ERR", repr(e)[:160])
