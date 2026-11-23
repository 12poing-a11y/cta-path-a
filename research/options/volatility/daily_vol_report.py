# -*- coding: utf-8 -*-
"""Daily vol-engine report (Vol-V1.4 · shadow only · no trade instructions)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.options.chain_store import list_snapshot_dates, load_snapshot
from research.options.volatility.greeks_engine import vanilla_greeks
from research.options.volatility.iv_surface import build_iv_surface
from research.options.volatility.shadow_greeks import shadow_greeks_for_point

SCHEMA = "cta-vol-engine-daily-v1"
MODEL_VERSION = "vol_engine_v1.4"
OUT_REL = Path("lab") / "research" / "volatility" / "vol_engine_daily_latest.json"
DEFAULT_CODES = ("CF", "SR", "MA")
# ATM ±N strikes for Shadow Greeks (monitor sample; full chain still in surface)
SHADOW_ATM_BAND = 3


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _atm_sample(points: list[dict[str, Any]], futures: float, *, band: int = SHADOW_ATM_BAND) -> list[dict[str, Any]]:
    ok = [p for p in points if p.get("status") == "OK" and p.get("iv") is not None]
    if not ok or futures <= 0:
        return []
    by_side: dict[str, list[dict[str, Any]]] = {"C": [], "P": []}
    for p in ok:
        side = str(p.get("side") or "").upper()
        if side in by_side:
            by_side[side].append(p)
    out: list[dict[str, Any]] = []
    for side, rows in by_side.items():
        rows_sorted = sorted(rows, key=lambda r: abs(float(r["strike"]) - futures))
        out.extend(rows_sorted[: max(1, band)])
    return out


def build_report_for_snapshot(snap: dict[str, Any], *, rate: float = 0.02) -> dict[str, Any]:
    surface = build_iv_surface(snap, rate=rate)
    if not surface.get("ok"):
        return {
            "ok": False,
            "code": surface.get("code"),
            "asof": surface.get("asof"),
            "error": surface.get("error") or "surface_empty",
            "surface": surface,
            "legs": [],
            "live_trading": False,
            "promote_path_a": False,
        }
    F = float(surface["futures"])
    years = float(surface["years"])
    points = surface.get("points") or []
    sample = _atm_sample(points, F)
    legs_out: list[dict[str, Any]] = []
    for p in sample:
        side = str(p["side"]).upper()
        K = float(p["strike"])
        iv = float(p["iv"])
        try:
            vg = vanilla_greeks(
                futures=F, strike=K, years=years, rate=rate, iv=iv, side=side
            )
            sg = shadow_greeks_for_point(
                futures=F,
                strike=K,
                years=years,
                rate=rate,
                side=side,
                iv=iv,
                surface_points=points,
            )
        except Exception as exc:  # noqa: BLE001
            legs_out.append(
                {
                    "symbol": p.get("symbol"),
                    "side": side,
                    "strike": K,
                    "status": "FAIL",
                    "reason": str(exc)[:120],
                }
            )
            continue
        legs_out.append(
            {
                "symbol": p.get("symbol"),
                "side": side,
                "strike": K,
                "status": "OK",
                "premium": p.get("premium"),
                "premium_source": p.get("premium_source"),
                "vanilla": vg,
                "shadow": sg,
            }
        )
    return {
        "ok": True,
        "code": surface["code"],
        "asof": surface["asof"],
        "futures": F,
        "years": years,
        "expiry": surface.get("expiry"),
        "quality": surface.get("quality"),
        "warnings": list(surface.get("warnings") or []),
        "n_surface_ok": surface.get("n_ok"),
        "n_surface_fail": surface.get("n_fail"),
        "n_shadow_legs": len(legs_out),
        "surface_summary": {
            "n_ok": surface.get("n_ok"),
            "n_skip": surface.get("n_skip"),
            "n_fail": surface.get("n_fail"),
            "quality": surface.get("quality"),
        },
        "legs": legs_out,
        "live_trading": False,
        "promote_path_a": False,
    }


def build_daily_vol_report(
    root: Path,
    *,
    codes: list[str] | tuple[str, ...] | None = None,
    asof: str | None = None,
    rate: float = 0.02,
    write: bool = True,
) -> dict[str, Any]:
    """Build multi-code daily vol engine report from option chain snapshots."""
    root = Path(root)
    codes_u = [str(c).upper() for c in (codes or DEFAULT_CODES)]
    products: list[dict[str, Any]] = []
    for code in codes_u:
        dates = list_snapshot_dates(root, code)
        if not dates:
            products.append(
                {
                    "ok": False,
                    "code": code,
                    "asof": asof,
                    "error": "no_snapshots",
                    "legs": [],
                    "live_trading": False,
                    "promote_path_a": False,
                }
            )
            continue
        use_asof = str(asof)[:10] if asof else dates[-1]
        snap = load_snapshot(root, code, use_asof)
        if snap is None:
            products.append(
                {
                    "ok": False,
                    "code": code,
                    "asof": use_asof,
                    "error": "snapshot_missing",
                    "legs": [],
                    "live_trading": False,
                    "promote_path_a": False,
                }
            )
            continue
        products.append(build_report_for_snapshot(snap, rate=rate))

    n_ok = sum(1 for p in products if p.get("ok"))
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "model_version": MODEL_VERSION,
        "ok": n_ok > 0,
        "built_at": _iso_now(),
        "asof_requested": asof,
        "codes": codes_u,
        "n_ok": n_ok,
        "n_fail": len(products) - n_ok,
        "products": products,
        "live_trading": False,
        "promote_path_a": False,
        "note": "shadow_monitor_only_no_trade_instructions",
    }
    if write:
        out = root / OUT_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        report["path"] = str(OUT_REL).replace("\\", "/")
    return report


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Vol-V1.4 daily report (shadow)")
    ap.add_argument("--root", default=".", help="repo root")
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD (default: latest per code)")
    ap.add_argument("--codes", default="CF,SR,MA", help="comma-separated")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    codes = [c.strip() for c in str(args.codes).split(",") if c.strip()]
    rep = build_daily_vol_report(
        Path(args.root),
        codes=codes,
        asof=args.asof,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "ok": rep.get("ok"),
                "n_ok": rep.get("n_ok"),
                "path": rep.get("path"),
                "live_trading": False,
                "promote_path_a": False,
                "products": [
                    {
                        "code": p.get("code"),
                        "asof": p.get("asof"),
                        "ok": p.get("ok"),
                        "quality": p.get("quality"),
                        "n_shadow_legs": p.get("n_shadow_legs"),
                        "error": p.get("error"),
                    }
                    for p in (rep.get("products") or [])
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
