# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from desk.npd_panel import load_npd_reminders


def test_repo_seed_events_fire_only_on_wasde_entry_day(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    # Seed WASDE published BJ 2026-11-11 → entry 2026-11-12
    on = load_npd_reminders(root, asof="2026-11-12")
    assert on.get("ok") is True
    assert on.get("is_entry_day") is True
    assert on.get("counts_toward_score") is False
    ids = {r.get("event_id") for r in on.get("reminders") or []}
    assert "USDA-WASDE-2026-11" in ids

    off = load_npd_reminders(root, asof="2026-11-13")
    assert off.get("is_entry_day") is False


def test_missing_events_file_is_silent(tmp_path: Path):
    pack = load_npd_reminders(tmp_path, asof="2026-11-12")
    assert pack.get("is_entry_day") is False
    assert pack.get("n") == 0
