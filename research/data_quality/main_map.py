# -*- coding: utf-8 -*-
"""Actual main-contract map (R6b-fix).

``main_map[code][d]`` = the monthly contract whose own daily bar on ``d`` matches
the Sina continuous bar of ``d`` (close within one tick; high/low only used to
break ties).  ``None`` when nothing matches.

* The calendar stamp ``bar["contract"]`` (``active_front_contract_on_date``) is
  NOT the main contract — it changes every month for 12-month products while
  Sina's main does not move.  It is only used as one candidate's data source.
* ``main_map[d]`` is only knowable after day ``d`` closes (needs d's close).
  Callers may use it to pick *which contract's* real bar prices day ``d``, and
  to schedule a roll at ``d+1`` open — never to trade on ``d`` itself.
* Truncation-safe: ``main_map[d]`` depends only on data dated ``d`` (plus
  ``main_map[d-1]`` as a tie-break), never on later bars.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

_BY_DATE_CACHE: dict[tuple[str, str, int], dict[str, dict]] = {}


def contract_bars_by_date(contract: str, root: Path | None = None) -> dict[str, dict]:
    """Exact-contract daily bars keyed by date (cached; refreshed when the cache file changes)."""
    root = Path(root or ROOT)
    contract = str(contract or "").upper()
    stable = root / ".cache" / "contracts" / f"{contract}.json"
    try:
        mt = stable.stat().st_mtime_ns if stable.is_file() else 0
    except OSError:
        mt = 0
    key = (str(root), contract, mt)
    hit = _BY_DATE_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        from research.execution.contract_pack import load_exact_contract_daily

        rows = load_exact_contract_daily(contract, root=root)
    except Exception:  # noqa: BLE001
        rows = []
    by = {str(b["date"])[:10]: b for b in rows}
    _BY_DATE_CACHE[key] = by
    return by


def cached_contracts_for(code: str, root: Path | None = None) -> list[str]:
    """Contract ids (``CODEYYMM``) available under ``.cache/contracts``."""
    root = Path(root or ROOT)
    d = root / ".cache" / "contracts"
    if not d.is_dir():
        return []
    pat = re.compile(rf"^{re.escape(str(code).upper())}\d{{4}}$")
    return sorted(p.stem for p in d.glob("*.json") if pat.match(p.stem))


def _snap_contract_bar(b: dict) -> dict | None:
    """Real contract OHLC stamped on a snapshot/continuous bar, if any."""
    try:
        if (
            b.get("contract_high") is None
            or b.get("contract_low") is None
            or b.get("contract_close") is None
        ):
            return None
        return {
            "high": float(b["contract_high"]),
            "low": float(b["contract_low"]),
            "close": float(b["contract_close"]),
        }
    except (TypeError, ValueError):
        return None


@dataclass
class MainMap:
    maps: dict[str, dict[str, str | None]] = field(default_factory=dict)
    stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    def main(self, code: str, day: str) -> str | None:
        return (self.maps.get(code) or {}).get(str(day)[:10])

    def usable(self, code: str) -> bool:
        """True when the map identified the main contract on at least one day."""
        return any(v is not None for v in (self.maps.get(code) or {}).values())


def match_main_contract(
    bar: dict,
    candidates: dict[str, dict],
    *,
    tick: float,
    prev_main: str | None = None,
) -> tuple[str | None, str]:
    """Pick the candidate whose close is within one tick of ``bar['close']``.

    Returns (contract|None, status) with status in
    ``matched`` / ``ambiguous`` / ``no_match`` / ``no_candidate``.
    """
    try:
        c0 = float(bar["close"])
        h0 = float(bar["high"])
        l0 = float(bar["low"])
    except (KeyError, TypeError, ValueError):
        return None, "no_candidate"
    if not candidates:
        return None, "no_candidate"
    tol = float(tick or 0.0) * (1.0 + 1e-9) + 1e-9
    within = {k: v for k, v in candidates.items() if abs(float(v["close"]) - c0) <= tol}
    if not within:
        return None, "no_match"
    if len(within) == 1:
        return next(iter(within)), "matched"
    hl = {
        k: v
        for k, v in within.items()
        if abs(float(v["high"]) - h0) <= tol and abs(float(v["low"]) - l0) <= tol
    }
    pool = hl or within

    def score(k: str) -> float:
        v = pool[k]
        return (
            abs(float(v["close"]) - c0)
            + abs(float(v["high"]) - h0)
            + abs(float(v["low"]) - l0)
        )

    best = min(score(k) for k in pool)
    top = sorted(k for k in pool if score(k) <= best + 1e-12)
    if len(top) == 1:
        return top[0], "matched"
    if prev_main in top:  # tie → stay on yesterday's main (d−1 info only)
        return prev_main, "matched"
    return None, "ambiguous"


def build_main_map(
    series: dict[str, dict[str, Any]],
    *,
    root: Path | None = None,
    start: str | None = None,
) -> MainMap:
    """Build main_map for every code in ``series`` (post-overlay continuous packs)."""
    root = Path(root or ROOT)
    out = MainMap()
    for code, pack in series.items():
        hist = pack.get("hist") or []
        meta = pack.get("meta") or {}
        try:
            tick = float(meta.get("tick") or 0.0)
        except (TypeError, ValueError):
            tick = 0.0
        contracts = set(cached_contracts_for(code, root))
        for b in hist:
            c = str(b.get("contract") or "").upper()
            if c and _snap_contract_bar(b) is not None:
                contracts.add(c)
        by_contract = {c: contract_bars_by_date(c, root) for c in sorted(contracts)}
        m: dict[str, str | None] = {}
        n = matched = none_n = ambiguous = no_cand = no_match = 0
        none_dates: list[str] = []
        prev_main: str | None = None
        for b in hist:
            d = str(b.get("date") or "")[:10]
            if not d:
                continue
            cands: dict[str, dict] = {}
            own = str(b.get("contract") or "").upper()
            snap_c = _snap_contract_bar(b)
            for c, rows in by_contract.items():
                if c == own and snap_c is not None:
                    cands[c] = snap_c  # snapshot contract_* first
                elif d in rows:
                    cands[c] = rows[d]
            main, status = match_main_contract(b, cands, tick=tick, prev_main=prev_main)
            m[d] = main
            in_window = (start is None) or d >= str(start)[:10]
            if in_window:
                n += 1
                if main is not None:
                    matched += 1
                else:
                    none_n += 1
                    if status == "ambiguous":
                        ambiguous += 1
                    elif status == "no_candidate":
                        no_cand += 1
                    else:
                        no_match += 1
                    if len(none_dates) < 40:
                        none_dates.append(d)
            prev_main = main
        out.maps[code] = m
        out.stats[code] = {
            "days": n,
            "matched": matched,
            "none_days": none_n,
            "coverage": round(matched / n, 4) if n else None,
            "none_no_candidate_bar": no_cand,
            "none_no_match_within_tick": no_match,
            "none_ambiguous": ambiguous,
            "none_dates": none_dates,
            "candidates": sorted(by_contract),
            "tick": tick,
        }
    return out
