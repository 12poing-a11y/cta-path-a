# -*- coding: utf-8 -*-
"""Warehouse receipt feed — exchange daily primary, Eastmoney inventory bypass.

Architecture (Path-A full universe):
  1. Primary: AKShare 交易所仓单日报
     - CZCE ``futures_warehouse_receipt_czce(date=YYYYMMDD)``
     - SHFE ``futures_shfe_warehouse_receipt(date=YYYYMMDD)``
     - DCE  ``futures_warehouse_receipt_dce(date=YYYYMMDD)``  (endpoint often flaky)
  2. Bypass: 东财 ``futures_inventory_em`` 库存时序（显式品种映射，禁止默认豆一）
  3. Merge: per-code prefer exchange total when present; else EM last; never invent.

Cache:
  .cache/warehouse/ex-{ex}-{YYYYMMDD}.json
  .cache/warehouse/em-inventory-{CODE}.json
  .cache/warehouse/em-inventory-latest.json
  .cache/warehouse/latest.json   # merged cross-section for desk / warrant_w
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "warehouse"

_EM_SYMBOL: dict[str, str] = {
    "MA": "甲醇",
    "V": "PVC",
    "EG": "乙二醇",
    "M": "豆粕",
    "FG": "玻璃",
    "EB": "苯乙烯",
    "TA": "PTA",
    "SA": "纯碱",
    "PP": "聚丙烯",
    "L": "塑料",
    "JD": "鸡蛋",
    "P": "棕榈",
    "RB": "螺纹钢",
    "FU": "燃油",
    "CF": "郑棉",
    "BU": "沥青",
    "RU": "橡胶",
    "AG": "沪银",
    "SP": "纸浆",
    "SR": "白糖",
    "AU": "沪金",
    "CU": "沪铜",
    "AL": "沪铝",
    "NI": "镍",
    "I": "铁矿石",
    "JM": "焦煤",
    "SS": "不锈钢",
}

# SHFE receipt table keys → Path-A code (厂库/仓库合并时取同 code 求和).
# 2025-11-18 起 HTML 表题为「螺纹钢(仓库)」等，解析后常规范成「螺纹钢仓库」。
_SHFE_NAME_TO_CODE: dict[str, str] = {
    "螺纹钢": "RB",
    "螺纹钢仓库": "RB",
    "螺纹钢厂库": "RB",
    "螺纹钢(仓库)": "RB",
    "螺纹钢(厂库)": "RB",
    "热轧卷板": "RB",  # not Path-A primary; skipped unless mapped intentionally
    "天然橡胶": "RU",
    "纸浆": "SP",
    "纸浆仓库": "SP",
    "纸浆厂库": "SP",
    "纸浆(仓库)": "SP",
    "纸浆(厂库)": "SP",
    "白银": "AG",
    "黄金": "AU",
    "铜": "CU",
    "铝": "AL",
    "镍": "NI",
    "不锈钢": "SS",
    "不锈钢仓库": "SS",
    "不锈钢厂库": "SS",
    "不锈钢(仓库)": "SS",
    "不锈钢(厂库)": "SS",
    "燃料油": "FU",
    "沥青": "BU",
    "石油沥青": "BU",
    "石油沥青仓库": "BU",
    "石油沥青厂库": "BU",
    "石油沥青(仓库)": "BU",
    "石油沥青(厂库)": "BU",
}

# 上期所自 2025-11-18 起不再提供 {date}dailystock.dat（404），改 HTML 分表。
_SHFE_HTML_SINCE = "20251118"
_SHFE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_CZCE_KEY_ALIASES = {"PTA": "TA"}


def _universe_codes(root: Path | None = None) -> list[str]:
    root = root or ROOT
    try:
        uni = json.loads((root / "universe.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return sorted(_EM_SYMBOL)
    codes = []
    for row in uni.get("symbols") or []:
        if isinstance(row, dict) and row.get("code"):
            codes.append(str(row["code"]).upper())
    return codes or sorted(_EM_SYMBOL)


def _ymd(day: str | date | None = None) -> str:
    if day is None:
        return date.today().strftime("%Y%m%d")
    if isinstance(day, date):
        return day.strftime("%Y%m%d")
    s = str(day).replace("-", "")[:8]
    return s


def _to_iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        try:
            return str(v.isoformat())[:10]
        except Exception:
            pass
    s = str(v).strip()
    return s[:10] if len(s) >= 10 else s or None


def _num(v: Any) -> float | None:
    try:
        if v is None:
            return None
        s = str(v).replace(",", "").strip()
        if s in ("", "-", "—", "nan", "None"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ----- Eastmoney inventory bypass -----


def fetch_em_inventory_series(code: str, *, sleep_s: float = 0.35) -> dict[str, Any]:
    code = str(code or "").upper()
    symbol = _EM_SYMBOL.get(code)
    out: dict[str, Any] = {
        "ok": False,
        "code": code,
        "em_symbol": symbol,
        "source": "eastmoney.futures_inventory_em",
        "rows": [],
        "error": None,
    }
    if not symbol:
        out["error"] = "no_em_symbol_map"
        return out
    try:
        import akshare as ak

        df = ak.futures_inventory_em(symbol=symbol)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}:{exc}"
        return out
    finally:
        if sleep_s > 0:
            time.sleep(sleep_s)
    if df is None or getattr(df, "empty", True):
        out["error"] = "empty"
        return out
    rows = []
    for rec in df.to_dict("records"):
        day = _to_iso(rec.get("日期") or rec.get("date"))
        inv = _num(rec.get("库存"))
        chg = _num(rec.get("增减"))
        if not day or inv is None:
            continue
        rows.append({"date": day, "inventory": inv, "change": chg})
    if not rows:
        out["error"] = "no_parsed_rows"
        return out
    out.update(
        {
            "ok": True,
            "rows": rows,
            "n": len(rows),
            "start": rows[0]["date"],
            "end": rows[-1]["date"],
            "last": rows[-1],
        }
    )
    return out


def pull_em_inventory_universe(
    root: Path | None = None,
    *,
    codes: list[str] | None = None,
    sleep_s: float = 0.35,
) -> dict[str, Any]:
    root = Path(root or ROOT)
    codes = [c.upper() for c in (codes or _universe_codes(root))]
    ok_codes: list[str] = []
    missing: dict[str, str] = {}
    latest_rows: list[dict[str, Any]] = []
    for code in codes:
        pack = fetch_em_inventory_series(code, sleep_s=sleep_s)
        _write_json(
            CACHE / f"em-inventory-{code}.json",
            {**pack, "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        )
        if pack.get("ok"):
            ok_codes.append(code)
            last = pack.get("last") or {}
            latest_rows.append(
                {
                    "code": code,
                    "em_symbol": pack.get("em_symbol"),
                    "date": last.get("date"),
                    "inventory": last.get("inventory"),
                    "change": last.get("change"),
                    "n": pack.get("n"),
                    "start": pack.get("start"),
                    "end": pack.get("end"),
                }
            )
            print(
                f"[warehouse:em] {code} ok n={pack.get('n')} "
                f"end={pack.get('end')} inv={last.get('inventory')}"
            )
        else:
            missing[code] = str(pack.get("error") or "fail")
            print(f"[warehouse:em] {code} FAIL {pack.get('error')}")
    summary = {
        "ok": len(missing) == 0,
        "asof": str(date.today()),
        "source": "eastmoney.futures_inventory_em",
        "role": "bypass",
        "universe_n": len(codes),
        "ok_n": len(ok_codes),
        "ok_codes": ok_codes,
        "missing": missing,
        "latest": latest_rows,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_json(CACHE / "em-inventory-latest.json", summary)
    return summary


# ----- Exchange warehouse daily (primary) -----


def _czce_totals(payload: dict) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    qty_keys = ("仓单数量", "仓单数量(完税)", "仓单量", "注册仓单")
    for key, df in (payload or {}).items():
        code = _CZCE_KEY_ALIASES.get(str(key).upper(), str(key).upper())
        if not hasattr(df, "to_dict"):
            continue
        total = None
        chg = None
        for rec in df.to_dict("records"):
            mark = str(rec.get("仓库编号") or rec.get("仓库简称") or "")
            if "总计" not in mark:
                continue
            for qk in qty_keys:
                total = _num(rec.get(qk))
                if total is not None:
                    break
            # 完税+保税（若分列且总计行有保税）
            bonded = _num(rec.get("仓单数量(保税)"))
            if total is not None and bonded is not None:
                total = float(total) + float(bonded)
            chg = _num(rec.get("当日增减"))
            break
        if total is None:
            continue
        out[code] = {"receipt": total, "change": chg}
    return out


def _normalize_shfe_var_name(raw: str) -> str:
    text = str(raw or "").strip()
    return text.replace("(仓库)", "仓库").replace("(厂库)", "厂库")


def _fetch_shfe_html(ymd: str) -> dict[str, Any]:
    """Parse SHFE stockdata HTML (post-2025-11-18). Keys = variety table titles."""
    import pandas as pd
    import requests
    from bs4 import BeautifulSoup

    ymd = _ymd(ymd)
    url = (
        f"https://www.shfe.com.cn/data/tradedata/future/stockdata/"
        f"dailystock_{ymd}/ZH/all.html"
    )
    headers = {"User-Agent": _SHFE_UA, "Referer": "https://www.shfe.com.cn/"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, features="lxml")
    column_map = {
        "地区": "REGNAME",
        "仓库": "WHABBRNAME",
        "厂库": "WHABBRNAME",
        "交割仓库": "WHABBRNAME",
        "期货": "WRTWGHTS",
        "本日数量": "WRTWGHTS",
        "增减": "WRTCHANGE",
    }
    big_dict: dict[str, Any] = {}
    for table in soup.find_all("table"):
        header = [th.get_text(strip=True) for th in table.find_all("th")]
        title_tr = table.find("tr", class_="special_row_type")
        if not header or title_tr is None or title_tr.td is None:
            continue
        columns = [column_map.get(item, item) for item in header]
        var_name = _normalize_shfe_var_name(title_tr.td.get_text(strip=True))
        spans: dict[int, tuple[str, int]] = {}
        rows: list[dict[str, Any]] = []
        for tr in table.find_all("tr"):
            if tr is title_tr or tr.find("th") is not None:
                continue
            cells = list(tr.find_all("td"))
            row: list[str] = []
            while len(row) < len(columns):
                col = len(row)
                if spans.get(col, ("", 0))[1] > 0:
                    text, remaining = spans[col]
                    spans[col] = (text, remaining - 1)
                    row.append(text)
                    continue
                if not cells:
                    break
                td = cells.pop(0)
                text = td.get_text(strip=True)
                rowspan = int(td.get("rowspan", 1) or 1)
                if rowspan > 1:
                    spans[col] = (text, rowspan - 1)
                colspan = int(td.get("colspan", 1) or 1)
                row.extend([""] * (colspan - 1) + [text])
            if len(row) != len(columns):
                continue
            item = dict(zip(columns, row))
            reg = str(item.get("REGNAME") or "")
            wh = str(item.get("WHABBRNAME") or "")
            if reg.endswith("总计") or wh.endswith("总计"):
                item["WHABBRNAME"] = reg + wh
                item["REGNAME"] = ""
                item["ROWSTATUS"] = "2"
            elif "合计" in (reg, wh):
                item["ROWSTATUS"] = "1"
            else:
                item["ROWSTATUS"] = "0"
            rows.append(item)
        if not rows:
            continue
        temp_df = pd.DataFrame(rows)
        temp_df["VARNAME"] = var_name
        keep = ["VARNAME", "REGNAME", "WHABBRNAME", "WRTWGHTS", "WRTCHANGE", "ROWSTATUS"]
        for col in keep:
            if col not in temp_df.columns:
                temp_df[col] = None
        temp_df = temp_df[keep]
        temp_df["WRTWGHTS"] = pd.to_numeric(temp_df["WRTWGHTS"], errors="coerce")
        temp_df["WRTCHANGE"] = pd.to_numeric(temp_df["WRTCHANGE"], errors="coerce")
        # Merge 仓库/厂库 tables that map to the same Path-A code under one key.
        big_dict[var_name] = temp_df
    if not big_dict:
        raise ValueError(f"shfe_html_empty:{ymd}")
    return big_dict


def _fetch_shfe_payload(ymd: str) -> dict[str, Any]:
    """SHFE warehouse payload: new HTML after 2025-11-18, else akshare/.dat."""
    ymd = _ymd(ymd)
    if ymd >= _SHFE_HTML_SINCE:
        return _fetch_shfe_html(ymd)
    import akshare as ak

    try:
        payload = ak.futures_shfe_warehouse_receipt(date=ymd)
        if isinstance(payload, dict) and payload:
            return payload
    except Exception:
        pass
    # Fallback: some mirrors still serve .dat briefly after cutover.
    return _fetch_shfe_html(ymd)


def _shfe_totals(payload: dict) -> dict[str, dict[str, float | None]]:
    """Sum WRTWGHTS across 仓库/厂库 tables mapped to the same Path-A code."""
    acc: dict[str, dict[str, float]] = {}
    for name, df in (payload or {}).items():
        code = _SHFE_NAME_TO_CODE.get(str(name)) or _SHFE_NAME_TO_CODE.get(
            _normalize_shfe_var_name(str(name))
        )
        if not code or not hasattr(df, "to_dict"):
            continue
        # Prefer explicit total/合计 row; else sum positive warehouse rows.
        total = None
        chg = None
        rows = df.to_dict("records")
        for rec in rows:
            label = str(rec.get("WHABBRNAME") or rec.get("REGNAME") or "")
            if any(t in label for t in ("总计", "合计", "小计")):
                # 小计太多；只要含总计/合计
                if "总计" in label or "合计" in label:
                    total = _num(rec.get("WRTWGHTS"))
                    chg = _num(rec.get("WRTCHANGE"))
                    break
        if total is None:
            s = 0.0
            c = 0.0
            n = 0
            for rec in rows:
                label = str(rec.get("WHABBRNAME") or "")
                if "小计" in label or "总计" in label or "合计" in label:
                    continue
                w = _num(rec.get("WRTWGHTS"))
                if w is None:
                    continue
                s += w
                dc = _num(rec.get("WRTCHANGE"))
                if dc is not None:
                    c += dc
                n += 1
            if n:
                total, chg = s, c
        if total is None:
            continue
        slot = acc.setdefault(code, {"receipt": 0.0, "change": 0.0})
        slot["receipt"] += float(total)
        if chg is not None:
            slot["change"] += float(chg)
    return {
        k: {"receipt": v["receipt"], "change": v.get("change")}
        for k, v in acc.items()
    }


def _dce_totals(df_or_dict: Any) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    if df_or_dict is None:
        return out
    if isinstance(df_or_dict, dict):
        # newer akshare sometimes returns dict
        for key, df in df_or_dict.items():
            code = str(key).upper()
            if not hasattr(df, "to_dict"):
                continue
            # best-effort: last 总计
            for rec in df.to_dict("records"):
                mark = " ".join(str(rec.get(c) or "") for c in rec)
                if "总计" in mark or "合计" in mark:
                    # try common column names
                    for qty_k, chg_k in (
                        ("仓单数量", "当日增减"),
                        ("WRTWGHTS", "WRTCHANGE"),
                        ("今日仓单量", "增减"),
                    ):
                        q = _num(rec.get(qty_k))
                        if q is not None:
                            out[code] = {"receipt": q, "change": _num(rec.get(chg_k))}
                            break
        return out
    if not hasattr(df_or_dict, "to_dict"):
        return out
    cols = list(df_or_dict.columns)
    # Typical DCE columns vary; look for variety + qty
    for rec in df_or_dict.to_dict("records"):
        code = None
        for k in ("品种", "品种代码", "VARNAME", "variety"):
            if k in rec and rec.get(k):
                raw = str(rec.get(k)).upper()
                # may be Chinese — skip unmapped Chinese here; EM covers DCE bypass
                if raw.isalpha() and 1 <= len(raw) <= 3:
                    code = raw
                break
        if not code:
            continue
        qty = None
        chg = None
        for qty_k in ("仓单数量", "今日仓单量", "仓单量", "WRTWGHTS"):
            qty = _num(rec.get(qty_k))
            if qty is not None:
                break
        for chg_k in ("当日增减", "增减", "WRTCHANGE"):
            chg = _num(rec.get(chg_k))
            if chg is not None:
                break
        if qty is None:
            continue
        out[code] = {"receipt": qty, "change": chg}
    return out


def fetch_exchange_day(ymd: str, *, sleep_s: float = 0.4) -> dict[str, Any]:
    """Pull one session's exchange warehouse prints. Soft per exchange."""
    ymd = _ymd(ymd)
    import akshare as ak

    exchanges: dict[str, Any] = {}
    # CZCE
    try:
        czce = ak.futures_warehouse_receipt_czce(date=ymd)
        totals = _czce_totals(czce if isinstance(czce, dict) else {})
        exchanges["CZCE"] = {
            "ok": bool(totals),
            "n_products": len(totals),
            "totals": totals,
            "error": None if totals else "empty_totals",
        }
        print(f"[warehouse:ex] CZCE {ymd} products={len(totals)}")
    except Exception as exc:  # noqa: BLE001
        exchanges["CZCE"] = {"ok": False, "n_products": 0, "totals": {}, "error": f"{type(exc).__name__}:{exc}"}
        print(f"[warehouse:ex] CZCE {ymd} FAIL {exchanges['CZCE']['error']}")
    time.sleep(sleep_s)
    # SHFE — own HTML path after 2025-11-18 (akshare .dat 404 → JSONDecodeError).
    try:
        shfe = _fetch_shfe_payload(ymd)
        totals = _shfe_totals(shfe if isinstance(shfe, dict) else {})
        exchanges["SHFE"] = {
            "ok": bool(totals),
            "n_products": len(totals),
            "totals": totals,
            "error": None if totals else "empty_totals",
            "transport": "html" if ymd >= _SHFE_HTML_SINCE else "dat/akshare",
        }
        print(f"[warehouse:ex] SHFE {ymd} products={len(totals)}")
    except Exception as exc:  # noqa: BLE001
        exchanges["SHFE"] = {
            "ok": False,
            "n_products": 0,
            "totals": {},
            "error": f"{type(exc).__name__}:{exc}",
        }
        print(f"[warehouse:ex] SHFE {ymd} FAIL {exchanges['SHFE']['error']}")
    time.sleep(sleep_s)
    # DCE — exchange API often HTTP 412 (瑞数反爬); EM inventory remains bypass.
    try:
        dce = ak.futures_warehouse_receipt_dce(date=ymd)
        totals = _dce_totals(dce)
        exchanges["DCE"] = {
            "ok": bool(totals),
            "n_products": len(totals),
            "totals": totals,
            "error": None if totals else "empty_totals",
        }
        print(f"[warehouse:ex] DCE {ymd} products={len(totals)}")
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}:{exc}"
        if "412" in err or "JSONDecodeError" in err:
            err = f"{err} (瑞数/反爬常见；东财库存旁路顶上)"
        exchanges["DCE"] = {"ok": False, "n_products": 0, "totals": {}, "error": err}
        print(f"[warehouse:ex] DCE {ymd} FAIL {exchanges['DCE']['error']}")

    by_code: dict[str, dict[str, Any]] = {}
    for ex, pack in exchanges.items():
        for code, row in (pack.get("totals") or {}).items():
            by_code[code] = {
                "code": code,
                "receipt": row.get("receipt"),
                "change": row.get("change"),
                "exchange": ex,
                "source": f"exchange.{ex.lower()}",
                "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
            }
    payload = {
        "ok": any(p.get("ok") for p in exchanges.values()),
        "ymd": ymd,
        "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
        "role": "primary",
        "exchanges": {
            k: {
                "ok": v.get("ok"),
                "n_products": v.get("n_products"),
                "error": v.get("error"),
                "codes": sorted((v.get("totals") or {}).keys()),
            }
            for k, v in exchanges.items()
        },
        "by_code": by_code,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_json(CACHE / f"ex-day-{ymd}.json", payload)
    return payload


def _recent_ymds(n: int = 5) -> list[str]:
    out = []
    d = date.today()
    for _ in range(n * 2):
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
            if len(out) >= n:
                break
        d -= timedelta(days=1)
    return out


def merge_latest(
    root: Path | None = None,
    *,
    ymd: str | None = None,
    refresh_em: bool = True,
) -> dict[str, Any]:
    """Primary exchange day + EM bypass → ``latest.json`` for universe codes."""
    root = Path(root or ROOT)
    codes = _universe_codes(root)
    ymds = [ _ymd(ymd) ] if ymd else _recent_ymds(5)
    ex_pack = None
    tried = []
    for day in ymds:
        tried.append(day)
        pack = fetch_exchange_day(day)
        if pack.get("ok") and pack.get("by_code"):
            ex_pack = pack
            break
    if refresh_em:
        em_sum = pull_em_inventory_universe(root, codes=codes)
    else:
        em_path = CACHE / "em-inventory-latest.json"
        try:
            em_sum = json.loads(em_path.read_text(encoding="utf-8")) if em_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            em_sum = {}

    em_by = {
        str(r.get("code")).upper(): r
        for r in (em_sum.get("latest") or [])
        if r.get("code")
    }
    ex_by = (ex_pack or {}).get("by_code") or {}

    rows = []
    for code in codes:
        if code in ex_by and ex_by[code].get("receipt") is not None:
            r = ex_by[code]
            rows.append(
                {
                    "code": code,
                    "date": r.get("date"),
                    "receipt": r.get("receipt"),
                    "change": r.get("change"),
                    "source": r.get("source"),
                    "exchange": r.get("exchange"),
                    "bypass": False,
                }
            )
        elif code in em_by and em_by[code].get("inventory") is not None:
            r = em_by[code]
            rows.append(
                {
                    "code": code,
                    "date": r.get("date"),
                    "receipt": r.get("inventory"),
                    "change": r.get("change"),
                    "source": "eastmoney.futures_inventory_em",
                    "exchange": None,
                    "bypass": True,
                }
            )
        else:
            rows.append(
                {
                    "code": code,
                    "date": None,
                    "receipt": None,
                    "change": None,
                    "source": None,
                    "exchange": None,
                    "bypass": False,
                    "missing": True,
                }
            )

    primary_n = sum(1 for r in rows if r.get("source") and not r.get("bypass") and not r.get("missing"))
    bypass_n = sum(1 for r in rows if r.get("bypass"))
    missing_n = sum(1 for r in rows if r.get("missing") or r.get("receipt") is None)
    summary = {
        "ok": primary_n + bypass_n > 0,
        "asof": str(date.today()),
        "architecture": "exchange_warehouse_daily_primary + eastmoney_inventory_bypass",
        "exchange_ymd": (ex_pack or {}).get("ymd"),
        "exchange_tried": tried,
        "exchange_status": (ex_pack or {}).get("exchanges"),
        "universe_n": len(codes),
        "primary_n": primary_n,
        "bypass_n": bypass_n,
        "missing_n": missing_n,
        "rows": rows,
        "note": (
            "正式仓单优先交易所日报（AKShare 三所）；"
            "东财库存仅旁路补洞。缺数保持 null，不编造。"
        ),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_json(CACHE / "latest.json", summary)
    print(
        f"[warehouse] merge primary={primary_n} bypass={bypass_n} "
        f"missing={missing_n} ex_ymd={summary.get('exchange_ymd')}"
    )
    return summary


def refresh_warehouse(root: Path | None = None, *, ymd: str | None = None) -> dict[str, Any]:
    """Entry for daily_update / CLI: exchange primary + EM bypass + merge."""
    return merge_latest(root, ymd=ymd, refresh_em=True)


if __name__ == "__main__":
    import sys

    day = sys.argv[1] if len(sys.argv) > 1 else None
    refresh_warehouse(ROOT, ymd=day)
