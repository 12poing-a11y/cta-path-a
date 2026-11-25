# -*- coding: utf-8 -*-
"""Unified parser for the R8 raw per-contract daily files (archive/R8/raw_contract/{shfe,czce,dce}/*.gz).

Row schema (floats or None): open, high, low, close, settle, presettle, volume, oi, turnover_wan (万元).
`load_all()` -> {contract_id: {YYYY-MM-DD: row}} for the 27 universe symbols only.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "archive" / "R8" / "raw_contract"
EXCH = {
    "shfe": {"AG", "AL", "AU", "BU", "CU", "FU", "NI", "RB", "RU", "SP", "SS"},
    "dce": {"EB", "EG", "I", "JD", "JM", "L", "M", "P", "PP", "V"},
    "czce": {"CF", "FG", "MA", "SA", "SR", "TA"},
}
CODE_EX = {c: ex for ex, cs in EXCH.items() for c in cs}


def _f(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _read(ex: str, ymd: str) -> bytes | None:
    p = RAW / ex / f"{ymd}.gz"
    return gzip.decompress(p.read_bytes()) if p.exists() else None


def parse_shfe(raw: bytes) -> dict[str, dict]:
    out = {}
    for r in json.loads(raw).get("o_curinstrument", []):
        pid = str(r.get("PRODUCTID", "")).strip()
        if not pid.endswith("_f"):
            continue
        code = pid.split("_")[0].upper()
        dm = str(r.get("DELIVERYMONTH", "")).strip()
        if code not in EXCH["shfe"] or not (dm.isdigit() and len(dm) == 4):
            continue
        out[code + dm] = {
            "open": _f(r.get("OPENPRICE")), "high": _f(r.get("HIGHESTPRICE")), "low": _f(r.get("LOWESTPRICE")),
            "close": _f(r.get("CLOSEPRICE")), "settle": _f(r.get("SETTLEMENTPRICE")), "presettle": _f(r.get("PRESETTLEMENTPRICE")),
            "volume": _f(r.get("VOLUME")), "oi": _f(r.get("OPENINTEREST")), "turnover_wan": _f(r.get("TURNOVER")),
        }
    return out


def _czce_contract(tok: str, d: str) -> str | None:
    m = re.fullmatch(r"([A-Z]{1,2})(\d{3,4})", tok)
    if not m:
        return None
    code, num = m.group(1), m.group(2)
    if len(num) == 4:
        return code + num
    y, mm = int(num[0]), int(num[1:])
    yy, dm = int(d[:4]), int(d[5:7])
    base = (yy // 10) * 10 + y
    for Y in (base - 10, base, base + 10):
        if (Y, mm) >= (yy, dm):
            return f"{code}{Y % 100:02d}{mm:02d}"
    return None


def parse_czce(raw: bytes, d: str) -> dict[str, dict]:
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("gbk", "ignore")
    out = {}
    for line in txt.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 13:
            continue
        cid = _czce_contract(parts[0].upper(), d)
        if cid is None or re.match(r"[A-Z]+", cid).group(0) not in EXCH["czce"]:
            continue
        out[cid] = {
            "presettle": _f(parts[1]), "open": _f(parts[2]), "high": _f(parts[3]), "low": _f(parts[4]), "close": _f(parts[5]),
            "settle": _f(parts[6]), "volume": _f(parts[9]), "oi": _f(parts[10]), "turnover_wan": _f(parts[12]),
        }
    return out


def parse_dce(raw: bytes) -> dict[str, dict]:
    j = json.loads(raw)
    out = {}
    for row in j["rows"]:
        r = dict(zip(j["cols"], row))
        cid = str(r["contractId"]).upper()
        code = re.match(r"[A-Z]+", cid).group(0)
        if code not in EXCH["dce"]:
            continue
        out[cid] = {
            "open": _f(r["open"]), "high": _f(r["high"]), "low": _f(r["low"]), "close": _f(r["close"]), "settle": _f(r["clearPrice"]),
            "presettle": _f(r["lastClear"]), "volume": _f(r["volumn"]), "oi": _f(r["openInterest"]), "turnover_wan": _f(r["turnover"]),
        }
    return out


def load_all() -> dict[str, dict[str, dict]]:
    by: dict[str, dict[str, dict]] = {}
    for ex in ("shfe", "czce", "dce"):
        m = json.loads((RAW / f"MANIFEST_{ex}.json").read_text(encoding="utf-8"))
        for d, rec in sorted(m.items()):
            if rec.get("status") != "ok":
                continue
            raw = _read(ex, d.replace("-", ""))
            if raw is None:
                continue
            rows = parse_shfe(raw) if ex == "shfe" else parse_czce(raw, d) if ex == "czce" else parse_dce(raw)
            for cid, row in rows.items():
                by.setdefault(cid, {})[d] = row
    return by


def complete(row: dict | None) -> bool:
    """OHLC > 0 and settle > 0 and volume / OI present (the user's 'full record' test)."""
    if not row:
        return False
    for k in ("open", "high", "low", "close", "settle"):
        v = row.get(k)
        if v is None or v <= 0:
            return False
    return row.get("volume") is not None and row.get("oi") is not None
