# -*- coding: utf-8 -*-
"""Read-only probe #2: older-year availability (SHFE/CZCE official), DCE access routes, sina exact-contract history for expired contracts."""
import json
import re
import warnings

warnings.filterwarnings("ignore")
import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def get(u, **kw):
    try:
        r = requests.get(u, headers=H, timeout=25, **kw)
        return r
    except Exception as e:  # noqa: BLE001
        return repr(e)[:120]


print("== SHFE official, older days")
for d in ("20160104", "20170103", "20180102", "20190102", "20200102", "20211231", "20221230"):
    r = get(f"https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{d}.dat")
    if isinstance(r, str):
        print(d, r)
    else:
        n = 0
        if r.status_code == 200:
            try:
                n = len(r.json()["o_curinstrument"])
            except Exception as e:  # noqa: BLE001
                n = f"parse-err {e!r}"[:60]
        print(d, r.status_code, len(r.content), "rows", n)

print("== CZCE official, older days (gbk?)")
for d in ("20160104", "20171229", "20190102", "20220104"):
    y = d[:4]
    r = get(f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{y}/{d}/FutureDataDaily.txt")
    if isinstance(r, str):
        print(d, r)
        continue
    enc = "utf-8"
    try:
        txt = r.content.decode("utf-8")
    except UnicodeDecodeError:
        txt = r.content.decode("gbk", "ignore")
        enc = "gbk"
    print(d, r.status_code, len(r.content), enc, "|", txt[:80].replace("\n", " ").replace("\t", " "))
    lines = [l for l in txt.splitlines() if l.strip().startswith(("CF", "SR", "TA"))]
    print("   sample:", lines[:2])

print("== DCE routes")
s = requests.Session()
s.headers.update(H)
r = s.get("http://www.dce.com.cn/dalianshangpin/xqsj/tjsj26/rtj/rxq/index.html", timeout=25)
print("dce page", r.status_code, len(r.content))
for u, data in (
    ("http://www.dce.com.cn/publicweb/quotesdata/exportDayQuotesChData.html", {"dayQuotes.variety": "all", "dayQuotes.trade_type": "0", "year": "2024", "month": "0", "day": "02", "exportFlag": "txt"}),
    ("http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html", {"dayQuotes.variety": "all", "dayQuotes.trade_type": "0", "year": "2024", "month": "0", "day": "02"}),
):
    try:
        rr = s.post(u, data=data, timeout=25)
        print("POST", u.split("/")[-1], rr.status_code, len(rr.content), rr.content[:100])
    except Exception as e:  # noqa: BLE001
        print("POST", u, repr(e)[:100])
for u, body in (
    ("https://www.dce.com.cn/dcereport/publicweb/dailystat/dayQuotes", {"tradeDate": "20240102", "varietyId": "all", "tradeType": "1", "lang": "zh"}),
):
    try:
        rr = s.post(u, json=body, timeout=25)
        print("POST json", rr.status_code, len(rr.content), rr.content[:160])
    except Exception as e:  # noqa: BLE001
        print("POST json", repr(e)[:100])

print("== sina exact-contract history for expired contracts")
for sym in ("V1605", "M1709", "I1809", "JM2005", "EG2005", "EB2005", "L1905", "P1801", "AG1612", "CF1705", "MA1705"):
    u = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.getDailyKLine?symbol={sym}"
    r = get(u)
    if isinstance(r, str):
        print(sym, r)
        continue
    m = re.search(r"\((\[.*\])\)", r.text, re.S)
    if not m:
        print(sym, r.status_code, "no-json", r.text[:80])
        continue
    arr = json.loads(m.group(1))
    print(sym, r.status_code, "bars", len(arr), arr[0] if arr else None, arr[-1] if arr else None)
