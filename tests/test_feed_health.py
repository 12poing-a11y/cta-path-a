# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from desk.feed_health import TZ, feed_health
from desk.freshness import desk_freshness


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


def test_feed_health_flags_stale_iv_and_vol(tmp_path: Path):
    # L1 fresh for freshness module (not required by feed_health).
    (tmp_path / "l1_report.json").write_text(
        '{"asof":"20261112","signals":[{"code":"CF"}]}', encoding="utf-8"
    )
    iv_dir = tmp_path / ".cache" / "akshare" / "option_iv" / "CF"
    iv_dir.mkdir(parents=True)
    (iv_dir / "20261028.json").write_text(
        json.dumps({"code": "CF", "date": "20261028", "iv": 0.15}), encoding="utf-8"
    )
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "vol_engine_latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-10-29T16:14:36+08:00",
                "reports": [{"code": "CF", "asof": "20261028", "iv": {"date": "20261028", "ok": True}}],
            }
        ),
        encoding="utf-8",
    )
    wh = tmp_path / ".cache" / "warehouse"
    wh.mkdir(parents=True)
    (wh / "latest.json").write_text(
        json.dumps(
            {
                "asof": "2026-11-12",
                "exchange_ymd": "20261112",
                "primary_n": 6,
                "bypass_n": 21,
                "exchange_status": {
                    "CZCE": {"ok": True},
                    "SHFE": {"ok": False, "error": "JSONDecodeError"},
                    "DCE": {"ok": False, "error": "JSONDecodeError"},
                },
            }
        ),
        encoding="utf-8",
    )
    pack = feed_health(tmp_path, now=_t("2026-11-12 18:00"))
    by_id = {f["id"]: f for f in pack["feeds"]}
    assert by_id["option_iv"]["stale"] is True
    assert by_id["vol_engine"]["stale"] is True
    assert by_id["warehouse"]["status"] == "主源异常"
    assert pack["stale_n"] >= 2


def test_desk_freshness_still_independent(tmp_path: Path):
    (tmp_path / "l1_report.json").write_text(
        '{"asof":"20261112","signals":[{"code":"CF"}]}', encoding="utf-8"
    )
    f = desk_freshness(tmp_path, now=_t("2026-11-12 18:00"))
    assert f["stale"] is False
    assert f["status"] == "已到"
