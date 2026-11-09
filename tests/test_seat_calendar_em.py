# -*- coding: utf-8 -*-
"""EM underlay counts for desk seat calendar / joint skip."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.regime_board import joint_skip_reason  # noqa: E402
from desk.seat_board import seat_calendar_dates  # noqa: E402


def test_seat_calendar_includes_em_only(tmp_path: Path):
    member = tmp_path / ".cache" / "member"
    member.mkdir(parents=True)
    (member / "em-20261029.json").write_text(
        json.dumps({"products": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    dates = seat_calendar_dates(tmp_path, "DCE")
    assert "20261029" in dates
    report = {"signals": [{"code": "M", "ticker": "m2501"}]}
    assert joint_skip_reason(tmp_path, "M", report) is None


def test_joint_skip_when_no_member_files(tmp_path: Path):
    (tmp_path / ".cache" / "member").mkdir(parents=True)
    report = {"signals": [{"code": "M", "ticker": "m2501"}]}
    reason = joint_skip_reason(tmp_path, "M", report)
    assert reason is not None
    assert "em" in reason.lower() or "dce" in reason.lower()
