# -*- coding: utf-8 -*-
"""Daily validation (design §6). Returns findings; 'fail' findings make the day abnormal, 'info' ones are only listed."""
from __future__ import annotations

from collections import Counter

from . import config as C


def _pos(x) -> bool:
    return x is not None and x > 0


def validate_day(by: dict, day: str, prev_day: str | None = None, products=None) -> dict:
    """by: {contract: {day: row}} (as contract_loader.load_all). prev_day: previous trading day to compare contract counts with."""
    products = list(products or C.PRODUCTS)
    fails: list[str] = []
    infos: list[str] = []
    rows_by_product: dict[str, dict[str, dict]] = {p: {} for p in products}
    for contract, dd in by.items():
        row = dd.get(day)
        if row is None:
            continue
        prod = "".join(ch for ch in contract if ch.isalpha()).upper()
        if prod in rows_by_product:
            rows_by_product[prod][contract] = row

    # 2. products complete
    empty = [p for p in products if not rows_by_product[p]]
    if empty:
        fails.append(f"products with no contract rows: {empty}")
    count = {p: len(rows_by_product[p]) for p in products}
    if prev_day is not None:
        prev_count = Counter()
        for contract, dd in by.items():
            if dd.get(prev_day) is not None:
                prod = "".join(ch for ch in contract if ch.isalpha()).upper()
                if prod in count:
                    prev_count[prod] += 1
        for p in products:
            if prev_count[p] and not count[p]:
                fails.append(f"{p}: had contracts on previous session, none today")
            elif prev_count[p] and count[p] < prev_count[p] * 0.5:
                infos.append(f"{p}: contract count {count[p]} vs previous {prev_count[p]}")

    # 3. OHLC sanity and settle
    bad_ohlc = bad_settle = thin_zero = jumps = 0
    examples: list[str] = []
    for p, cs in rows_by_product.items():
        for contract, r in cs.items():
            o, h, l, c, s = (r.get(k) for k in ("open", "high", "low", "close", "settle"))
            vol = r.get("volume") or 0
            if _pos(h) and _pos(l) and _pos(c):
                o_ = o if _pos(o) else None  # official open of 0 = not published; not checked against the range
                lo = min(x for x in (l, c, o_) if x is not None)
                hi = max(x for x in (h, c, o_) if x is not None)
                if not (lo == l and hi == h):
                    bad_ohlc += 1
                    if len(examples) < 10:
                        examples.append(f"{contract} OHLC {o},{h},{l},{c}")
            elif (o or 0) == 0 and (h or 0) == 0 and (l or 0) == 0 and (c or 0) > 0:
                thin_zero += 1  # thin row without OHLC: official publishes zeros; not an error by itself
            if vol > 0 and not _pos(s):
                bad_settle += 1
                if len(examples) < 10:
                    examples.append(f"{contract} settle missing with volume {vol}")
            pre = r.get("presettle")
            if _pos(c) and _pos(pre) and abs(c / pre - 1) > C.PRICE_JUMP_INFO:
                jumps += 1
    if bad_ohlc:
        fails.append(f"OHLC inconsistent rows: {bad_ohlc}")
    if bad_settle:
        fails.append(f"settle missing on rows with volume: {bad_settle}")
    if thin_zero:
        infos.append(f"thin rows with zero OHLC (volume-only): {thin_zero}")
    if jumps:
        infos.append(f"|close/presettle-1| > {C.PRICE_JUMP_INFO:.0%}: {jumps} rows (listed, not failed)")
    return {"ok": not fails, "fails": fails, "infos": infos, "examples": examples,
            "products_counts": count, "contract_rows": sum(count.values())}
