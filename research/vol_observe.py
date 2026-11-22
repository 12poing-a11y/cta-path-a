# -*- coding: utf-8 -*-
"""V-旁路：分品种下行 HV + 容忍带观察（Research only · 不写 position_rules）.

Reuses gemini_tvs_shadow math; emits a desk-readable snapshot.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.gemini_tvs_shadow import apply_tolerance, downside_hv_ann

SCHEMA = "cta-vol-observe-v1"
OUT_REL = Path("lab") / "research" / "vol_observe_latest.json"


def _leverage_from_downside_hv(
    hv: float | None, *, target_vol: float = 0.15, max_leverage: float = 1.5
) -> float | None:
    if hv is None or hv <= 0:
        return None
    return max(0.0, min(float(max_leverage), float(target_vol) / float(hv)))


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _closes(root: Path, code: str) -> list[float]:
    path = Path(root) / ".cache" / "history" / f"{str(code).upper()}0.json"
    if not path.is_file():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    px: list[float] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            c = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if c > 0:
            px.append(c)
    return px


def _rets(px: list[float]) -> list[float]:
    out = []
    for i in range(1, len(px)):
        if px[i - 1] > 0:
            out.append(px[i] / px[i - 1] - 1.0)
    return out


def build_vol_observe(
    root: Path,
    codes: list[str] | None = None,
    *,
    target_vol: float = 0.15,
    band: float = 0.05,
    write: bool = True,
) -> dict[str, Any]:
    root = Path(root)
    if codes is None:
        uni = root / "universe.json"
        codes = []
        if uni.is_file():
            try:
                cfg = json.loads(uni.read_text(encoding="utf-8"))
                codes = [
                    str(r.get("code")).upper()
                    for r in (cfg.get("symbols") or [])
                    if isinstance(r, dict) and r.get("code")
                ]
            except (OSError, json.JSONDecodeError):
                codes = []
    rows = []
    for code in codes:
        px = _closes(root, code)
        rets = _rets(px)
        hv = downside_hv_ann(rets, window=20) if len(rets) >= 20 else None
        target = _leverage_from_downside_hv(hv, target_vol=target_vol)
        sug = apply_tolerance(1.0, float(target), band=band) if target is not None else None
        rows.append(
            {
                "code": code,
                "downside_hv": None if hv is None else round(float(hv), 6),
                "target_leverage": None if target is None else round(float(target), 4),
                "suggested_leverage_band": None if sug is None else round(float(sug), 4),
                "n_rets": len(rets),
            }
        )
    rows.sort(key=lambda r: (-(r["downside_hv"] or 0.0), r["code"]))
    report = {
        "ok": True,
        "schema": SCHEMA,
        "built_at": _iso_now(),
        "live_trading": False,
        "promote_path_a": False,
        "target_vol": target_vol,
        "tolerance_band": band,
        "n": len(rows),
        "rows": rows,
        "note": (
            "观察旁路：分品种下行 HV → 杠杆建议；±band 容忍。"
            "不写 position_rules / paper_book / seats。"
        ),
    }
    if write:
        out = root / OUT_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["path"] = str(out.relative_to(root))
    return report
