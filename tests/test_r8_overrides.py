# -*- coding: utf-8 -*-
"""R8: --max-gross / --equity / --min-lots are research overrides and only work together with --out."""
from __future__ import annotations

import sys

import pytest

import historical_backtest as hb


class _Reached(Exception):
    """Raised by the stub that replaces the data fetch: we got past all R8 guards."""


def _run(monkeypatch, capsys, argv, *, fetch="forbid"):
    monkeypatch.setattr(sys, "argv", ["historical_backtest.py", *argv])

    def _stub(*a, **k):
        if fetch == "forbid":
            raise AssertionError("main() must refuse before fetching any data")
        raise _Reached()

    monkeypatch.setattr(hb, "_fetch_pack", _stub)
    rc = hb.main()
    return rc, capsys.readouterr()


@pytest.mark.parametrize(
    "argv",
    [["--max-gross", "70"], ["--equity", "300000"], ["--min-lots", "1"], ["--max-gross=70"],
     ["--fill", "next_open", "--equity=500000", "--min-lots", "0"]],
)
def test_overrides_without_out_are_refused(monkeypatch, capsys, argv):
    rc, cap = _run(monkeypatch, capsys, argv)
    assert rc == 2
    assert "--out" in cap.err


@pytest.mark.parametrize(
    "extra, needle",
    [(["--equity"], "needs a value"), (["--max-gross", "0"], "must be"), (["--max-gross", "abc"], "bad value"),
     (["--equity", "-5"], "must be"), (["--min-lots", "-1"], "must be"), (["--min-lots", "1.5"], "bad value")],
)
def test_bad_values_are_refused_even_with_out(monkeypatch, capsys, tmp_path, extra, needle):
    out = tmp_path / "x" / "r.json"
    rc, cap = _run(monkeypatch, capsys, ["--out", str(out), *extra])
    assert rc == 2
    assert needle in cap.err
    assert not out.exists() and not out.parent.exists()


def test_overrides_not_allowed_with_other_modes(monkeypatch, capsys, tmp_path):
    for mode in ("--compare", "--rr-grid", "--roll-grid", "--hedge-grid", "--ctf"):
        rc, cap = _run(monkeypatch, capsys, ["--out", str(tmp_path / "r.json"), "--equity", "300000", mode])
        assert rc == 2, mode
        assert "default single run" in cap.err


def test_valid_overrides_reach_the_run_header_and_write_nothing(monkeypatch, capsys, tmp_path):
    out = tmp_path / "r8" / "r.json"
    monkeypatch.setattr(sys, "argv", ["historical_backtest.py", "--out", str(out), "--max-gross", "70",
                                     "--equity", "300000", "--min-lots", "1"])
    monkeypatch.setattr(hb, "_fetch_pack", lambda *a, **k: (_ for _ in ()).throw(_Reached()))
    with pytest.raises(_Reached):
        hb.main()
    header = capsys.readouterr().out
    assert "equity0=300000.0" in header
    assert "gross≤70.0%" in header
    assert "min_lots=1" in header
    assert not out.exists()


def test_parser_returns_empty_without_flags_and_accepts_zero_min_lots(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--fill", "next_open", "--out", "a.json"])
    assert hb.r8_overrides_from_argv() == {}
    assert hb._r8_flags_present() is False
    monkeypatch.setattr(sys, "argv", ["x", "--out", "a.json", "--min-lots", "0", "--max-gross=100", "--equity", "1e6"])
    assert hb.r8_overrides_from_argv() == {"min_lots": 0, "max_gross_pct": 100.0, "equity0": 1_000_000.0}
    assert hb._r8_flags_present() is True


def test_out_alone_is_unchanged_r0_behaviour(monkeypatch, capsys, tmp_path):
    """--out without R8 flags must not trip the R8 guard."""
    rc_or_exc = None
    monkeypatch.setattr(sys, "argv", ["historical_backtest.py", "--out", str(tmp_path / "r.json")])
    monkeypatch.setattr(hb, "_fetch_pack", lambda *a, **k: (_ for _ in ()).throw(_Reached()))
    with pytest.raises(_Reached):
        rc_or_exc = hb.main()
    assert rc_or_exc is None
    assert "research overrides" not in capsys.readouterr().err
