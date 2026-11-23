# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

from virtual_portfolio.guard import assert_vp_write_path, vp_data_root

_ACCOUNT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{1,63}$")


def validate_account_id(account_id: str) -> str:
    aid = str(account_id or "").strip()
    if not _ACCOUNT_RE.match(aid):
        raise ValueError(
            "account_id must be 2–64 chars [A-Za-z0-9_-], starting alphanumeric"
        )
    return aid


def account_dir(root: Path, account_id: str, *, create: bool = False) -> Path:
    aid = validate_account_id(account_id)
    d = vp_data_root(root) / aid
    if create:
        assert_vp_write_path(d, root)
        d.mkdir(parents=True, exist_ok=True)
        assert_vp_write_path(d, root)
    return d


def ledger_path(root: Path, account_id: str) -> Path:
    return account_dir(root, account_id) / "ledger.jsonl"


def account_json_path(root: Path, account_id: str) -> Path:
    return account_dir(root, account_id) / "account.json"


def positions_json_path(root: Path, account_id: str) -> Path:
    return account_dir(root, account_id) / "positions.json"


def equity_json_path(root: Path, account_id: str) -> Path:
    return account_dir(root, account_id) / "equity.json"


def signal_inbox_dir(root: Path, *, create: bool = False) -> Path:
    d = vp_data_root(root) / "signal_inbox"
    if create:
        assert_vp_write_path(d, root)
        d.mkdir(parents=True, exist_ok=True)
        assert_vp_write_path(d, root)
    return d


def signal_inbox_latest_path(root: Path) -> Path:
    return signal_inbox_dir(root) / "latest.json"


def signal_inbox_by_asof_path(root: Path, asof: str) -> Path:
    return signal_inbox_dir(root) / "by_asof" / f"{asof}.json"


def signal_inbox_events_path(root: Path) -> Path:
    return signal_inbox_dir(root) / "events.jsonl"


def signal_inbox_rejects_path(root: Path) -> Path:
    return signal_inbox_dir(root) / "rejects.jsonl"


def vp_runtime_path(root: Path) -> Path:
    """Operational flags under VP data namespace (fail-closed if missing)."""
    return vp_data_root(root) / "runtime.json"
