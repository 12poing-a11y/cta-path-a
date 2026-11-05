# -*- coding: utf-8 -*-
import notion_sync


def test_signal_verify_retries_transient_missing_page(monkeypatch):
    results = iter(
        [
            {"ok": False, "missing": ["SS"], "duplicates": {}, "unexpected": []},
            {"ok": True, "missing": [], "duplicates": {}, "unexpected": []},
        ]
    )
    calls = []
    sleeps = []
    monkeypatch.setattr(
        notion_sync, "_verify_signal_pages",
        lambda date, expected, slot: (calls.append((date, expected, slot)) or next(results)),
    )
    monkeypatch.setattr(notion_sync.time, "sleep", sleeps.append)

    result = notion_sync._verify_signal_pages_with_retry(
        "2026-11-05", {"CF", "SS"}, "backup", retry_delays=(1, 2)
    )

    assert result["ok"] is True
    assert len(calls) == 2
    assert sleeps == [1]


def test_signal_verify_keeps_hard_failure_after_retries(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(
        notion_sync, "_verify_signal_pages",
        lambda date, expected, slot: (
            calls.append((date, expected, slot))
            or {"ok": False, "missing": ["SS"], "duplicates": {}, "unexpected": []}
        ),
    )
    monkeypatch.setattr(notion_sync.time, "sleep", sleeps.append)

    result = notion_sync._verify_signal_pages_with_retry(
        "2026-11-05", {"CF", "SS"}, "backup", retry_delays=(1, 2, 4)
    )

    assert result["ok"] is False
    assert len(calls) == 4
    assert sleeps == [1, 2, 4]
