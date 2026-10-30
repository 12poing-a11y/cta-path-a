# -*- coding: utf-8 -*-
"""Build a long-format daily factor panel from lab continuous bars (+ carry/seats)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
sys.path.insert(0, str(ROOT))

from vol_factor_combo import _ret_std  # noqa: E402

FACTOR_LIST = [
    "mom_20",
    "mom_60",
    "vol_s",
    "vol_m",
    "vol_l",
    "vol_ratio_sl",
    "carry_gap_pct",
    "basis_mom_20",
    "skew_60",
    "mom_vol_20",
    "hedge_pressure",
    "warrant_w",
]


def _std_mom(closes: list[float], i: int, n: int) -> float | None:
    if i < n or closes[i - n] <= 0:
        return None
    return (closes[i] / closes[i - n] - 1.0) * 100.0


def _skew(rets: list[float]) -> float | None:
    n = len(rets)
    if n < 20:
        return None
    mu = sum(rets) / n
    var = sum((r - mu) ** 2 for r in rets) / n
    if var <= 1e-18:
        return 0.0
    sd = math.sqrt(var)
    return sum(((r - mu) / sd) ** 3 for r in rets) / n


# Lab needs IS-era carry; Sina contract history typically starts ~2018–2019.
_CURVE_BACK_DAYS = 4000


def _load_carry_rich(code: str) -> tuple[dict[str, float], dict[str, float]]:
    """gap% by day, and basis-momentum 20d from front vs next contract moms."""
    try:
        from public_curve import load_curves
        from path_a_filters import carry_gap_pct
    except Exception:
        return {}, {}
    curves = load_curves([code], back_days=_CURVE_BACK_DAYS)
    carry = (curves.get(code) or {}).get("carry") or {}
    gap_map: dict[str, float] = {}
    front_px: dict[str, float] = {}
    next_px: dict[str, float] = {}
    for day, pair in carry.items():
        day = str(day)
        g = carry_gap_pct(pair)
        if g is not None:
            gap_map[day] = float(g)
        try:
            front_px[day] = float(pair[0])
            next_px[day] = float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
    days = sorted(set(front_px) & set(next_px))
    basis_mom: dict[str, float] = {}
    for i, day in enumerate(days):
        if i < 20:
            continue
        d0 = days[i - 20]
        f0, f1 = front_px[d0], front_px[day]
        n0, n1 = next_px[d0], next_px[day]
        if f0 <= 0 or n0 <= 0:
            continue
        # Boons-style proxy: nearby mom − deferred mom (%)
        basis_mom[day] = (f1 / f0 - 1.0) * 100.0 - (n1 / n0 - 1.0) * 100.0
    return gap_map, basis_mom


def _member_dates_from_cache() -> list[str]:
    folder = ROOT / ".cache" / "member"
    if not folder.is_dir():
        return []
    days: set[str] = set()
    for path in folder.glob("*-????????.*"):
        stem = path.stem
        # czce-20251126 / shfe-20251126 / dce-20251126
        ymd = stem.split("-")[-1]
        if len(ymd) == 8 and ymd.isdigit():
            days.add(f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}")
    return sorted(days)


def _rolling_z_by_code(
    raw: dict[str, float], *, window: int = 60, min_periods: int = 40
) -> dict[str, float]:
    """Within-code rolling z on sorted dates (scale-free hedge pressure)."""
    series = sorted((str(d), float(v)) for d, v in raw.items())
    out: dict[str, float] = {}
    vals: list[float] = []
    for day, v in series:
        vals.append(v)
        if len(vals) < min_periods:
            continue
        chunk = vals[-window:] if len(vals) >= window else vals
        mu = sum(chunk) / len(chunk)
        var = sum((x - mu) ** 2 for x in chunk) / len(chunk)
        sd = math.sqrt(var) if var > 1e-18 else 0.0
        out[day] = 0.0 if sd <= 0 else (v - mu) / sd
    return out


def _load_hedge_pressure(codes: list[str]) -> dict[str, dict[str, float]]:
    """code -> {date -> within-code 60d rolling z of inst net lots}."""
    dates = _member_dates_from_cache()
    if not dates:
        return {c: {} for c in codes}
    try:
        from member_rank import load_member_seats
    except Exception:
        return {c: {} for c in codes}
    print(f"[factors] seats dates={len(dates)} codes={len(codes)}")
    books = load_member_seats(dates, codes)
    out: dict[str, dict[str, float]] = {}
    for code in codes:
        raw: dict[str, float] = {}
        for day, row in (books.get(code) or {}).items():
            try:
                raw[str(day)] = float(row.get("inst") or 0.0)
            except (TypeError, ValueError):
                continue
        out[code] = _rolling_z_by_code(raw, window=60, min_periods=40)
    return out


def main() -> int:
    bar_dir = LAB / "data" / "bars" / "continuous"
    out_dir = LAB / "data" / "factors"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in bar_dir.glob("*.json") if not p.name.startswith("."))
    codes = [json.loads(p.read_text(encoding="utf-8")).get("code") or p.stem for p in paths]
    codes = [str(c).upper() for c in codes]
    hedge = _load_hedge_pressure(codes)

    panel: list[dict] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        code = str(payload.get("code") or path.stem).upper()
        bars = payload.get("bars") or []
        closes = [float(b["close"]) for b in bars]
        gap_map, basis_mom = _load_carry_rich(code)
        hp_map = hedge.get(code) or {}
        print(
            f"[factors] {code} bars={len(bars)} carry={len(gap_map)} "
            f"basis_mom={len(basis_mom)} seats={len(hp_map)}"
        )
        for i, bar in enumerate(bars):
            day = str(bar.get("date") or "")
            vs = _ret_std(closes, i, 5)
            vm = _ret_std(closes, i, 20)
            vl = _ret_std(closes, i, 60)
            ratio = (vs / vl) if vs is not None and vl not in (None, 0) else None
            mom20 = _std_mom(closes, i, 20)
            mom_vol = None
            if mom20 is not None and vs not in (None, 0):
                mom_vol = mom20 / (vs * 100.0)  # mom% / daily-vol%
            skew = None
            if i >= 60:
                rets = []
                ok = True
                for j in range(i - 59, i + 1):
                    if closes[j - 1] <= 0:
                        ok = False
                        break
                    rets.append(closes[j] / closes[j - 1] - 1.0)
                if ok:
                    skew = _skew(rets)
            panel.append(
                {
                    "date": day,
                    "code": code,
                    "mom_20": mom20,
                    "mom_60": _std_mom(closes, i, 60),
                    "vol_s": None if vs is None else vs * 100.0,
                    "vol_m": None if vm is None else vm * 100.0,
                    "vol_l": None if vl is None else vl * 100.0,
                    "vol_ratio_sl": ratio,
                    "carry_gap_pct": gap_map.get(day),
                    "basis_mom_20": basis_mom.get(day),
                    "skew_60": skew,
                    "mom_vol_20": mom_vol,
                    "hedge_pressure": hp_map.get(day),
                    "warrant_w": None,
                }
            )
    out_path = out_dir / "panel_daily.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for row in panel:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    # coverage
    cov = {}
    for fac in FACTOR_LIST:
        n = sum(1 for r in panel if r.get(fac) is not None)
        cov[fac] = {"non_null": n, "pct": round(100.0 * n / max(1, len(panel)), 2)}
    meta = {
        "ok": True,
        "rows": len(panel),
        "path": str(out_path).replace("\\", "/"),
        "factors": FACTOR_LIST,
        "coverage": cov,
        "hedge_pressure_transform": "within_code_rolling_z_60d_min40",
    }
    (out_dir / "panel_daily_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[factors] rows={len(panel)} → {out_path}")
    for fac, c in cov.items():
        print(f"  cover {fac}: {c['non_null']} ({c['pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
