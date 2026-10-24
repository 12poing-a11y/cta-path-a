# -*- coding: utf-8 -*-
"""Member rankings — public portals first, exchange prints as soft underlay.

**Unified seat path (Path-A 20):**
1. Eastmoney ``RPT_FUTU_DAILYPOSITION`` → ``em-YYYYMMDD.json`` (and DCE slice)
2. Sina ``futures_hold_pos_sina`` fills any code still thin / missing
3. SHFE/CZCE txt + DCE zip are optional densifiers (calendar / bonus), never
   required for observation completeness

Bars still use 新浪+腾讯 (see ``market_data``); Tencent has no top-20 seat API.
``daily_update`` / weekly backfill require full observation coverage via 1–2.

Seat books use three fixed name lists. Other top-20 members are ignored.
The ranking prints 中信建投 for the retail seat often called 中建投,
and 东证期货 for 东证融汇.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
_CHANGES: dict | None = None
_SEATS: dict | None = None

# 4 foreign-owned futures brokers.
_FOREIGN = ("摩根大通", "摩根士丹利", "瑞银", "高盛")
# 5 institutional seats. 东证 covers 东证期货 and 东证融汇.
# 中信期货 must not match 中信建投.
_INST = ("中信期货", "国泰君安", "华泰", "永安", "东证融汇", "东证")
# 5 retail seats. Rankings print 中信建投; 中建投 is the same seat.
_HOLDER = ("东方财富", "东财", "平安", "方正中期", "徽商", "中信建投", "中建投")

# Path-A DCE products plus common neighbors; narrows akshare download when supported.
_DCE_VARS = (
    "A",
    "B",
    "C",
    "CS",
    "EB",
    "EG",
    "FB",
    "I",
    "J",
    "JD",
    "JM",
    "L",
    "LG",
    "LH",
    "M",
    "P",
    "PG",
    "PP",
    "RR",
    "V",
    "Y",
)


def clean_member_name(name: str) -> str:
    s = str(name or "").strip()
    for tag in ("（代客）", "(代客)", "（自营）", "(自营)"):
        s = s.replace(tag, "")
    return s.strip()


def seat_kind(name: str) -> str | None:
    """foreign, inst, holder, or None when the name is outside the three lists."""
    cleaned = clean_member_name(name)
    if not cleaned:
        return None
    for stem in _FOREIGN:
        if stem in cleaned:
            return "foreign"
    for stem in _HOLDER:
        if stem in cleaned:
            return "holder"
    for stem in _INST:
        if stem in cleaned:
            return "inst"
    return None


def _num(text) -> float | None:
    s = str(text or "").replace(",", "").replace("+", "").strip()
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _cache_path(kind: str, ymd: str) -> Path:
    return ROOT / ".cache" / "member" / f"{kind}-{ymd}.txt"


def _get(url: str, path: Path) -> bytes | None:
    if path.exists() and path.stat().st_size > 200:
        return path.read_bytes()
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    except Exception:
        return None
    if resp.status_code != 200 or len(resp.content) < 200:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    except Exception:
        pass
    return resp.content


def _shfe_nets(ymd: str) -> dict[str, float]:
    raw = _get(
        f"https://www.shfe.com.cn/data/tradedata/future/dailydata/pm{ymd}.dat",
        _cache_path("shfe", ymd),
    )
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    by_inst: dict[str, list] = {}
    for row in payload.get("o_cursor") or []:
        iid = str(row.get("INSTRUMENTID") or "")
        if not iid or iid.lower().endswith("all"):
            continue
        by_inst.setdefault(iid, []).append(row)
    products: dict[str, list] = {}
    for iid, rows in by_inst.items():
        code = "".join(ch for ch in iid if ch.isalpha()).upper()
        products.setdefault(code, []).append(rows)
    out = {}
    for code, insts in products.items():
        best = None
        best_oi = -1.0
        for rows in insts:
            ranked = []
            total = 0.0
            for row in rows:
                try:
                    rank = int(row.get("RANK") or 0)
                except (TypeError, ValueError):
                    continue
                if rank == 999:
                    total = float(row.get("CJ2") or 0)
                elif 1 <= rank <= 20:
                    ranked.append(row)
            if total <= 0 and ranked:
                total = sum(float(r.get("CJ2") or 0) for r in ranked)
            if len(ranked) >= 15 and total > best_oi:
                best_oi = total
                best = ranked
        if best:
            long_ = sum(float(r.get("CJ2") or 0) for r in best)
            short_ = sum(float(r.get("CJ3") or 0) for r in best)
            out[code] = long_ - short_
    return out


def _czce_nets(ymd: str) -> dict[str, float]:
    year = ymd[:4]
    raw = _get(
        f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{ymd}/FutureDataHolding.txt",
        _cache_path("czce", ymd),
    )
    if not raw:
        return {}
    text = None
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if not text or "品种" not in text:
        return {}
    out = {}
    for part in re.split(r"品种[：:]", text)[1:]:
        head = part[:40]
        m = re.search(
            r"(PTA|AP|CF|CJ|CY|FG|MA|OI|PF|PK|PL|PR|PX|RM|RS|SA|SF|SH|SM|SR|UR|TA)",
            head,
        )
        if not m:
            continue
        code = "TA" if m.group(1) == "PTA" else m.group(1)
        long_ = short_ = 0.0
        n = 0
        for line in part.splitlines():
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            if not cells or not cells[0].isdigit():
                continue
            rank = int(cells[0])
            if not 1 <= rank <= 20 or len(cells) < 10:
                continue
            lv, sv = _num(cells[5]), _num(cells[8])
            if lv is None or sv is None:
                continue
            long_ += lv
            short_ += sv
            n += 1
        if n >= 15:
            out[code] = long_ - short_
    return out


def _empty_seat() -> dict[str, float]:
    return {"inst": 0.0, "foreign": 0.0, "holder": 0.0}


def _add_leg(book: dict[str, float], name: str, qty: float, sign: float) -> None:
    kind = seat_kind(name)
    if not kind or qty is None:
        return
    book[kind] += sign * float(qty)


def _shfe_seats(ymd: str) -> dict[str, dict]:
    raw = _get(
        f"https://www.shfe.com.cn/data/tradedata/future/dailydata/pm{ymd}.dat",
        _cache_path("shfe", ymd),
    )
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    by_inst: dict[str, list] = {}
    for row in payload.get("o_cursor") or []:
        iid = str(row.get("INSTRUMENTID") or "")
        if not iid or iid.lower().endswith("all"):
            continue
        by_inst.setdefault(iid, []).append(row)
    products: dict[str, list] = {}
    for iid, rows in by_inst.items():
        code = "".join(ch for ch in iid if ch.isalpha()).upper()
        products.setdefault(code, []).append(rows)
    out = {}
    for code, insts in products.items():
        best = None
        best_oi = -1.0
        for rows in insts:
            ranked = []
            total = 0.0
            for row in rows:
                try:
                    rank = int(row.get("RANK") or 0)
                except (TypeError, ValueError):
                    continue
                if rank == 999:
                    total = float(row.get("CJ2") or 0)
                elif 1 <= rank <= 20:
                    ranked.append(row)
            if total <= 0 and ranked:
                total = sum(float(r.get("CJ2") or 0) for r in ranked)
            if len(ranked) >= 15 and total > best_oi:
                best_oi = total
                best = ranked
        if not best:
            continue
        book = _empty_seat()
        for row in best:
            _add_leg(book, str(row.get("PARTICIPANTABBR2") or ""), float(row.get("CJ2") or 0), 1.0)
            _add_leg(book, str(row.get("PARTICIPANTABBR3") or ""), float(row.get("CJ3") or 0), -1.0)
        out[code] = book
    return out


def _czce_text(raw: bytes) -> str | None:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return None


def _czce_seats(ymd: str) -> dict[str, dict]:
    year = ymd[:4]
    raw = _get(
        f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{ymd}/FutureDataHolding.txt",
        _cache_path("czce", ymd),
    )
    if not raw:
        return {}
    text = _czce_text(raw)
    if not text or "品种" not in text:
        return {}
    out = {}
    for part in re.split(r"品种[：:]", text)[1:]:
        # Product table only. Later 合约 blocks repeat the same ranks per month.
        part = part.split("合约")[0]
        head = part[:40]
        m = re.search(
            r"(PTA|AP|CF|CJ|CY|FG|MA|OI|PF|PK|PL|PR|PX|RM|RS|SA|SF|SH|SM|SR|UR|TA)",
            head,
        )
        if not m:
            continue
        code = "TA" if m.group(1) == "PTA" else m.group(1)
        book = _empty_seat()
        n = 0
        for line in part.splitlines():
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            if not cells or not cells[0].isdigit():
                continue
            rank = int(cells[0])
            if not 1 <= rank <= 20 or len(cells) < 9:
                continue
            _add_leg(book, cells[4] if len(cells) > 4 else "", _num(cells[5]), 1.0)
            _add_leg(book, cells[7] if len(cells) > 7 else "", _num(cells[8]), -1.0)
            n += 1
        if n >= 15:
            out[code] = book
    return out


def _dce_json_path(ymd: str) -> Path:
    return ROOT / ".cache" / "member" / f"dce-{ymd}.json"


def _product_code(symbol: str) -> str:
    return "".join(ch for ch in str(symbol or "") if ch.isalpha()).upper()


def _read_dce_json(ymd: str) -> dict[str, Any] | None:
    path = _dce_json_path(ymd)
    if not path.is_file() or path.stat().st_size < 50:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("products"), dict):
        return None
    return data


def _normalize_dce_ak(raw: dict) -> dict[str, dict[str, Any]]:
    """Collapse akshare contract frames into one dominant contract per variety."""
    best: dict[str, tuple[float, dict[str, Any]]] = {}
    for key, frame in (raw or {}).items():
        try:
            rows = frame.to_dict("records") if hasattr(frame, "to_dict") else []
        except Exception:
            rows = []
        if not rows:
            continue
        first = rows[0]
        symbol = str(first.get("symbol") or key or "").upper()
        variety = str(first.get("variety") or "").upper() or _product_code(symbol)
        if not variety:
            continue
        longs: list[list] = []
        shorts: list[list] = []
        long_total = 0.0
        short_total = 0.0
        n = 0
        for row in rows:
            long_name = clean_member_name(str(row.get("long_party_name") or ""))
            short_name = clean_member_name(str(row.get("short_party_name") or ""))
            long_qty = _num(row.get("long_open_interest"))
            short_qty = _num(row.get("short_open_interest"))
            if long_qty is None and short_qty is None:
                continue
            n += 1
            if long_name and long_qty is not None:
                longs.append([long_name, float(long_qty)])
                long_total += float(long_qty)
            if short_name and short_qty is not None:
                shorts.append([short_name, float(short_qty)])
                short_total += float(short_qty)
        if n < 15:
            continue
        score = long_total
        packed = {
            "contract": symbol or variety,
            "longs": longs,
            "shorts": shorts,
            "n": n,
            "long_total": long_total,
            "short_total": short_total,
        }
        prev = best.get(variety)
        if prev is None or score > prev[0]:
            best[variety] = (score, packed)
    return {code: packed for code, (_score, packed) in best.items()}


_EM_MARKETS = {
    "SHFE": "069001005",
    "DCE": "069001007",
    "CZCE": "069001008",
}
_EM_POS_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.eastmoney.com/futures/dl/data.html",
}


def _em_json_path(ymd: str) -> Path:
    return ROOT / ".cache" / "member" / f"em-{ymd}.json"


def _read_em_json(ymd: str) -> dict[str, Any] | None:
    path = _em_json_path(ymd)
    if not path.is_file() or path.stat().st_size < 50:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("products"), dict):
        return None
    return data


def _write_product_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _pack_legs(contract: str, longs: list[list], shorts: list[list]) -> dict[str, Any] | None:
    n = max(len(longs), len(shorts))
    if n < 15:
        return None
    return {
        "contract": str(contract or "").upper(),
        "longs": longs,
        "shorts": shorts,
        "n": n,
        "long_total": sum(float(x[1]) for x in longs),
        "short_total": sum(float(x[1]) for x in shorts),
    }


def _product_to_seat(row: dict[str, Any]) -> dict | None:
    if not isinstance(row, dict) or int(row.get("n") or 0) < 15:
        return None
    book = _empty_seat()
    for name, qty in row.get("longs") or []:
        _add_leg(book, str(name), _num(qty) or 0.0, 1.0)
    for name, qty in row.get("shorts") or []:
        _add_leg(book, str(name), _num(qty) or 0.0, -1.0)
    return book


def _universe_codes() -> list[str]:
    try:
        uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    out: list[str] = []
    for sym in uni.get("symbols") or []:
        code = str(sym.get("code") or "").upper()
        if code:
            out.append(code)
    return out


def _em_get(params: dict[str, Any]) -> list[dict]:
    try:
        resp = requests.get(_EM_POS_URL, params=params, headers=_EM_HEADERS, timeout=25)
        data = resp.json()
    except Exception:
        return []
    if not isinstance(data, dict) or not data.get("success"):
        return []
    rows = (data.get("result") or {}).get("data") or []
    return rows if isinstance(rows, list) else []


def _em_main_contracts(want: set[str] | None = None) -> dict[str, dict[str, str]]:
    """variety -> {exchange, contract} for Path-A universe (or want set)."""
    want = {c.upper() for c in (want or set(_universe_codes()) or _DCE_VARS)}
    rows = _em_get(
        {
            "reportName": "RPT_FUTU_POSITIONCODE",
            "columns": "TRADE_MARKET_CODE,TRADE_CODE,SECURITY_CODE,IS_MAINCODE",
            "filter": '(IS_MAINCODE="1")',
            "pageNumber": 1,
            "pageSize": 500,
            "source": "WEB",
            "client": "WEB",
        }
    )
    market_rev = {v: k for k, v in _EM_MARKETS.items()}
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        variety = str(row.get("TRADE_CODE") or "").upper()
        sec = str(row.get("SECURITY_CODE") or "").upper()
        exchange = market_rev.get(str(row.get("TRADE_MARKET_CODE") or ""))
        if variety in want and sec and exchange:
            out[variety] = {"exchange": exchange, "contract": sec}
    return out


def _em_contract_legs(sec: str, day_iso: str) -> tuple[list[list], list[list]] | None:
    """Top-20 long/short member legs for one contract on Eastmoney."""
    longs: list[list] = []
    shorts: list[list] = []
    for rank_col, qty_key, bucket in (
        ("LPRANK", "LONG_POSITION", longs),
        ("SPRANK", "SHORT_POSITION", shorts),
    ):
        filt = (
            f'(SECURITY_CODE="{sec}")(TRADE_DATE=\'{day_iso}\')'
            f'(TYPE="0")({rank_col}<>9999)'
        )
        rows = _em_get(
            {
                "reportName": "RPT_FUTU_DAILYPOSITION",
                "columns": "ALL",
                "filter": filt,
                "sortTypes": 1,
                "sortColumns": rank_col,
                "pageNumber": 1,
                "pageSize": 20,
                "source": "WEB",
                "client": "WEB",
            }
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = clean_member_name(
                str(row.get("MEMBER_NAME_ABBR") or row.get("ORG_NAME_ABBR_NEW") or "")
            )
            qty = _num(row.get(qty_key))
            if name and qty is not None:
                bucket.append([name, float(qty)])
    if len(longs) < 10 and len(shorts) < 10:
        return None
    return longs, shorts


def _sina_contract_legs(contract: str, ymd: str) -> tuple[list[list], list[list]] | None:
    """Top-20 long/short legs via akshare → 新浪成交持仓排名."""
    try:
        import akshare as ak
    except ImportError:
        return None
    longs: list[list] = []
    shorts: list[list] = []
    for symbol, bucket in (("多单持仓", longs), ("空单持仓", shorts)):
        try:
            frame = ak.futures_hold_pos_sina(symbol=symbol, contract=contract, date=ymd)
        except Exception:
            return None
        if frame is None or getattr(frame, "empty", True):
            return None
        name_col = next((c for c in frame.columns if "会员" in str(c)), None)
        qty_col = next(
            (c for c in frame.columns if ("多单" in str(c) or "空单" in str(c) or "持仓" in str(c)) and "增减" not in str(c)),
            None,
        )
        if not name_col or not qty_col:
            return None
        for _, row in frame.iterrows():
            name = clean_member_name(str(row.get(name_col) or ""))
            qty = _num(row.get(qty_col))
            if name and qty is not None:
                bucket.append([name, float(qty)])
    if len(longs) < 10 and len(shorts) < 10:
        return None
    return longs, shorts


def fetch_eastmoney_member_day(
    ymd: str, *, codes: list[str] | None = None, force: bool = False
) -> dict[str, Any] | None:
    """Pull SHFE/DCE/CZCE member ranks for Path-A codes into ``em-{ymd}.json``."""
    ymd = str(ymd or "").replace("-", "")
    if len(ymd) != 8 or not ymd.isdigit():
        return None
    want = [c.upper() for c in (codes or _universe_codes())]
    if not force:
        cached = _read_em_json(ymd)
        if cached:
            have = set((cached.get("products") or {}).keys())
            if want and all(c in have for c in want):
                return cached
            if not want and cached.get("products"):
                return cached
    day_iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    mains = _em_main_contracts(set(want) if want else None)
    if not mains:
        return _read_em_json(ymd)
    products: dict[str, dict[str, Any]] = dict((_read_em_json(ymd) or {}).get("products") or {})

    def _one(item: tuple[str, dict[str, str]]) -> tuple[str, dict[str, Any] | None]:
        variety, meta = item
        if not force and variety in products and int((products.get(variety) or {}).get("n") or 0) >= 15:
            return variety, products[variety]
        legs = _em_contract_legs(meta["contract"], day_iso)
        if not legs:
            return variety, None
        packed = _pack_legs(meta["contract"], legs[0], legs[1])
        if not packed:
            return variety, None
        packed["exchange"] = meta["exchange"]
        packed["source"] = "eastmoney.RPT_FUTU_DAILYPOSITION"
        return variety, packed

    targets = [(c, mains[c]) for c in (want or sorted(mains)) if c in mains]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for variety, packed in pool.map(_one, targets):
            if packed:
                products[variety] = packed
    if not products:
        return None
    payload = {
        "ymd": ymd,
        "source": "eastmoney.RPT_FUTU_DAILYPOSITION",
        "products": products,
    }
    _write_product_cache(_em_json_path(ymd), payload)
    # Keep dce-*.json in sync for desk paths that only read DCE cache.
    dce_products = {
        k: v for k, v in products.items() if str(v.get("exchange") or "") == "DCE"
    }
    if dce_products:
        _write_product_cache(
            _dce_json_path(ymd),
            {
                "ymd": ymd,
                "source": "eastmoney.RPT_FUTU_DAILYPOSITION",
                "products": dce_products,
            },
        )
    return payload


def _fetch_dce_eastmoney(ymd: str) -> dict[str, Any] | None:
    """DCE-only slice via the shared Eastmoney pull."""
    got = fetch_eastmoney_member_day(ymd, codes=list(_DCE_VARS), force=True)
    if not got:
        return None
    products = {
        k: v
        for k, v in (got.get("products") or {}).items()
        if str(v.get("exchange") or "DCE") == "DCE" or k in _DCE_VARS
    }
    if not products:
        return None
    return {
        "ymd": ymd,
        "source": "eastmoney.RPT_FUTU_DAILYPOSITION",
        "products": products,
    }


def _fetch_dce_akshare(ymd: str) -> dict[str, Any] | None:
    try:
        import akshare as ak
    except ImportError:
        return None
    raw = None
    try:
        raw = ak.futures_dce_position_rank(date=ymd, vars_list=list(_DCE_VARS))
    except TypeError:
        try:
            raw = ak.futures_dce_position_rank(date=ymd)
        except Exception:
            return None
    except Exception:
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    products = _normalize_dce_ak(raw)
    if not products:
        return None
    return {
        "ymd": ymd,
        "source": "akshare.futures_dce_position_rank",
        "products": products,
    }


def fetch_dce_member_day(ymd: str, *, force: bool = False) -> dict[str, Any] | None:
    """Pull one DCE session and cache ``dce-{ymd}.json``. Soft-fail.

    Public-first: Eastmoney → (optional) akshare/DCE zip last. Avoids WAF as
    the default path.
    """
    ymd = str(ymd or "").replace("-", "")
    if len(ymd) != 8 or not ymd.isdigit():
        return None
    if not force:
        cached = _read_dce_json(ymd)
        if cached and cached.get("products"):
            return cached
    payload = _fetch_dce_eastmoney(ymd)
    if not payload or not (payload.get("products") or {}):
        payload = _fetch_dce_akshare(ymd)
    if not payload or not (payload.get("products") or {}):
        return None
    path = _dce_json_path(ymd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return payload


def ensure_public_member_day(
    ymd: str,
    *,
    codes: list[str] | None = None,
    force_em: bool = False,
) -> dict[str, Any]:
    """One session via 东财 → 新浪补缺; writes ``em-*.json`` (+ DCE slice)."""
    ymd = str(ymd or "").replace("-", "")
    codes = [c.upper() for c in (codes or _universe_codes())]
    if len(ymd) != 8 or not ymd.isdigit():
        return {"ymd": ymd, "ok": False, "eastmoney": False, "coverage": {}}
    em = fetch_eastmoney_member_day(ymd, codes=codes, force=force_em)
    em_ok = bool(em and (em.get("products") or {}))
    if em_ok:
        print(f"  [member] eastmoney {ymd} products={len(em.get('products') or {})}")
    else:
        print(f"  [member] eastmoney {ymd} empty — sina coverage next")
    cov = ensure_universe_member_coverage(ymd, codes)
    return {
        "ymd": ymd,
        "ok": bool(cov.get("complete")),
        "eastmoney": em_ok,
        "coverage": cov,
    }


def ensure_member_days(
    dates: list[str], *, dce: bool = True, public_first: bool = True
) -> dict[str, int]:
    """Refresh seat caches for ISO / YYYYMMDD sessions.

    Default ``public_first``: 东财+新浪 for the Path-A 20, then soft SHFE/CZCE
    downloads for calendar densify. DCE zip is not required.
    """
    ymds: list[str] = []
    seen: set[str] = set()
    for day in dates:
        ymd = str(day or "").replace("-", "")
        if len(ymd) != 8 or not ymd.isdigit() or ymd in seen:
            continue
        seen.add(ymd)
        ymds.append(ymd)
    shfe_ok = czce_ok = dce_ok = em_ok = sina_fill = 0
    codes = _universe_codes()
    for ymd in ymds:
        if public_first:
            pub = ensure_public_member_day(ymd, codes=codes, force_em=False)
            if pub.get("eastmoney"):
                em_ok += 1
            filled = (pub.get("coverage") or {}).get("filled") or {}
            if any(v == "sina" for v in filled.values()):
                sina_fill += 1
            if dce and (_read_dce_json(ymd) or {}).get("products"):
                dce_ok += 1
        year = ymd[:4]
        # Soft native prints (calendar / desk SHFE·CZCE txt); never gate completeness.
        shfe = _get(
            f"https://www.shfe.com.cn/data/tradedata/future/dailydata/pm{ymd}.dat",
            _cache_path("shfe", ymd),
        )
        czce = _get(
            f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{ymd}/FutureDataHolding.txt",
            _cache_path("czce", ymd),
        )
        if shfe:
            shfe_ok += 1
        if czce:
            czce_ok += 1
        if not public_first:
            if dce:
                got = fetch_dce_member_day(ymd, force=False)
                if got and got.get("products"):
                    dce_ok += 1
                    print(f"  [member] dce {ymd} products={len(got['products'])}")
                else:
                    print(f"  [member] dce {ymd} empty — will use eastmoney/sina")
            em = fetch_eastmoney_member_day(ymd, codes=codes, force=False)
            if em and em.get("products"):
                em_ok += 1
                print(f"  [member] eastmoney {ymd} products={len(em['products'])}")
    return {
        "days": len(ymds),
        "shfe": shfe_ok,
        "czce": czce_ok,
        "dce": dce_ok,
        "eastmoney": em_ok,
        "sina_fill_days": sina_fill,
    }


def _member_folder() -> Path:
    return ROOT / ".cache" / "member"


def _ymd_stems(prefix: str) -> list[str]:
    folder = _member_folder()
    if not folder.is_dir():
        return []
    out: list[str] = []
    for path in folder.glob(f"{prefix}-*.*"):
        ymd = path.stem.split("-", 1)[-1]
        if len(ymd) == 8 and ymd.isdigit():
            out.append(ymd)
    return sorted(set(out))


def session_calendar_ymds(
    *,
    on_or_after: str | None = None,
    on_or_before: str | None = None,
) -> list[str]:
    """Trading-session candidates: SHFE/CZCE + public em/dce stems."""
    lo = str(on_or_after or "").replace("-", "")[:8] or None
    hi = str(on_or_before or "").replace("-", "")[:8] or None
    days = (
        set(_ymd_stems("shfe"))
        | set(_ymd_stems("czce"))
        | set(_ymd_stems("em"))
        | set(_ymd_stems("dce"))
    )
    out = sorted(days)
    if lo:
        out = [d for d in out if d >= lo]
    if hi:
        out = [d for d in out if d <= hi]
    return out


def backfill_member_lookback(
    *,
    lookback_calendar_days: int = 14,
    end: str | None = None,
    dce: bool = True,
    coverage: bool = True,
) -> dict[str, Any]:
    """Fill recent sessions via 东财→新浪 (unified), soft SHFE/CZCE underlay.

    Used by GitHub weekly / daily lookback so seat charts stay dense.
    Soft-fails per day.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    end_ymd = str(end or "").replace("-", "")[:8]
    if len(end_ymd) != 8 or not end_ymd.isdigit():
        end_ymd = datetime.now(tz).strftime("%Y%m%d")
    try:
        end_dt = datetime.strptime(end_ymd, "%Y%m%d")
    except ValueError:
        end_dt = datetime.now(tz)
        end_ymd = end_dt.strftime("%Y%m%d")
    start_dt = end_dt - timedelta(days=max(1, int(lookback_calendar_days)))
    start_ymd = start_dt.strftime("%Y%m%d")

    # Prefer known exchange session dates; if cache is empty, weekday grid.
    ymds = session_calendar_ymds(on_or_after=start_ymd, on_or_before=end_ymd)
    if not ymds:
        cursor = start_dt
        while cursor.date() <= end_dt.date():
            if cursor.weekday() < 5:
                ymds.append(cursor.strftime("%Y%m%d"))
            cursor += timedelta(days=1)

    # Always include days that already have any member file in the window
    # (keeps densifying DCE/EM even if SHFE list lags on CI fresh clone).
    for pref in ("shfe", "czce", "dce", "em"):
        for ymd in _ymd_stems(pref):
            if start_ymd <= ymd <= end_ymd and ymd not in ymds:
                ymds.append(ymd)
    ymds = sorted(set(ymds))

    stats = ensure_member_days(ymds, dce=dce)
    cov_ok = cov_miss = 0
    codes = _universe_codes()
    if coverage:
        for ymd in ymds:
            try:
                cov = ensure_universe_member_coverage(ymd, codes)
            except Exception as exc:  # noqa: BLE001
                print(f"  [member] coverage {ymd} soft-fail: {exc}")
                continue
            if cov.get("complete"):
                cov_ok += 1
            else:
                cov_miss += 1
                miss = cov.get("missing") or []
                if miss:
                    print(f"  [member] coverage {ymd} missing={miss}")
    out = {
        **stats,
        "start": start_ymd,
        "end": end_ymd,
        "coverage_ok": cov_ok,
        "coverage_incomplete": cov_miss,
        "ymds": ymds,
    }
    print(
        f"[member] backfill {start_ymd}→{end_ymd} days={stats['days']} "
        f"shfe={stats['shfe']} czce={stats['czce']} dce={stats['dce']} "
        f"em={stats.get('eastmoney', 0)} cov_ok={cov_ok}"
    )
    return out


def _fill_sina_product(ymd: str, code: str, contract: str) -> dict[str, Any] | None:
    legs = _sina_contract_legs(contract, ymd)
    if not legs:
        # try lowercase contract (sina sometimes prefers it)
        alt = contract.lower()
        if alt != contract:
            legs = _sina_contract_legs(alt, ymd)
    if not legs:
        return None
    packed = _pack_legs(contract, legs[0], legs[1])
    if not packed:
        return None
    packed["source"] = "sina.futures_hold_pos_sina"
    return packed


def ensure_universe_member_coverage(
    ymd: str, codes: list[str] | None = None
) -> dict[str, Any]:
    """Guarantee seat books for the Path-A observation set (default: all 20).

    Unified fill: Eastmoney cache (pull if thin) → Sina hold rank for any code
    still missing or ``n<15``. Writes ``em-{ymd}.json`` (+ DCE slice). Exchange
    prints are not required. ``complete`` only when every code has n≥15.
    """
    ymd = str(ymd or "").replace("-", "")
    codes = [c.upper() for c in (codes or _universe_codes())]
    if len(ymd) != 8 or not ymd.isdigit() or not codes:
        return {"ymd": ymd, "complete": False, "ok": [], "missing": codes, "filled": {}}

    def _em_ok(row: dict | None) -> bool:
        return bool(row) and int((row or {}).get("n") or 0) >= 15

    em = dict((_read_em_json(ymd) or {}).get("products") or {})
    need = [c for c in codes if not _em_ok(em.get(c))]
    if need:
        # Top up Eastmoney for thin/missing codes before Sina.
        fetch_eastmoney_member_day(ymd, codes=need, force=False)
        em = dict((_read_em_json(ymd) or {}).get("products") or {})

    mains = _em_main_contracts(set(codes))
    native = _day_seats(ymd)
    filled: dict[str, str] = {}
    for code in codes:
        if _em_ok(em.get(code)):
            continue
        if code in native:
            # Exchange print already has a book; still try Sina to densify em cache.
            pass
        meta = mains.get(code) or {}
        contract = str(meta.get("contract") or "")
        if not contract:
            continue
        sina_row = _fill_sina_product(ymd, code, contract)
        if not sina_row:
            continue
        sina_row["exchange"] = str(meta.get("exchange") or "")
        em[code] = sina_row
        filled[code] = "sina"
        print(f"  [member] sina fill {code} {contract}")
    if filled or em:
        payload = {
            "ymd": ymd,
            "source": "eastmoney+sina",
            "products": em,
        }
        _write_product_cache(_em_json_path(ymd), payload)
        dce_products = {
            k: v for k, v in em.items() if str(v.get("exchange") or "") == "DCE"
        }
        if dce_products:
            existing = (_read_dce_json(ymd) or {}).get("products") or {}
            existing.update(dce_products)
            _write_product_cache(
                _dce_json_path(ymd),
                {
                    "ymd": ymd,
                    "source": "eastmoney+sina",
                    "products": existing,
                },
            )
    # Re-read after fills — public em is authoritative for completeness.
    em = (_read_em_json(ymd) or {}).get("products") or {}
    day_books = _day_seats(ymd)
    ok: list[str] = []
    missing: list[str] = []
    for code in codes:
        if _em_ok(em.get(code)) or code in day_books:
            ok.append(code)
        else:
            missing.append(code)
    return {
        "ymd": ymd,
        "complete": not missing,
        "ok": ok,
        "missing": missing,
        "filled": filled,
        "n_ok": len(ok),
        "n_codes": len(codes),
    }


def _dce_nets(ymd: str) -> dict[str, float]:
    data = _read_dce_json(ymd)
    if not data:
        return {}
    out: dict[str, float] = {}
    for code, row in (data.get("products") or {}).items():
        if not isinstance(row, dict):
            continue
        n = int(row.get("n") or 0)
        if n < 15:
            continue
        long_total = _num(row.get("long_total"))
        short_total = _num(row.get("short_total"))
        if long_total is None or short_total is None:
            long_total = sum(float(x[1]) for x in (row.get("longs") or []) if len(x) >= 2)
            short_total = sum(float(x[1]) for x in (row.get("shorts") or []) if len(x) >= 2)
        out[str(code).upper()] = float(long_total) - float(short_total)
    return out


def _dce_seats(ymd: str) -> dict[str, dict]:
    data = _read_dce_json(ymd)
    if not data:
        return {}
    out: dict[str, dict] = {}
    for code, row in (data.get("products") or {}).items():
        if not isinstance(row, dict):
            continue
        n = int(row.get("n") or 0)
        if n < 15:
            continue
        book = _empty_seat()
        for name, qty in row.get("longs") or []:
            _add_leg(book, str(name), _num(qty) or 0.0, 1.0)
        for name, qty in row.get("shorts") or []:
            _add_leg(book, str(name), _num(qty) or 0.0, -1.0)
        out[str(code).upper()] = book
    return out


def _em_seats(ymd: str) -> dict[str, dict]:
    data = _read_em_json(ymd)
    if not data:
        return {}
    out: dict[str, dict] = {}
    for code, row in (data.get("products") or {}).items():
        book = _product_to_seat(row if isinstance(row, dict) else {})
        if book is not None:
            out[str(code).upper()] = book
    return out


def _em_nets(ymd: str) -> dict[str, float]:
    data = _read_em_json(ymd)
    if not data:
        return {}
    out: dict[str, float] = {}
    for code, row in (data.get("products") or {}).items():
        if not isinstance(row, dict) or int(row.get("n") or 0) < 15:
            continue
        long_total = _num(row.get("long_total"))
        short_total = _num(row.get("short_total"))
        if long_total is None or short_total is None:
            long_total = sum(float(x[1]) for x in (row.get("longs") or []) if len(x) >= 2)
            short_total = sum(float(x[1]) for x in (row.get("shorts") or []) if len(x) >= 2)
        out[str(code).upper()] = float(long_total) - float(short_total)
    return out


def _day_nets(ymd: str) -> dict[str, float]:
    # Native first; Eastmoney/Sina overlay only fills holes.
    merged = {}
    merged.update(_em_nets(ymd))
    merged.update(_shfe_nets(ymd))
    merged.update(_czce_nets(ymd))
    merged.update(_dce_nets(ymd))
    return merged


def _day_seats(ymd: str) -> dict[str, dict]:
    # Exchange prints first; 东财/新浪 unified cache wins / fills (public-first).
    merged = {}
    merged.update(_shfe_seats(ymd))
    merged.update(_czce_seats(ymd))
    merged.update(_dce_seats(ymd))
    merged.update(_em_seats(ymd))
    return merged


def load_member_changes(dates: list[str], codes: list[str]) -> dict[str, dict]:
    """Map code -> {date -> top-20 net-long change vs previous session}."""
    global _CHANGES
    key = (tuple(dates), tuple(codes))
    if _CHANGES is not None and _CHANGES.get("_key") == key:
        return _CHANGES["changes"]
    ymds = [(d, d.replace("-", "")) for d in dates]
    nets: dict[str, dict[str, float]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_day_nets, ymd): day for day, ymd in ymds}
        done = 0
        for fut in as_completed(futs):
            day = futs[fut]
            try:
                nets[day] = fut.result()
            except Exception:
                nets[day] = {}
            done += 1
            if done % 40 == 0 or done == len(ymds):
                print(f"  [member] files {done}/{len(ymds)}")
    changes = {c: {} for c in codes}
    prev = None
    for day in dates:
        if prev is not None:
            for code in codes:
                now = (nets.get(day) or {}).get(code)
                old = (nets.get(prev) or {}).get(code)
                changes[code][day] = None if now is None or old is None else now - old
        prev = day
    covered = {
        c: sum(1 for v in changes[c].values() if v is not None) for c in codes
    }
    print("  [member] days-with-change " + " ".join(f"{c}:{covered[c]}" for c in codes))
    _CHANGES = {"_key": key, "changes": changes}
    return changes


def load_member_seats(dates: list[str], codes: list[str]) -> dict[str, dict]:
    """Map code -> {date -> {inst, foreign, holder} net lots}. Missing day is omitted."""
    global _SEATS
    key = (tuple(dates), tuple(codes))
    if _SEATS is not None and _SEATS.get("_key") == key:
        return _SEATS["books"]
    ymds = [(d, d.replace("-", "")) for d in dates]
    nets: dict[str, dict[str, dict]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_day_seats, ymd): day for day, ymd in ymds}
        done = 0
        for fut in as_completed(futs):
            day = futs[fut]
            try:
                nets[day] = fut.result()
            except Exception:
                nets[day] = {}
            done += 1
            if done % 40 == 0 or done == len(ymds):
                print(f"  [seats] files {done}/{len(ymds)}")
    books = {c: {} for c in codes}
    for day in dates:
        day_book = nets.get(day) or {}
        for code in codes:
            row = day_book.get(code)
            if row is None:
                continue
            books[code][day] = {k: row.get(k, 0.0) for k in ("inst", "foreign", "holder")}
    covered = {c: len(books[c]) for c in codes}
    print("  [seats] days " + " ".join(f"{c}:{covered[c]}" for c in codes))
    _SEATS = {"_key": key, "books": books}
    return books


if __name__ == "__main__":
    import sys

    day = (sys.argv[1] if len(sys.argv) > 1 else "").replace("-", "")
    if len(day) != 8 or not day.isdigit():
        print("usage: python member_rank.py YYYYMMDD")
        raise SystemExit(2)
    got = fetch_dce_member_day(day, force=True)
    if not got:
        print(f"[dce] {day} empty (WAF/network/akshare soft-fail)")
        raise SystemExit(1)
    print(f"[dce] {day} products={sorted((got.get('products') or {}).keys())}")
