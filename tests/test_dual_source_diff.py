# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.data_quality.dual_source_diff import (  # noqa: E402
    build_report,
    diff_bars,
    diff_seat_product,
    write_report,
)


def test_diff_bars_flags_mismatch_and_fill():
    free = [
        {"date": "2026-11-18", "close": 100.0},
        {"date": "2026-11-19", "close": 101.0},
    ]
    hist = [
        {"date": "2026-11-18", "close": 100.0},
        {"date": "2026-11-19", "close": 105.0},  # >0.15%
        {"date": "2026-11-20", "close": 106.0},  # history-only fill
    ]
    row = diff_bars(
        "CF",
        free,
        hist,
        lookback_days=30,
        close_tol_pct=0.15,
        asof=__import__("datetime").date(2026, 11, 20),
    )
    assert row["status"] == "mismatch"
    assert row["mismatch_n"] >= 1
    assert row["paid_fill_suspected"] is True
    assert "2026-11-20" in row["only_history_sample"]


def test_diff_seat_product_kind_delta():
    em = {
        "n": 20,
        "source": "eastmoney.RPT_FUTU_DAILYPOSITION",
        # 永安/中信 → inst
        "longs": [["永安期货", 100.0], ["中信期货", 50.0]],
        "shorts": [["永安期货", 20.0], ["中信期货", 40.0]],
    }
    ex = {"inst": 50.0, "foreign": 0.0, "holder": 0.0}  # em inst = 90
    row = diff_seat_product("MA", em, ex, net_tol=1.0)
    assert row["status"] == "mismatch"
    assert row["kind_diff_n"] >= 1


def test_build_report_cache_only_no_paid(tmp_path: Path):
    (tmp_path / "universe.json").write_text(
        json.dumps({"symbols": [{"code": "CF"}, {"code": "MA"}]}),
        encoding="utf-8",
    )
    hist_dir = tmp_path / ".cache" / "history"
    hist_dir.mkdir(parents=True)
    (hist_dir / "CF0.json").write_text(
        json.dumps([{"date": "2026-11-19", "close": 100.0}]),
        encoding="utf-8",
    )
    member = tmp_path / ".cache" / "member"
    member.mkdir(parents=True)
    (member / "em-20261119.json").write_text(
        json.dumps(
            {
                "ymd": "20261119",
                "products": {
                    "CF": {
                        "n": 20,
                        "source": "sina.futures_hold_pos_sina",
                        "longs": [["永安期货", 1]],
                        "shorts": [["中信期货", 1]],
                    },
                    "MA": {
                        "n": 20,
                        "source": "eastmoney.RPT_FUTU_DAILYPOSITION",
                        "longs": [["永安期货", 1]],
                        "shorts": [["中信期货", 1]],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    report = build_report(
        tmp_path,
        codes=["CF", "MA"],
        fetch_free=False,
        allow_paid=True,  # must still force paid_calls=0
        seat_ymd="20261119",
    )
    assert report["allow_paid"] is False
    assert report["summary"]["paid_calls"] == 0
    assert report["seat_fill"].get("CF") == "sina"
    path = write_report(report, tmp_path)
    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["schema_version"].startswith("cta-dual-source-diff")
