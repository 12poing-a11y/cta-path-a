# -*- coding: utf-8 -*-
"""Overlay exact-contract OHLC onto continuous packs for fill simulation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def default_front_month(root: Path | None = None) -> str:
    root = root or ROOT
    try:
        from gamma_wall import OBSERVE_MONTH

        return str(OBSERVE_MONTH)
    except Exception:
        return "2701"


def front_month_for_product(code: str, *, root: Path | None = None, fallback: str | None = None) -> str:
    """Pick YYMM from product listed months nearest to observe month."""
    root = root or ROOT
    base = fallback or default_front_month(root)
    code = str(code or "").upper()
    try:
        from research.data_quality.calendar import product_rule

        pr = product_rule(code)
        months = pr.get("months") or list(range(1, 13))
    except Exception:
        months = list(range(1, 13))
    yy = int(base[:2])
    mm = int(base[2:])
    year = 2000 + yy
    # search forward up to 12 months for a listed month
    for _ in range(13):
        if mm in months:
            return f"{year % 100:02d}{mm:02d}"
        mm += 1
        if mm > 12:
            mm = 1
            year += 1
    return base


def front_contract_for(code: str, month: str | None = None) -> str:
    m = month or front_month_for_product(code)
    return f"{str(code).upper()}{m}"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_exact_contract_daily(contract: str, root: Path | None = None) -> list[dict[str, Any]]:
    """Load cached exact-contract daily bars (no network)."""
    root = root or ROOT
    contract = str(contract).upper()
    # Prefer stable contracts cache from backfill script
    stable = root / ".cache" / "contracts" / f"{contract}.json"
    # Prefer gamma/raw exact daily
    raw = root / ".cache" / "gamma_wall" / "raw" / f"{contract}_daily.json"
    candidates = [stable, raw]
    # Dated sina snapshots — take newest folder file
    sina_root = root / ".cache" / "sina"
    if sina_root.is_dir():
        hits = sorted(sina_root.glob(f"*/{contract}.json"), reverse=True)
        candidates.extend(hits[:3])
    bars: list[dict[str, Any]] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = _load_json(path)
        except Exception:
            continue
        rows = data if isinstance(data, list) else data.get("bars") or data.get("hist") or data.get("data") or []
        for b in rows:
            if not isinstance(b, dict):
                continue
            d = str(b.get("date") or b.get("datetime") or "")[:10]
            if len(d) == 8 and d.isdigit():
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            if len(d) != 10:
                continue
            try:
                bars.append(
                    {
                        "date": d,
                        "open": float(b.get("open") if b.get("open") is not None else b["close"]),
                        "high": float(b.get("high") if b.get("high") is not None else b["close"]),
                        "low": float(b.get("low") if b.get("low") is not None else b["close"]),
                        "close": float(b["close"]),
                        "volume": float(b.get("volume") or 0),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        if bars:
            break
    # dedupe by date keep last
    by: dict[str, dict] = {}
    for b in bars:
        by[b["date"]] = b
    return [by[k] for k in sorted(by)]


def overlay_contract_fills(
    series: dict[str, dict[str, Any]],
    *,
    month: str | None = None,
    root: Path | None = None,
    min_coverage: float = 0.3,
) -> dict[str, Any]:
    """Annotate continuous hist with contract open/close when cache exists.

    Signals stay on continuous; fills may use contract_open when present.
    """
    root = root or ROOT
    report = {"month": month or "per_product", "symbols": {}, "fill_series": "continuous_proxy"}
    any_contract = False
    for code, pack in series.items():
        hist = pack.get("hist") or []
        meta = dict(pack.get("meta") or {})
        use_month = month or front_month_for_product(code, root=root)
        contract = front_contract_for(code, use_month)
        c_bars = load_exact_contract_daily(contract, root=root)
        by_c = {b["date"]: b for b in c_bars}
        matched = 0
        new_hist = []
        for b in hist:
            row = dict(b)
            d = str(row.get("date") or "")[:10]
            cb = by_c.get(d)
            if cb:
                matched += 1
                row["contract"] = contract
                row["contract_open"] = cb["open"]
                row["contract_high"] = cb["high"]
                row["contract_low"] = cb["low"]
                row["contract_close"] = cb["close"]
                row["price_basis"] = "continuous_proxy"
                row["fill_price_basis"] = "contract"
            new_hist.append(row)
        cov = matched / max(len(hist), 1)
        meta["front_contract"] = contract
        meta["contract_fill_coverage"] = round(cov, 4)
        if cov >= min_coverage and matched > 0:
            meta["price_basis"] = "continuous_proxy"
            meta["allow_continuous_fill"] = True
            meta["fill_series"] = "contract"
            any_contract = True
        else:
            meta["fill_series"] = "continuous_proxy"
            meta["allow_continuous_fill"] = True
        pack["hist"] = new_hist
        pack["meta"] = meta
        report["symbols"][code] = {
            "contract": contract,
            "coverage": round(cov, 4),
            "matched": matched,
            "fill_series": meta["fill_series"],
        }
    report["fill_series"] = "contract" if any_contract else "continuous_proxy"
    return report


def annotate_pack_calendar(
    series: dict[str, dict[str, Any]],
    *,
    month: str | None = None,
    root: Path | None = None,
) -> None:
    from research.data_quality.calendar import annotate_bars_with_calendar

    for code, pack in series.items():
        use_month = month or front_month_for_product(code, root=root)
        contract = front_contract_for(code, use_month)
        pack["hist"] = annotate_bars_with_calendar(
            code, pack.get("hist") or [], front_contract=contract
        )
        meta = dict(pack.get("meta") or {})
        meta["front_contract"] = contract
        pack["meta"] = meta
