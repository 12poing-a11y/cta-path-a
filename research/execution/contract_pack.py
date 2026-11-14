# -*- coding: utf-8 -*-
"""Overlay exact-contract OHLC onto continuous packs for fill simulation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# |contract_close/continuous_close - 1| above this → drop contract stamps (force proxy).
# Calendar-nearest month ≠ OI main often shows 10–20% gaps; those must not fill mixed.
DEFAULT_MAX_BASIS_REL = 0.03


def default_front_month(root: Path | None = None) -> str:
    root = root or ROOT
    try:
        from gamma_wall import OBSERVE_MONTH

        return str(OBSERVE_MONTH)
    except Exception:
        return "2701"


def front_month_for_product(code: str, *, root: Path | None = None, fallback: str | None = None) -> str:
    """Pick YYMM from product listed months nearest to observe month (live/desk helper).

    Historical fills must use ``active_front_contract_on_date`` instead of this.
    """
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
    stable = root / ".cache" / "contracts" / f"{contract}.json"
    raw = root / ".cache" / "gamma_wall" / "raw" / f"{contract}_daily.json"
    candidates = [stable, raw]
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
    by: dict[str, dict] = {}
    for b in bars:
        by[b["date"]] = b
    return [by[k] for k in sorted(by)]


def _basis_rel(contract_px: float, continuous_px: float) -> float | None:
    try:
        c0 = float(continuous_px)
        c1 = float(contract_px)
    except (TypeError, ValueError):
        return None
    if c0 <= 0 or c1 <= 0:
        return None
    return abs(c1 / c0 - 1.0)


def overlay_contract_fills(
    series: dict[str, dict[str, Any]],
    *,
    month: str | None = None,
    root: Path | None = None,
    min_coverage: float = 0.3,
    historical: bool = True,
    max_basis_rel: float = DEFAULT_MAX_BASIS_REL,
) -> dict[str, Any]:
    """Annotate continuous hist with contract open/close when cache exists.

    Signals stay on continuous; fills may use contract_open when present.

    When ``historical=True`` (default), each bar picks the front contract that was
    still tradeable on that bar date — not a single observe-month blanket.
    Pass ``month=YYMM`` and ``historical=False`` only for live/desk single-month overlays.

    Bars whose contract close diverges from continuous by more than ``max_basis_rel``
    are forced to ``continuous_proxy`` (no contract_* stamps) so simulate cannot mix
    contract entry with continuous stop/target management.
    """
    root = root or ROOT
    from research.data_quality.calendar import active_front_contract_on_date, load_delivery_rules

    rules = load_delivery_rules(root)
    max_basis = float(max_basis_rel)
    report: dict[str, Any] = {
        "month": month or ("historical" if historical else "per_product"),
        "mode": "historical_roll" if historical and month is None else ("fixed_month" if month else "per_product"),
        "symbols": {},
        "fill_series": "continuous_proxy",
        "max_basis_rel": max_basis,
        "basis_rejected_n": 0,
    }
    any_contract = False
    basis_rejected_total = 0
    contract_cache: dict[str, dict[str, dict]] = {}

    def _bars_by_date(contract: str) -> dict[str, dict]:
        if contract not in contract_cache:
            rows = load_exact_contract_daily(contract, root=root)
            contract_cache[contract] = {b["date"]: b for b in rows}
        return contract_cache[contract]

    for code, pack in series.items():
        hist = pack.get("hist") or []
        meta = dict(pack.get("meta") or {})
        matched = 0
        proxy_n = 0
        basis_rejected = 0
        used: dict[str, int] = {}
        new_hist = []
        for b in hist:
            row = dict(b)
            d = str(row.get("date") or "")[:10]
            if month and not historical:
                contract = front_contract_for(code, month)
            elif month and historical:
                # rare: force month for tests, still stamp that contract only
                contract = front_contract_for(code, month)
            else:
                contract = active_front_contract_on_date(code, d, rules=rules)
            if not contract:
                row["price_basis"] = "continuous_proxy"
                row["fill_price_basis"] = "continuous_proxy"
                proxy_n += 1
                new_hist.append(row)
                continue
            by_c = _bars_by_date(contract)
            cb = by_c.get(d)
            row["contract"] = contract
            used[contract] = used.get(contract, 0) + 1
            if cb:
                cont_close = row.get("close")
                rel = _basis_rel(cb["close"], cont_close) if cont_close is not None else None
                if rel is not None and rel > max_basis:
                    # Wrong month vs main continuous — do not stamp executable contract fills.
                    basis_rejected += 1
                    row["price_basis"] = "continuous_proxy"
                    row["fill_price_basis"] = "continuous_proxy"
                    row["basis_rejected"] = True
                    row["basis_rel"] = round(rel, 4)
                    proxy_n += 1
                else:
                    matched += 1
                    row["contract_open"] = cb["open"]
                    row["contract_high"] = cb["high"]
                    row["contract_low"] = cb["low"]
                    row["contract_close"] = cb["close"]
                    row["price_basis"] = "contract"
                    row["fill_price_basis"] = "contract"
                    if rel is not None:
                        row["basis_rel"] = round(rel, 4)
            else:
                row["price_basis"] = "continuous_proxy"
                row["fill_price_basis"] = "continuous_proxy"
                proxy_n += 1
            new_hist.append(row)
        cov = matched / max(len(hist), 1)
        basis_rejected_total += basis_rejected
        meta["front_contract"] = (
            max(used.items(), key=lambda kv: kv[1])[0] if used else front_contract_for(code)
        )
        meta["contracts_used"] = used
        meta["contract_fill_coverage"] = round(cov, 4)
        meta["proxy_fill_share"] = round(proxy_n / max(len(hist), 1), 4)
        meta["basis_rejected_n"] = basis_rejected
        meta["historical_roll"] = bool(historical and not month)
        if cov >= min_coverage and matched > 0:
            # Continuous proxy always allowed as fallback; contract fills only when stamped.
            meta["allow_continuous_fill"] = True
            meta["fill_series"] = "contract" if proxy_n == 0 else "mixed"
            any_contract = True
        else:
            meta["fill_series"] = "continuous_proxy"
            meta["allow_continuous_fill"] = True
        pack["hist"] = new_hist
        pack["meta"] = meta
        report["symbols"][code] = {
            "contracts_used": used,
            "front_contract": meta["front_contract"],
            "coverage": round(cov, 4),
            "matched": matched,
            "proxy_n": proxy_n,
            "basis_rejected_n": basis_rejected,
            "proxy_fill_share": meta["proxy_fill_share"],
            "fill_series": meta["fill_series"],
        }
    report["basis_rejected_n"] = basis_rejected_total
    report["fill_series"] = "contract" if any_contract else "continuous_proxy"
    if any_contract:
        # Prefer mixed when any symbol still proxies
        if any(
            (report["symbols"][c].get("proxy_n") or 0) > 0 for c in report["symbols"]
        ):
            report["fill_series"] = "mixed"
    return report


def annotate_pack_calendar(
    series: dict[str, dict[str, Any]],
    *,
    month: str | None = None,
    root: Path | None = None,
) -> None:
    from research.data_quality.calendar import annotate_bars_with_calendar

    for code, pack in series.items():
        # Per-bar inference when month is None (historical); fixed contract when month set.
        front = front_contract_for(code, month) if month else None
        pack["hist"] = annotate_bars_with_calendar(
            code, pack.get("hist") or [], front_contract=front
        )
        meta = dict(pack.get("meta") or {})
        if front:
            meta["front_contract"] = front
        pack["meta"] = meta
