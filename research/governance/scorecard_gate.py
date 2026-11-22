# -*- coding: utf-8 -*-
"""Derive strategy-gate booleans from formal BT / PBO artifacts (T-GV / GV-01).

Never self-reports pass; never mutates execution_rules / paper_book / seats.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.governance.strategy_gate import evaluate_strategy_gate

ROOT = Path(__file__).resolve().parents[2]
BT_REL = Path("historical_backtest_latest.json")
PBO_REL = Path("lab") / "research" / "validation" / "pbo_path_a_latest.json"
SCORECARD_REL = Path("lab") / "research" / "validation" / "formal_scorecard_latest.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def has_stress_contrast(bt: dict[str, Any] | None) -> bool:
    if not bt:
        return False
    contrast = bt.get("cost_scenario_contrast") or {}
    if not contrast.get("ok"):
        return False
    rows = contrast.get("rows") or {}
    return "stress" in rows or any(
        str(k).lower() == "stress" for k in (rows.keys() if isinstance(rows, dict) else [])
    )


def validation_from_artifacts(
    bt: dict[str, Any] | None,
    pbo: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the validation blob evaluate_strategy_gate expects — from files only."""
    psr = None
    dsr = None
    pbo_val: dict[str, Any] = {"error": "pbo_artifact_missing"}
    if pbo:
        block = pbo.get("pbo") if isinstance(pbo.get("pbo"), dict) else None
        if block is not None:
            pbo_val = {"pbo": block.get("pbo"), "n_obs": block.get("n_obs"), "n_trials": block.get("n_trials")}
        elif pbo.get("pbo") is not None:
            pbo_val = {"pbo": pbo.get("pbo")}
        else:
            pbo_val = {"error": str((pbo.get("pbo") or {}).get("error") or "pbo_missing")}
        psr_primary = pbo.get("psr_primary") or {}
        dsr_primary = pbo.get("dsr_primary") or {}
        if isinstance(psr_primary, dict) and psr_primary.get("psr") is not None:
            psr = psr_primary.get("psr")
        if isinstance(dsr_primary, dict) and dsr_primary.get("dsr") is not None:
            dsr = dsr_primary.get("dsr")
    return {
        "psr": {"psr": psr},
        "dsr": {"dsr": dsr},
        "pbo": pbo_val,
        "source": "artifacts",
        "bt_schema": (bt or {}).get("schema_version"),
        "proxy_entry_share": (bt or {}).get("proxy_entry_share"),
    }


def derive_gate_flags(
    bt: dict[str, Any] | None,
    pbo: dict[str, Any] | None,
    *,
    human_approved: bool = False,
    beats_path_a: bool | None = None,
) -> dict[str, Any]:
    has_oos = bool(
        pbo
        and (
            (isinstance(pbo.get("pbo"), dict) and pbo["pbo"].get("pbo") is not None)
            or (pbo.get("pbo") is not None and not isinstance(pbo.get("pbo"), dict))
            or (pbo.get("matrix_meta") or {}).get("n_obs")
        )
    )
    return {
        "has_oos": has_oos,
        "has_cost_stress": has_stress_contrast(bt),
        "beats_path_a": beats_path_a,
        "human_approved": bool(human_approved),
    }


def artifact_build_ok(gate: dict[str, Any]) -> bool:
    """Engineering completeness for scorecard write — human_approval is not a build blocker."""
    blocking = [x for x in (gate.get("hard_failures") or []) if x != "human_approval"]
    return len(blocking) == 0


def evaluate_from_artifacts(
    root: Path | None = None,
    *,
    human_approved: bool = False,
    beats_path_a: bool | None = None,
) -> dict[str, Any]:
    root = Path(root or ROOT)
    bt = _load_json(root / BT_REL)
    pbo = _load_json(root / PBO_REL)
    validation = validation_from_artifacts(bt, pbo)
    flags = derive_gate_flags(
        bt, pbo, human_approved=human_approved, beats_path_a=beats_path_a
    )
    gate = evaluate_strategy_gate(validation, **flags)
    gate["artifact_build_ok"] = artifact_build_ok(gate)
    gate["flags"] = flags
    gate["validation"] = validation
    gate["artifacts"] = {
        "bt_present": bt is not None,
        "pbo_present": pbo is not None,
        "bt_path": str(BT_REL),
        "pbo_path": str(PBO_REL).replace("\\", "/"),
        "stress_ok": flags["has_cost_stress"],
    }
    return gate


def attach_gate_to_scorecard(
    card: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    out = dict(card)
    out["gate"] = {
        "schema": gate.get("schema"),
        "pass": gate.get("pass"),
        "auto_promote": False,
        "artifact_build_ok": gate.get("artifact_build_ok"),
        "hard_failures": gate.get("hard_failures"),
        "checks": gate.get("checks"),
        "flags": gate.get("flags"),
        "artifacts": gate.get("artifacts"),
        "note": gate.get("note"),
    }
    # Formal scorecard ok requires engineering artifacts; never auto-promote.
    out["ok"] = bool(card.get("ok", True)) and bool(gate.get("artifact_build_ok"))
    out["live_trading"] = False
    if not out["ok"]:
        out["note"] = (
            str(card.get("note") or "")
            + " | GATE BUILD FAIL: "
            + ",".join(gate.get("hard_failures") or [])
        ).strip(" |")
    return out


def refresh_scorecard_gate(
    root: Path | None = None,
    *,
    human_approved: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    """Re-attach gate to existing formal_scorecard_latest.json without re-running BT."""
    root = Path(root or ROOT)
    path = root / SCORECARD_REL
    card = _load_json(path) or {
        "ok": True,
        "schema": "cta-formal-scorecard-v1",
        "purpose": "gate-only refresh",
        "live_trading": False,
    }
    gate = evaluate_from_artifacts(root, human_approved=human_approved)
    card = attach_gate_to_scorecard(card, gate)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "card": card, "gate": gate}
