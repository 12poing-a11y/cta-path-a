# -*- coding: utf-8 -*-
"""Stage-2 hook: regime → which paper sleeves are enabled (rules only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CFG_PATH = ROOT / "regime_enable.json"


def load_regime_enable(root: Path | None = None) -> dict[str, Any]:
    path = (root or ROOT) / "regime_enable.json"
    if not path.is_file():
        return {"live_trading": False, "rules": [], "default_regime": "mixed"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"live_trading": False, "rules": [], "default_regime": "mixed"}


def normalize_regime(label: str | None, cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or load_regime_enable()
    text = str(label or "").strip()
    if not text:
        return str(cfg.get("default_regime") or "mixed")
    mapped = (cfg.get("label_map") or {}).get(text)
    if mapped:
        return str(mapped)
    if text in (cfg.get("regimes") or []):
        return text
    # Heuristics from desk Chinese / English crumbs
    if "强趋" in text or text.lower() in ("strong_trend",):
        return "strong_trend"
    if "强震" in text or "chop_strong" in text.lower():
        return "chop_strong"
    if "震" in text or "chop" in text.lower():
        return "chop"
    if "趋" in text or "trend" in text.lower() or text in ("偏多", "偏空", "多", "空"):
        return "trend"
    return str(cfg.get("default_regime") or "mixed")


def enabled_sleeves(
    regime_label: str | None,
    *,
    root: Path | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return enabled rule rows for the normalized regime."""
    cfg = cfg or load_regime_enable(root)
    regime = normalize_regime(regime_label, cfg)
    out: list[dict[str, Any]] = []
    for rule in cfg.get("rules") or []:
        sleeve = str(rule.get("sleeve") or "")
        if not sleeve:
            continue
        disable = set(rule.get("disable_when") or [])
        enable = set(rule.get("enable_when") or [])
        if regime in disable:
            continue
        if enable and regime not in enable:
            continue
        out.append(
            {
                "sleeve": sleeve,
                "role": rule.get("role"),
                "regime": regime,
                "enabled": True,
                "note": rule.get("note"),
            }
        )
    return out


def enable_matrix_table(
    regime_label: str | None = None,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Full sleeve × current-regime enable flags for desk display."""
    cfg = load_regime_enable(root)
    regime = normalize_regime(regime_label, cfg)
    enabled_ids = {r["sleeve"] for r in enabled_sleeves(regime, cfg=cfg)}
    rows: list[dict[str, Any]] = []
    for rule in cfg.get("rules") or []:
        sleeve = str(rule.get("sleeve") or "")
        rows.append(
            {
                "sleeve": sleeve,
                "role": rule.get("role"),
                "regime": regime,
                "enabled": sleeve in enabled_ids,
                "enable_when": ",".join(rule.get("enable_when") or []),
                "disable_when": ",".join(rule.get("disable_when") or []),
            }
        )
    return rows


def infer_regime_from_pack(pack: dict[str, Any] | None) -> str:
    """Lightweight infer from desk pack / decision crumbs; default mixed."""
    if not pack:
        return "mixed"
    for key in ("regime_label", "state", "bucket", "dir_name", "综合方向"):
        if pack.get(key):
            return normalize_regime(str(pack.get(key)))
    decision = pack.get("decision") if isinstance(pack.get("decision"), dict) else {}
    for key in ("stance", "dir", "方向", "label"):
        if decision.get(key):
            return normalize_regime(str(decision.get(key)))
    return "mixed"
