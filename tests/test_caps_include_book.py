# -*- coding: utf-8 -*-
"""R4: portfolio caps (gross / ATR risk / bucket) must count the already-open book."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import historical_backtest as hb  # noqa: E402
from position_rules import apply_portfolio_caps, book_usage_from_positions  # noqa: E402

EQ = 200_000.0


def _cand(code, *, lots, close, mult, atr, bucket="黑色", r20=9.0, r60=12.0):
    return {
        "code": code,
        "direction": "多",
        "lots": lots,
        "close": close,
        "mult": mult,
        "r20": r20,
        "r60": r60,
        "atr": atr,
        "bucket": bucket,
    }


def _held(code, *, lots, mark, mult, atr, bucket):
    return {"code": code, "lots": lots, "mark": mark, "entry": mark, "mult": mult, "atr": atr, "bucket": bucket}


def _left(book, *, cap_g=50.0, cap_r=8.0):
    g, r, b = book_usage_from_positions(book)
    return max(0.0, cap_g - g / EQ * 100.0), max(0.0, cap_r - r / EQ * 100.0), b


def _caps(cands, book, **kw):
    gl, rl, b = _left(book)
    return apply_portfolio_caps(
        cands,
        equity=EQ,
        max_positions=max(0, 3 - len(book)),
        max_gross_exposure_pct=gl,
        max_portfolio_risk_pct=rl,
        max_per_bucket=1,
        min_r20_pct=3.0,
        min_r60_pct=5.0,
        existing_buckets=b,
        **kw,
    )


# ───────────────────────── gross ─────────────────────────


def test_two_open_positions_at_45pct_gross_force_new_candidate_to_shrink_or_drop():
    book = {
        "P1": _held("P1", lots=1, mark=4500.0, mult=10.0, atr=1.0, bucket="农产品"),
        "P2": _held("P2", lots=1, mark=4500.0, mult=10.0, atr=1.0, bucket="有色"),
    }
    g, _r, _b = book_usage_from_positions(book)
    assert abs(g / EQ * 100 - 45.0) < 1e-9
    # (a) new candidate worth 20% of equity, indivisible -> dropped (only 5% left)
    sel, _ = _caps([_cand("N", lots=1, close=4000.0, mult=10.0, atr=1.0)], book)
    assert sel == []
    # (b) divisible (10 lots × 4000 × 1 = 20%) -> shrunk so book + new <= 50%
    sel, _ = _caps([_cand("N", lots=10, close=4000.0, mult=1.0, atr=1.0)], book)
    assert len(sel) == 1 and 0 < sel[0]["lots"] < 10
    new_g = sel[0]["lots"] * 4000.0 * 1.0
    assert (g + new_g) / EQ * 100 <= 50.0 + 1e-9
    # without the book (old behaviour) the full 20% is accepted -> 65% in total
    old_sel, _ = apply_portfolio_caps(
        [_cand("N", lots=10, close=4000.0, mult=1.0, atr=1.0)],
        equity=EQ, max_positions=1, max_gross_exposure_pct=50.0, max_portfolio_risk_pct=8.0,
    )
    assert old_sel[0]["lots"] == 10


# ───────────────────────── bucket ─────────────────────────


def test_existing_energy_chemical_position_blocks_new_energy_candidate():
    book = {"EB": _held("EB", lots=1, mark=1000.0, mult=10.0, atr=1.0, bucket="能化")}
    cands = [
        _cand("TA", lots=1, close=1000.0, mult=10.0, atr=1.0, bucket="能化", r20=20.0, r60=30.0),
        _cand("RB", lots=1, close=1000.0, mult=10.0, atr=1.0, bucket="黑色", r20=5.0, r60=7.0),
    ]
    sel, meta = _caps(cands, book)
    assert [c["code"] for c in sel] == ["RB"]
    assert "TA" in meta["bucket_skipped"]
    # old behaviour: the stronger 能化 candidate wins the bucket inside the call (bucket-blind to the book)
    old, old_meta = apply_portfolio_caps(
        cands, equity=EQ, max_positions=2, max_gross_exposure_pct=50.0, max_portfolio_risk_pct=8.0
    )
    assert "TA" in [c["code"] for c in old]


def test_existing_buckets_count_is_used_by_the_refill_pass_too():
    book = {"EB": _held("EB", lots=1, mark=1000.0, mult=10.0, atr=1.0, bucket="能化")}
    # B's lots scale to 0 in the main pass, A (能化) must not sneak in through the refill pass
    cands = [
        _cand("A", lots=1, close=1000.0, mult=10.0, atr=1.0, bucket="能化", r20=30.0, r60=30.0),
        _cand("B", lots=1, close=1000.0, mult=10.0, atr=1.0, bucket="黑色", r20=6.0, r60=8.0),
    ]
    sel, _ = _caps(cands, book)
    assert "A" not in [c["code"] for c in sel]


# ───────────────────────── ATR risk ─────────────────────────


def test_existing_atr_risk_6pct_plus_new_4pct_is_shrunk_to_the_remaining_2pct():
    book = {"X": _held("X", lots=1, mark=100.0, mult=100.0, atr=120.0, bucket="有色")}
    _g, r, _b = book_usage_from_positions(book)
    assert abs(r / EQ * 100 - 6.0) < 1e-9
    cand = _cand("N", lots=10, close=100.0, mult=10.0, atr=80.0)  # 10×80×10 = 8000 = 4%
    sel, _ = _caps([cand], book)
    assert len(sel) == 1 and 0 < sel[0]["lots"] < 10
    new_r = sel[0]["lots"] * 80.0 * 10.0
    assert (r + new_r) / EQ * 100 <= 8.0 + 1e-9
    # old behaviour: 4% alone is under the 8% cap -> untouched
    old, _ = apply_portfolio_caps([cand], equity=EQ, max_positions=1, max_gross_exposure_pct=50.0, max_portfolio_risk_pct=8.0)
    assert old[0]["lots"] == 10


# ───────────────────────── backwards compatibility ─────────────────────────

_REF = [
    _cand("A", lots=2, close=5000.0, mult=10.0, atr=100.0, bucket="黑色", r20=9.0, r60=12.0),
    {**_cand("B", lots=2, close=4000.0, mult=10.0, atr=80.0, bucket="能化", r20=-7.0, r60=-9.0), "direction": "空"},
    _cand("C", lots=1, close=8000.0, mult=10.0, atr=150.0, bucket="能化", r20=6.0, r60=8.0),
    _cand("D", lots=4, close=9000.0, mult=5.0, atr=120.0, bucket="农产品", r20=4.0, r60=6.0),
    {**_cand("E", lots=2, close=3000.0, mult=10.0, atr=60.0, bucket="有色", r20=-1.0, r60=-2.0), "direction": "空"},
]


def test_no_existing_buckets_gives_the_old_result_exactly():
    # reference values produced by the pre-R4 implementation (git show HEAD:position_rules.py)
    kw = dict(equity=200000.0, max_positions=3, max_gross_exposure_pct=50.0, max_portfolio_risk_pct=8.0,
              max_per_bucket=1, min_r20_pct=3.0, min_r60_pct=5.0)
    for extra in ({}, {"existing_buckets": None}, {"existing_buckets": {}}):
        sel, meta = apply_portfolio_caps(_REF, **kw, **extra)
        assert [(c["code"], c["lots"]) for c in sel] == [("D", 1)]
        assert meta["gross_after"] == 45000.0 and meta["atr_risk_after"] == 600.0
        assert meta["scale"] == 0.2778 and meta["bucket_skipped"] == ["C"] and meta["weak_filtered"] == ["E"]
    kw2 = dict(equity=400000.0, max_positions=4, max_gross_exposure_pct=60.0, max_portfolio_risk_pct=3.0,
               max_per_bucket=2, min_r20_pct=3.0, min_r60_pct=5.0, min_lots=1)
    sel, meta = apply_portfolio_caps(_REF[:4], **kw2)
    assert [(c["code"], c["lots"]) for c in sel] == [("A", 1), ("B", 1), ("D", 2)]
    assert meta["gross_after"] == 180000.0 and meta["atr_risk_after"] == 3000.0 and meta["scale"] == 0.5455


def _signals():
    out = []
    for code, bucket, close, mult, atr, r20, r60 in (
        ("AA", "黑色", 4000.0, 10.0, 80.0, 9.0, 12.0),
        ("BB", "能化", 6000.0, 10.0, 90.0, 8.0, 10.0),
        ("CC", "农产品", 5000.0, 10.0, 70.0, 7.0, 9.0),
    ):
        out.append(
            {
                "code": code, "align": "同向", "direction": "多", "lots_raw": 3, "lots_l1": 3,
                "close": close, "mult": mult, "atr": atr, "r20": r20, "r60": r60, "bucket": bucket,
                "stop": close - atr, "target": close + 2 * atr,
            }
        )
    return out


def test_daily_update_apply_caps_without_held_is_the_old_behaviour():
    import daily_update as du

    cands = [
        {k: s[k] for k in ("code", "direction", "close", "mult", "r20", "r60", "atr", "bucket")} | {"lots": s["lots_raw"]}
        for s in _signals()
    ]
    expect, emeta = apply_portfolio_caps(
        cands, equity=EQ, max_positions=du.MAX_POSITIONS, max_gross_exposure_pct=du.MAX_GROSS_PCT,
        max_portfolio_risk_pct=du.MAX_PORT_RISK_PCT, max_per_bucket=du.MAX_PER_BUCKET,
        min_r20_pct=du.MIN_R20_PCT, min_r60_pct=du.MIN_R60_PCT,
    )
    sigs = _signals()
    meta = du._apply_caps(sigs, sizing_equity=EQ)
    got = {s["code"]: s["lots_l1"] for s in sigs if s.get("selected")}
    assert got == {c["code"]: c["lots"] for c in expect}
    assert meta["selected"] == emeta["selected"] and "held_book" not in meta
    sigs2 = _signals()
    du._apply_caps(sigs2, sizing_equity=EQ, held=None)
    assert {s["code"]: s["lots_l1"] for s in sigs2 if s.get("selected")} == got


def test_daily_update_apply_caps_with_held_deducts_the_book():
    import daily_update as du

    held = {"ZZ": _held("ZZ", lots=1, mark=9000.0, mult=10.0, atr=100.0, bucket="黑色")}  # 45% gross
    base = _signals()
    du._apply_caps(base, sizing_equity=EQ)
    sigs = _signals()
    meta = du._apply_caps(sigs, sizing_equity=EQ, held=held)
    assert meta["held_book"]["held_n"] == 1
    new_g = sum(s["lots_l1"] * s["close"] * s["mult"] for s in sigs if s.get("selected"))
    assert (9000.0 * 10.0 + new_g) / EQ * 100 <= du.MAX_GROSS_PCT + 1e-9
    # 黑色 is already held -> AA (黑色) cannot be opened
    assert not [s for s in sigs if s["code"] == "AA"][0].get("selected")
    # held code itself never competes as a new candidate
    sigs3 = _signals()
    du._apply_caps(sigs3, sizing_equity=EQ, held={"BB": _held("BB", lots=1, mark=6000.0, mult=10.0, atr=90.0, bucket="能化")})
    assert not [s for s in sigs3 if s["code"] == "BB"][0].get("selected")


# ───────────────────────── simulate helper / paper book ─────────────────────────


def test_book_usage_prefers_held_contract_close_and_adjusted_atr():
    series = {"AA": {"hist": [{"date": "d1", "close": 100.0}], "meta": {"mult": 10.0}}}
    idx = {"AA": {"d1": 0}}
    pos = {"AA": {"lots": 2, "bucket": "黑色", "atr": 9.0, "entry": 90.0, "fill_price_basis": "contract"}}
    g, r, b = hb._book_usage(
        pos, idx, series, "d1",
        atr_fn=lambda code, hist, i: 5.0,
        close_fn=lambda code, p, i, d: 120.0,
    )
    assert g == 2 * 120.0 * 10.0 and r == 2 * 5.0 * 10.0 and b == {"黑色": 1}
    g, r, _ = hb._book_usage(pos, idx, series, "d1", atr_fn=lambda *a: 5.0, close_fn=lambda *a: None)
    assert g == 2 * 100.0 * 10.0  # falls back to the continuous close
    # a position with no bar today is still counted (entry price / entry ATR)
    g, r, _ = hb._book_usage(pos, {"AA": {}}, series, "d9")
    assert g == 2 * 90.0 * 10.0 and r == 2 * 9.0 * 10.0


def test_paper_book_caps_book_check():
    from paper_book import caps_book_check

    caps = {"max_positions": 3, "max_gross_pct": 50.0, "max_port_risk_pct": 8.0, "max_per_bucket": 1}
    kept = {"P1": _held("P1", lots=1, mark=4500.0, mult=10.0, atr=10.0, bucket="农产品")}
    new = {"lots": 1, "entry": 1000.0, "atr": 10.0, "bucket": "有色"}
    assert caps_book_check(kept, new, equity=EQ, caps=caps, mult=10.0) is None
    assert "bucket" in caps_book_check(kept, {**new, "bucket": "农产品"}, equity=EQ, caps=caps, mult=10.0)
    assert "gross" in caps_book_check(kept, {**new, "entry": 9000.0}, equity=EQ, caps=caps, mult=10.0)
    assert "atr_risk" in caps_book_check(kept, {**new, "atr": 2000.0}, equity=EQ, caps=caps, mult=10.0)
    full = {f"K{i}": _held(f"K{i}", lots=1, mark=100.0, mult=10.0, atr=1.0, bucket=f"b{i}") for i in range(3)}
    assert "positions" in caps_book_check(full, new, equity=EQ, caps=caps, mult=10.0)
