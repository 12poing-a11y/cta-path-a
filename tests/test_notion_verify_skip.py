# -*- coding: utf-8 -*-
"""Daily Notion verify must pass on a weekend skip marker (no signals, no failure)."""
from __future__ import annotations

import json

import notion_sync


def test_verify_skip_marker_passes_without_notion_or_quality(tmp_path, monkeypatch):
    monkeypatch.setattr(notion_sync, "ROOT", tmp_path)
    report = tmp_path / "l1_report_risk15.json"
    report.write_text(json.dumps({"asof": "20261128", "skipped": "weekend"}), encoding="utf-8")

    def _boom(*_a, **_k):  # any Notion query on a skipped day is a bug
        raise AssertionError("notion should not be queried on a skipped run")

    monkeypatch.setattr(notion_sync, "_verify_signal_pages_with_retry", _boom)
    result = notion_sync.verify_signals(report)

    assert result["ok"] is True
    assert result["skipped"] == "weekend"
    written = json.loads((tmp_path / "notion_daily_quality.json").read_text(encoding="utf-8"))
    assert written["ok"] is True and written["skipped"] == "weekend"
