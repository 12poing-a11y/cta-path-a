# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab.gamma.iv_oi import iv_oi_joint_series
from lab.gamma.migration import classify_wall_migration
from lab.gamma.touch_study import touch_event_study

ROOT = Path(__file__).resolve().parents[2]


def _load_daily_for_product(root: Path, product: str) -> list[dict]:
    """Prefer continuous CODE0 history cache; else gamma exact-contract daily."""
    # Try history continuous
    for cand in (
        root / ".cache" / "history" / f"{product.upper()}0.json",
        root / "lab" / "data" / "bars" / "continuous" / f"{product.upper()}.json",
    ):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                bars = data if isinstance(data, list) else data.get("bars") or data.get("hist") or []
                out = []
                for b in bars:
                    if not isinstance(b, dict):
                        continue
                    d = str(b.get("date") or b.get("datetime") or "")[:10]
                    if len(d) != 10:
                        continue
                    try:
                        out.append(
                            {
                                "date": d,
                                "open": float(b["open"]),
                                "high": float(b["high"]),
                                "low": float(b["low"]),
                                "close": float(b["close"]),
                            }
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                if len(out) >= 30:
                    return out
            except Exception:
                pass
    # Fallback: gamma raw futures daily
    fut = root / ".cache" / "gamma_wall" / "raw" / f"{product.upper()}2701_daily.json"
    # contract month varies — glob
    matches = sorted((root / ".cache" / "gamma_wall" / "raw").glob(f"{product.upper()}*_daily.json"))
    if matches:
        try:
            data = json.loads(matches[-1].read_text(encoding="utf-8"))
            bars = data if isinstance(data, list) else data.get("bars") or data.get("hist") or []
            out = []
            for b in bars:
                if not isinstance(b, dict):
                    continue
                d = str(b.get("date") or b.get("datetime") or b.get("日") or "")[:10]
                if len(d) < 8:
                    continue
                # normalize
                if len(d) == 8 and d.isdigit():
                    d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                try:
                    out.append(
                        {
                            "date": d[:10],
                            "open": float(b.get("open") or b.get("开盘价") or b["close"]),
                            "high": float(b.get("high") or b.get("最高价") or b["close"]),
                            "low": float(b.get("low") or b.get("最低价") or b["close"]),
                            "close": float(b.get("close") or b.get("收盘价")),
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            return out
        except Exception:
            return []
    return []


def run_gamma_research(contract: str = "CF2701", *, root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    product = "".join(ch for ch in contract if ch.isalpha()).upper()
    mig = classify_wall_migration(contract, root=root)
    daily = _load_daily_for_product(root, product)
    touch = (
        touch_event_study(contract, daily, touch_atr=3.0, root=root)
        if daily
        else {
            "ok": False,
            "error": "no_daily_bars",
            "n_events": 0,
        }
    )
    ivoi = iv_oi_joint_series(product, root=root)
    return {
        "ok": True,
        "schema": "cta-gamma-research-v1",
        "contract": contract.upper(),
        "product": product,
        "migration": mig,
        "touch": touch,
        "iv_oi": ivoi,
        "n_daily_bars": len(daily),
        "live_trading": False,
        "status": "Research",
        "disclaimer": (
            "Call+/Put− GEX 为展示约定；OI 不能识别做市商方向。"
            "本模块只做结构观察，不生成 Path-A 多空信号。"
        ),
    }


def save_gamma_research(payload: dict[str, Any], root: Path | None = None) -> str:
    root = root or ROOT
    out_dir = root / "lab" / "research" / "gamma"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Slim events in latest
    slim = dict(payload)
    if isinstance(slim.get("migration"), dict) and "events" in slim["migration"]:
        mig = dict(slim["migration"])
        mig["events_tail"] = (mig.get("events") or [])[-40:]
        mig.pop("events", None)
        mig.pop("series", None)
        slim["migration"] = mig
    if isinstance(slim.get("touch"), dict) and "events" in slim["touch"]:
        t = dict(slim["touch"])
        t["events_tail"] = (t.get("events") or [])[-40:]
        t.pop("events", None)
        slim["touch"] = t
    if isinstance(slim.get("iv_oi"), dict):
        iv = dict(slim["iv_oi"])
        iv["changes_tail"] = (iv.get("changes") or [])[-40:]
        iv.pop("changes", None)
        iv.pop("series", None)
        slim["iv_oi"] = iv
    path = out_dir / f"gamma_{payload.get('contract')}_latest.json"
    path.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path.relative_to(root))
