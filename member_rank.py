# -*- coding: utf-8 -*-
"""Member rankings from SHFE, CZCE public files, and DCE via akshare.

SHFE/CZCE are plain exchange downloads into ``.cache/member/{shfe,czce}-*.txt``.
DCE is pulled through ``akshare.futures_dce_position_rank`` into
``dce-YYYYMMDD.json``. Exchange WAF (HTTP 412 / BadZipFile) is common; fetch
soft-fails and leaves the day missing so Path A still passes DCE without a
seat book. A missing print does not block the entry.

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


def fetch_dce_member_day(ymd: str, *, force: bool = False) -> dict[str, Any] | None:
    """Pull one DCE session via akshare and cache ``dce-{ymd}.json``. Soft-fail."""
    ymd = str(ymd or "").replace("-", "")
    if len(ymd) != 8 or not ymd.isdigit():
        return None
    if not force:
        cached = _read_dce_json(ymd)
        if cached and cached.get("products"):
            return cached
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
    payload: dict[str, Any] = {
        "ymd": ymd,
        "source": "akshare.futures_dce_position_rank",
        "products": products,
    }
    path = _dce_json_path(ymd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return payload


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


def _day_nets(ymd: str) -> dict[str, float]:
    merged = {}
    merged.update(_shfe_nets(ymd))
    merged.update(_czce_nets(ymd))
    merged.update(_dce_nets(ymd))
    return merged


def _day_seats(ymd: str) -> dict[str, dict]:
    merged = {}
    merged.update(_shfe_seats(ymd))
    merged.update(_czce_seats(ymd))
    merged.update(_dce_seats(ymd))
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
