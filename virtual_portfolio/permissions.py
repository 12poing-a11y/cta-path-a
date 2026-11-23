# -*- coding: utf-8 -*-
"""VP runtime mode & execution permissions — fail closed."""
from __future__ import annotations

from typing import Any

# Defaults when config/fields missing: deny automation.
DEFAULT_ACCOUNT_MODE = "RESEARCH_ONLY"
DEFAULT_MARGIN_STATUS = "UNVERIFIED"
DEFAULT_AUTO_OPEN_ALLOWED = False
DEFAULT_AUTO_CLOSE_ALLOWED = False
DEFAULT_SIGNAL_INGEST_ALLOWED = False

ALLOWED_ACCOUNT_MODES = frozenset({"RESEARCH_ONLY", "PAPER_SIM", "LIVE_SHADOW"})


class VpPermissionError(PermissionError):
    """Raised when an operation is blocked by runtime permissions."""


def default_runtime_flags() -> dict[str, Any]:
    return {
        "ACCOUNT_MODE": DEFAULT_ACCOUNT_MODE,
        "MARGIN_STATUS": DEFAULT_MARGIN_STATUS,
        "AUTO_OPEN_ALLOWED": DEFAULT_AUTO_OPEN_ALLOWED,
        "AUTO_CLOSE_ALLOWED": DEFAULT_AUTO_CLOSE_ALLOWED,
        "SIGNAL_INGEST_ALLOWED": DEFAULT_SIGNAL_INGEST_ALLOWED,
    }


def coerce_bool(val: Any, *, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off", ""):
        return False
    return default


def resolve_runtime(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Merge account meta with fail-closed defaults. Missing → deny automation."""
    m = meta or {}
    mode = str(m.get("ACCOUNT_MODE") or DEFAULT_ACCOUNT_MODE).upper()
    if mode not in ALLOWED_ACCOUNT_MODES:
        mode = DEFAULT_ACCOUNT_MODE
    margin = str(m.get("MARGIN_STATUS") or DEFAULT_MARGIN_STATUS).upper()
    if margin not in ("UNVERIFIED", "VERIFIED", "MISSING", "EXPIRED"):
        margin = DEFAULT_MARGIN_STATUS
    return {
        "ACCOUNT_MODE": mode,
        "MARGIN_STATUS": margin,
        "AUTO_OPEN_ALLOWED": coerce_bool(
            m.get("AUTO_OPEN_ALLOWED"), default=DEFAULT_AUTO_OPEN_ALLOWED
        ),
        "AUTO_CLOSE_ALLOWED": coerce_bool(
            m.get("AUTO_CLOSE_ALLOWED"), default=DEFAULT_AUTO_CLOSE_ALLOWED
        ),
        "SIGNAL_INGEST_ALLOWED": coerce_bool(
            m.get("SIGNAL_INGEST_ALLOWED"), default=DEFAULT_SIGNAL_INGEST_ALLOWED
        ),
    }


def assert_manual_ops_allowed(runtime: dict[str, Any]) -> None:
    """Phase 1A manual/SYSTEM_TEST path — allowed in RESEARCH_ONLY."""
    mode = runtime.get("ACCOUNT_MODE")
    if mode not in ALLOWED_ACCOUNT_MODES:
        raise VpPermissionError(f"ACCOUNT_MODE blocked: {mode}")


def assert_auto_open_allowed(runtime: dict[str, Any]) -> None:
    if not runtime.get("AUTO_OPEN_ALLOWED"):
        raise VpPermissionError("AUTO_OPEN_ALLOWED=false (fail-closed)")
    if runtime.get("MARGIN_STATUS") != "VERIFIED":
        raise VpPermissionError("auto open requires MARGIN_STATUS=VERIFIED")
    if not runtime.get("SIGNAL_INGEST_ALLOWED"):
        raise VpPermissionError("SIGNAL_INGEST_ALLOWED=false (fail-closed)")


def assert_auto_close_allowed(runtime: dict[str, Any]) -> None:
    if not runtime.get("AUTO_CLOSE_ALLOWED"):
        raise VpPermissionError("AUTO_CLOSE_ALLOWED=false (fail-closed)")


def assert_signal_ingest_allowed(runtime: dict[str, Any]) -> None:
    if not runtime.get("SIGNAL_INGEST_ALLOWED"):
        raise VpPermissionError("SIGNAL_INGEST_ALLOWED=false (fail-closed)")


def derive_margin_status(flags: list[str] | set[str], *, verified_any: bool) -> str:
    fs = {str(x) for x in (flags or [])}
    if "MARGIN_DATA_MISSING" in fs:
        return "MISSING"
    if verified_any:
        return "VERIFIED"
    return "UNVERIFIED"
