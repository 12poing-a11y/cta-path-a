# -*- coding: utf-8 -*-
"""Member rankings from SHFE and CZCE public files.

DCE is not in these files. A missing print does not block the entry.

Seat books use three fixed name lists. Other top-20 members are ignored.
The ranking prints 中信建投 for the retail seat often called 中建投,
and 东证期货 for 东证融汇. DCE has no member file.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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


def _day_nets(ymd: str) -> dict[str, float]:
    merged = {}
    merged.update(_shfe_nets(ymd))
    merged.update(_czce_nets(ymd))
    return merged


def _day_seats(ymd: str) -> dict[str, dict]:
    merged = {}
    merged.update(_shfe_seats(ymd))
    merged.update(_czce_seats(ymd))
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
