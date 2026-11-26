# -*- coding: utf-8 -*-
"""Unit tests for the official daily pipeline (no network). Store/alerts/state are exercised on temp directories."""
from __future__ import annotations

import gzip
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from official_pipeline import alerts  # noqa: E402
from official_pipeline import config as C  # noqa: E402
from official_pipeline import install_tasks  # noqa: E402
from official_pipeline import run as R  # noqa: E402
from official_pipeline import seed as SEED  # noqa: E402
from official_pipeline import sources as SRC  # noqa: E402
from official_pipeline import state as S  # noqa: E402
from official_pipeline.store import Store, sha256_bytes  # noqa: E402


# ---- calendar ------------------------------------------------------------------------------------------------------------
def test_weekdays_before_skips_weekends_and_today():
    days = R.weekdays_before(date(2026, 11, 26), 14)  # Thursday
    assert len(days) == 14
    assert days[-1] == "2026-11-25"
    assert "2026-11-26" not in days
    assert all(date.fromisoformat(d).weekday() < 5 for d in days)
    assert days == sorted(days)


def test_weekdays_between_is_the_full_catch_up_range():
    days = R.weekdays_between("2026-11-20", "2026-11-26")  # Fri .. Thu
    assert days == ["2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26"]
    assert R.weekdays_between("2026-11-27", "2026-11-26") == []


def _fake_cache(monkeypatch, per_product: dict[str, set[str]]):
    monkeypatch.setattr(R, "sina_bar_days", lambda code: per_product.get(code, set()))
    monkeypatch.setattr(R.C, "PRODUCTS", sorted(per_product))


def test_sina_status_pending_when_cache_not_synced_to_day(monkeypatch):
    _fake_cache(monkeypatch, {"AG": {"2026-11-24", "2026-11-25"}, "M": {"2026-11-20"}})
    assert R.sina_status("2026-11-26") == ("pending", [])


def test_sina_status_gap_when_synced_past_day_but_product_missing(monkeypatch):
    _fake_cache(monkeypatch, {"AG": {"2026-11-25", "2026-11-26"}, "M": {"2026-11-20"}})
    status, stale = R.sina_status("2026-11-25")
    assert status == "gap" and stale == ["M"]


def test_sina_status_ok_when_every_product_has_the_day(monkeypatch):
    _fake_cache(monkeypatch, {"AG": {"2026-11-26"}, "M": {"2026-11-26", "2026-11-25"}})
    assert R.sina_status("2026-11-26") == ("ok", [])


# ---- state: streak, closed days, final normal ----------------------------------------------------------------------------
def test_streak_counts_trailing_normal_days_and_ignores_closed():
    st = S.empty()
    for d, ok in [("2026-11-18", True), ("2026-11-19", False), ("2026-11-20", True), ("2026-11-23", True)]:
        st = S.judge(st, d, ok, [] if ok else ["x"])
    assert st["streak"] == 2
    st = S.mark_closed(st, "2026-11-24")  # closed day: neither breaks nor counts
    assert st["streak"] == 2
    st = S.judge(st, "2026-11-25", True, [])
    assert st["streak"] == 3
    assert S.gate_ready(st) is False
    for d in ["2026-11-26", "2026-11-27", "2026-11-30", "2026-12-01"]:
        st = S.judge(st, d, True, [])
    assert S.gate_ready(st) is True


def test_normal_judgement_is_final_but_abnormal_can_be_rejudged():
    st = S.empty()
    st = S.judge(st, "2026-11-26", False, ["dce missing"])
    assert st["streak"] == 0
    st = S.judge(st, "2026-11-26", True, [])  # later recovery re-judges the abnormal day
    assert st["days"]["2026-11-26"]["normal"] is True and st["streak"] == 1
    st = S.judge(st, "2026-11-26", False, ["later problem"])  # normal is final: no change
    assert st["days"]["2026-11-26"]["normal"] is True


def test_state_save_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    st = S.judge(S.empty(), "2026-11-26", True, [])
    S.save(st, p)
    assert S.load(p)["streak"] == 1


# ---- store: new / unchanged / revision (never overwrite the original) ----------------------------------------------------
def test_store_put_new_unchanged_revision(tmp_path):
    s = Store(raw_root=tmp_path / "raw", revisions_root=tmp_path / "rev")
    assert s.put("shfe", "2026-11-26", b"v1") == "new"
    assert s.put("shfe", "2026-11-26", b"v1") == "unchanged"
    assert s.put("shfe", "2026-11-26", b"v2") == "revision"
    assert gzip.decompress(s.raw_path("shfe", "2026-11-26").read_bytes()) == b"v1"  # original kept
    assert "2026-11-26" in s.revision_days()["shfe"]
    assert s.is_stored("shfe", "2026-11-26") and s.read_body("shfe", "2026-11-26") == b"v1"


def test_store_failure_does_not_overwrite_ok(tmp_path):
    s = Store(raw_root=tmp_path / "raw", revisions_root=tmp_path / "rev")
    s.put("czce", "2026-11-26", b"body")
    s.record_failure("czce", "2026-11-26", "error")
    assert s.is_stored("czce", "2026-11-26")
    assert s.status("czce", "2026-11-26") == "ok"


# ---- DCE canonical body (format verified against a live reply 2026-11-26) -----------------------------------------------
def _dce_reply(rows):
    return json.dumps({"success": True, "code": 200, "msg": "操作成功", "data": rows}, ensure_ascii=False)


def _dce_row(cid, **kw):
    base = {"variety": "x", "contractId": cid, "open": "1", "high": "2", "low": "0.5", "close": "1.5",
            "lastClear": "1.2", "clearPrice": "1.4", "volumn": "10", "openInterest": "20", "turnover": "3"}
    base.update(kw)
    return base


def test_dce_body_keeps_universe_rows_in_r8_canonical_form():
    text = _dce_reply([_dce_row("a2701"), _dce_row("ZZ2701"), _dce_row("m2701"), _dce_row("v2701")])
    body = SRC.dce_response_to_body(text, "2026-11-26")
    j = json.loads(body)
    assert j["cols"] == SRC.DCE_COLS
    # a (soybean No.1) and ZZ are not in the 10-product DCE universe -> dropped
    assert [r[0] for r in j["rows"]] == ["m2701", "v2701"]
    assert body == json.dumps(j, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_dce_body_none_when_no_universe_rows_and_raises_on_bad_shape():
    assert SRC.dce_response_to_body(_dce_reply([_dce_row("ZZ2701")]), "2026-11-26") is None
    with pytest.raises(ValueError):
        SRC.dce_response_to_body('{"success": false, "code": 500, "data": null}', "2026-11-26")
    with pytest.raises(ValueError):
        SRC.dce_response_to_body(_dce_reply([{"contractId": "a2701", "open": "1"}]), "2026-11-26")


# ---- seed: hash verification before copy --------------------------------------------------------------------------------
def test_seed_copies_only_hash_verified_days(tmp_path):
    src = tmp_path / "src"
    (src / "shfe").mkdir(parents=True)
    good, bad = b'{"ok":1}', b'{"ok":2}'
    (src / "shfe" / "20261126.gz").write_bytes(gzip.compress(good))
    (src / "shfe" / "20261127.gz").write_bytes(gzip.compress(bad))
    manifest = {
        "2026-11-26": {"status": "ok", "sha256": sha256_bytes(good), "bytes": len(good)},
        "2026-11-27": {"status": "ok", "sha256": sha256_bytes(b"something else"), "bytes": 3},
        "2026-11-28": {"status": "404"},
    }
    (src / "MANIFEST_shfe.json").write_text(json.dumps(manifest), encoding="utf-8")
    store = Store(raw_root=tmp_path / "raw", revisions_root=tmp_path / "rev")
    rep = SEED.verify_and_copy(src_root=src, store=store)
    assert rep["mismatch"] == ["shfe 2026-11-27"]
    assert store.is_stored("shfe", "2026-11-26")
    assert not store.raw_path("shfe", "2026-11-27").exists()
    assert store.status("shfe", "2026-11-28") == "404"  # non-ok outcome kept as-is


# ---- alerts --------------------------------------------------------------------------------------------------------------
def test_alert_file_written_with_reasons(tmp_path):
    p = alerts.write_alert("2026-11-26", ["dce missing"], ["detail line"], root=tmp_path)
    text = p.read_text(encoding="utf-8")
    assert p.name == "ALERT_2026-11-26.md"
    assert "dce missing" in text and "detail line" in text


# ---- scheduled tasks ----------------------------------------------------------------------------------------------------
def test_task_xml_has_wake_and_catchup_and_the_right_command():
    xml = install_tasks.task_xml("17:30", "run")
    assert "<WakeToRun>true</WakeToRun>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "T17:30:00" in xml
    assert "-m official_pipeline run" in xml
    assert "<Monday />" in xml and "<Friday />" in xml and "<Saturday" not in xml
    assert install_tasks.TASKS["CTA_Official_Judge_0830"] == ("08:30", "judge")


# ---- accuracy check and GitHub sync ----------------------------------------------------------------------------------------
def test_verify_flags_tampered_and_missing_bodies(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    store = Store(raw_root=raw, revisions_root=tmp_path / "rev")
    good, bad = b'{"a":1}', b'{"a":2}'
    store.put("shfe", "2026-11-26", good)
    store.put("shfe", "2026-11-25", bad)
    store.raw_path("shfe", "2026-11-25").write_bytes(gzip.compress(b'{"a":999}'))  # tampered after manifest
    store.put("shfe", "2026-11-24", b"x")
    store.raw_path("shfe", "2026-11-24").unlink()  # missing file
    monkeypatch.setattr(R, "Store", lambda: store)
    lines: list[str] = []
    rc = R.cmd_verify(lines.append)
    assert rc == R.EXIT_VALID
    text = "\n".join(lines)
    assert "2026-11-25: sha256 differs" in text and "2026-11-24: raw file missing" in text
    assert "2026-11-26" not in text.replace("checked", "")  # the good body is not reported


def test_sync_is_skipped_safely_when_store_is_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(R.C, "STORE", tmp_path)  # no .git here
    lines: list[str] = []
    assert R.sync_store(lines.append, "test") is False
    assert any("not a git repo" in s for s in lines)


def test_store_gitignore_keeps_raw_replies_out_of_git():
    gi = (C.STORE / ".gitignore").read_text(encoding="utf-8") if (C.STORE / ".gitignore").exists() else ""
    assert "responses/" in gi and "logs/" in gi


# ---- config guard: store must be outside the repo -----------------------------------------------------------------------
def test_store_is_outside_repo_and_protected_files_not_referenced():
    assert ROOT not in C.STORE.parents and C.STORE != ROOT
    text = (ROOT / "official_pipeline").joinpath("run.py").read_text(encoding="utf-8")
    for protected in ("universe.json", "execution_rules.json", "formal_rule_lock", "historical_backtest.yml"):
        assert protected not in text
