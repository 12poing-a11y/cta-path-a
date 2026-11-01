# -*- coding: utf-8 -*-
"""Order-block v1: structure, retest timing, and no-lookahead invariants."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signals.order_block import (  # noqa: E402
    OrderBlockParams,
    detect_order_blocks,
    load_run_config,
    params_from_config,
)
from signals.order_block_eval import FORMAL_ARTIFACTS, assert_shadow_destination  # noqa: E402
from signals.order_block_sim import simulate_retest_trades  # noqa: E402
from scripts.order_block_shadow import run_shadow  # noqa: E402


def _ohlc(rows: list[tuple], start: str = "2024-01-02") -> list[dict]:
    """rows are (open, high, low, close). Dates are calendar days from start."""
    y, m, d = (int(x) for x in start.split("-"))
    from datetime import date, timedelta

    cursor = date(y, m, d)
    out = []
    for o, h, l, c in rows:
        out.append(
            {
                "date": cursor.isoformat(),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
            }
        )
        cursor += timedelta(days=1)
    return out


# Swing high 20 at index 4, confirmed at 6. Bearish source at 8 (nearer than
# the bearish bar at 6). Close breaks the swing at index 9. First retest at 11.
LONG_ROWS = [
    (10, 11, 9, 10),
    (10, 12, 9, 11),
    (11, 13, 10, 12),
    (12, 14, 11, 13),
    (13, 20, 12, 19),
    (19, 19.5, 14, 15),
    (15, 16, 13, 14),
    (14, 17, 13, 16),
    (16, 18, 12, 13),
    (13, 26, 13, 25),
    (25, 27, 24, 26),
    (26, 26, 14, 18),
]

# Swing low 10 at index 4, confirmed at 6. Bullish source at 8. Close breaks
# down at index 9. First retest at 11.
SHORT_ROWS = [
    (30, 31, 28, 29),
    (29, 30, 27, 28),
    (28, 29, 26, 27),
    (27, 28, 22, 23),
    (23, 24, 10, 12),
    (12, 16, 11, 15),
    (15, 18, 14, 17),
    (17, 19, 16, 18),
    (18, 22, 17, 21),
    (21, 21, 8, 9),
    (9, 10, 8, 8.5),
    (8.5, 20, 8, 16),
]


def _long_zone(bars=None):
    found = detect_order_blocks(bars or _ohlc(LONG_ROWS))
    zones = [z for z in found.order_blocks if z.direction == "long"]
    assert len(zones) == 1
    return found, zones[0]


def test_swing_right_zero_is_rejected():
    try:
        OrderBlockParams(swing_right=0).validated()
    except ValueError as exc:
        assert "swing_right" in str(exc)
    else:
        raise AssertionError("swing_right=0 must be rejected")


def test_long_zone_uses_nearest_prior_bearish_candle():
    found, zone = _long_zone()
    assert zone.source_index == 8
    assert zone.bos_index == 9
    assert zone.swing_index == 4
    assert zone.swing_confirmed_index == 6
    assert zone.zone_low == 12
    assert zone.zone_high == 18
    assert zone.known_from_index == 9
    assert zone.active_from_index == 10
    assert zone.invalidation_price == 12
    assert found.signals[0].signal_index == 11
    assert found.signals[0].ob_id == zone.ob_id
    assert found.signals[0].fill_rule == "next_open"
    assert found.signals[0].quality_score is None


def test_signal_is_after_break_and_after_activation():
    found, zone = _long_zone()
    for sig in found.signals:
        assert sig.source_index < sig.bos_index
        assert sig.bos_index < zone.active_from_index <= sig.signal_index
        assert sig.signal_index > sig.bos_index
        assert sig.entry_reference == 18
        assert sig.stop_price == zone.zone_low


def test_pre_break_overlap_does_not_signal():
    found, zone = _long_zone()
    # Bar 8 is the source candle and overlaps its own future zone.
    assert all(sig.signal_index > zone.bos_index for sig in found.signals)
    assert all(sig.signal_index >= zone.active_from_index for sig in found.signals)


def test_failed_zone_is_kept_and_blocks_a_later_touch():
    rows = LONG_ROWS[:10] + [
        (24, 24, 11, 11.5),  # close through 12
        (14, 17, 13, 16),  # would have been a retest
    ]
    found = detect_order_blocks(_ohlc(rows))
    zone = next(z for z in found.order_blocks if z.direction == "long")
    assert zone.status == "invalidated"
    assert zone.invalidated_index == 10
    assert zone.retest_count == 0
    assert found.signals == []


def test_unretested_zone_is_kept():
    rows = LONG_ROWS[:10] + [
        (25, 28, 24, 27),
        (27, 30, 26, 29),
        (29, 32, 28, 31),
        (31, 33, 30, 32),
        (32, 34, 31, 33),
    ]
    found = detect_order_blocks(_ohlc(rows))
    zone = next(z for z in found.order_blocks if z.direction == "long")
    assert zone.status == "active"
    assert zone.retest_count == 0
    assert zone.invalidated_index is None
    assert found.signals == []


def test_stale_zone_already_through_at_the_break_is_kept_and_silent():
    """Nearest bearish candle can be a stale range the break close is already under.

    Retirement is decided from that close alone. A later rally into the
    range must not become a signal.
    """
    rows = [
        (100, 101, 90, 91),
        (20, 22, 19, 21),
        (21, 23, 20, 22),
        (22, 24, 21, 23),
        (23, 35, 22, 34),
        (30, 32, 29, 31),
        (31, 33, 30, 32),
        (32, 34, 31, 33),
        (33, 37, 32, 36),
        (36, 95, 35, 94),
    ]
    bars = _ohlc(rows)
    found = detect_order_blocks(bars)
    zone = next(z for z in found.order_blocks if z.ob_id == "L8-0")
    assert zone.source_index == 0
    assert zone.bos_index == 8
    assert zone.zone_low == 90
    assert bars[8]["close"] < zone.invalidation_price
    assert zone.status == "invalidated"
    assert zone.invalidated_index == 8
    assert not any(s.ob_id == zone.ob_id for s in found.signals)


def test_second_touch_does_not_emit_another_signal():
    rows = LONG_ROWS + [
        (20, 24, 19, 22),  # leaves the zone
        (22, 23, 13, 16),  # second overlap, close still above 12
    ]
    found = detect_order_blocks(_ohlc(rows))
    zone = next(z for z in found.order_blocks if z.ob_id == "L9-8")
    assert zone.retest_count == 1
    assert [s.signal_index for s in found.signals if s.ob_id == zone.ob_id] == [11]


def test_wick_through_far_side_can_still_signal_if_close_holds():
    rows = LONG_ROWS[:11] + [
        (26, 26, 10, 15),  # low through 12, close back above
    ]
    found = detect_order_blocks(_ohlc(rows))
    zone = next(z for z in found.order_blocks if z.direction == "long")
    assert zone.status == "retested"
    assert zone.invalidated_index is None
    assert len(found.signals) == 1
    assert found.signals[0].signal_index == 11


def test_short_mirror():
    found = detect_order_blocks(_ohlc(SHORT_ROWS))
    zone = next(z for z in found.order_blocks if z.direction == "short")
    assert zone.source_index == 8
    assert zone.bos_index == 9
    assert zone.swing_index == 4
    assert zone.swing_confirmed_index == 6
    assert zone.zone_low == 17
    assert zone.zone_high == 22
    assert zone.invalidation_price == 22
    assert zone.active_from_index == 10
    assert len(found.signals) == 1
    sig = found.signals[0]
    assert sig.direction == "short"
    assert sig.signal_index == 11
    assert sig.stop_price == 22


def test_opposite_candle_after_the_break_cannot_become_the_zone():
    rows = [
        (10, 11, 9, 10.5),
        (10.5, 12, 10, 11.5),
        (11.5, 13, 11, 12.5),
        (12.5, 14, 12, 13.5),
        (13.5, 20, 13, 19),
        (19, 19.5, 18, 19.2),
        (19.2, 19.4, 18.5, 19.3),
        (19.3, 19.6, 18.8, 19.4),
        (19.4, 19.8, 19, 19.6),  # bullish, so the pre-break window has no bearish bar
        (19.6, 26, 19.5, 25),  # BOS
        (25, 25, 14, 16),  # bearish after the break; must not be copied backward
    ]
    found = detect_order_blocks(
        _ohlc(rows),
        OrderBlockParams(ob_search_window=5),
    )
    assert not any(z.direction == "long" for z in found.order_blocks)
    assert any(b.direction == "long" and b.bos_index == 9 for b in found.unzoned_breaks)
    assert all(z.source_index < z.bos_index for z in found.order_blocks)


def test_prefix_matches_full_scan_on_crafted_and_random_paths():
    stale = [
        (100, 101, 90, 91),
        (20, 22, 19, 21),
        (21, 23, 20, 22),
        (22, 24, 21, 23),
        (23, 35, 22, 34),
        (30, 32, 29, 31),
        (31, 33, 30, 32),
        (32, 34, 31, 33),
        (33, 37, 32, 36),
        (36, 95, 35, 94),
    ]
    samples = [_ohlc(LONG_ROWS), _ohlc(SHORT_ROWS), _ohlc(stale)]
    rng = random.Random(11)
    price = 100.0
    random_rows = []
    for _ in range(90):
        o = price
        c = o + rng.uniform(-1.5, 1.5)
        h = max(o, c) + rng.uniform(0.05, 0.8)
        l = min(o, c) - rng.uniform(0.05, 0.8)
        random_rows.append((o, h, l, c))
        price = c
    samples.append(_ohlc(random_rows))

    saw_signal = False
    for bars in samples:
        full = detect_order_blocks([dict(b) for b in bars])
        saw_signal = saw_signal or bool(full.signals)
        for t in range(len(bars)):
            prefix = detect_order_blocks([dict(b) for b in bars[: t + 1]])
            assert _known(prefix, t) == _known(full, t)
    assert saw_signal, "fixture produced no signal; lookahead check would be vacuous"


def _known(found, t: int) -> dict:
    """State that is fixed once bar t has closed."""
    swings = []
    for swing in found.swings:
        if swing.confirmed_index > t:
            continue
        broken = swing.broken_index if swing.broken_index is not None and swing.broken_index <= t else None
        swings.append((swing.kind, swing.index, swing.price, swing.confirmed_index, broken))
    zones = []
    for zone in found.order_blocks:
        if zone.bos_index > t:
            continue
        inv = zone.invalidated_index if zone.invalidated_index is not None and zone.invalidated_index <= t else None
        retests = [s for s in found.signals if s.ob_id == zone.ob_id and s.signal_index <= t]
        if inv is not None:
            status = "invalidated"
        elif retests:
            status = "retested"
        else:
            status = "active"
        zones.append(
            (
                zone.ob_id,
                zone.direction,
                zone.source_index,
                zone.bos_index,
                zone.swing_index,
                zone.swing_confirmed_index,
                zone.zone_low,
                zone.zone_high,
                zone.active_from_index,
                inv,
                len(retests),
                status,
            )
        )
    signals = tuple(
        (s.ob_id, s.direction, s.signal_index, s.stop_price, s.entry_reference)
        for s in found.signals
        if s.signal_index <= t
    )
    breaks = tuple(
        (b.direction, b.bos_index, b.swing_index)
        for b in found.unzoned_breaks
        if b.bos_index <= t
    )
    return {"swings": swings, "zones": zones, "signals": signals, "breaks": breaks}


def test_random_paths_obey_time_order():
    rng = random.Random(19)
    for seed_shift in range(8):
        rng.seed(100 + seed_shift)
        price = 50.0
        rows = []
        for _ in range(70):
            o = price
            c = o + rng.uniform(-2, 2)
            h = max(o, c) + rng.uniform(0, 1)
            l = min(o, c) - rng.uniform(0, 1)
            rows.append((o, h, l, c))
            price = c
        found = detect_order_blocks(_ohlc(rows), OrderBlockParams(swing_left=2, swing_right=3))
        for zone in found.order_blocks:
            assert zone.swing_confirmed_index == zone.swing_index + 3
            assert zone.swing_confirmed_index < zone.bos_index
            assert zone.source_index < zone.bos_index
            assert zone.known_from_index == zone.bos_index
            assert zone.active_from_index == zone.bos_index + 1
            bos_close = rows[zone.bos_index][3]
            if zone.invalidated_index == zone.bos_index:
                if zone.direction == "long":
                    assert bos_close < zone.invalidation_price
                else:
                    assert bos_close > zone.invalidation_price
                assert not any(s.ob_id == zone.ob_id for s in found.signals)
            else:
                assert zone.invalidated_index is None or zone.invalidated_index > zone.bos_index
            assert zone.quality_score is None
        for sig in found.signals:
            assert sig.signal_index > sig.bos_index
            assert sig.active_from_index <= sig.signal_index
        for swing in found.swings:
            assert swing.confirmed_index == swing.index + 3
            if swing.broken_index is not None:
                assert swing.broken_index > swing.confirmed_index


def test_fill_is_next_open_and_same_bar_conflict_takes_stop():
    rows = LONG_ROWS + [
        (18, 19, 15, 18),
        (17, 40, 11, 20),  # open is the fill; high tags target; low tags stop
    ]
    bars = _ohlc(rows)
    found, _zone = _long_zone(bars)
    trades, skipped = simulate_retest_trades(bars, found.signals, reward_rr=1.5)
    assert skipped == []
    assert len(trades) == 1
    trade = trades[0]
    assert trade.signal_index == 11
    assert trade.entry_index == 12
    assert trade.entry_price == 18
    assert trade.entry_price != bars[11]["low"]
    assert trade.stop_price == 12
    assert trade.target_price == 18 + 1.5 * (18 - 12)
    assert trade.exit_reason == "stop_and_target_stop_first"
    assert trade.exit_price == 12
    assert trade.r_multiple == -1


def test_gap_through_stop_skips_the_entry():
    rows = LONG_ROWS + [
        (11, 12, 10, 11),  # open already through the zone low at 12
    ]
    bars = _ohlc(rows)
    found, _zone = _long_zone(bars)
    trades, skipped = simulate_retest_trades(bars, found.signals)
    assert trades == []
    assert skipped[0].reason == "gap_through_stop"


def test_baseline_config_is_runnable_and_stubs_are_not(tmp_path):
    cfg = load_run_config(ROOT / "configs" / "order_block" / "baseline.json")
    params = params_from_config(cfg)
    assert params.swing_right == 2
    assert cfg["formal_path_a"]["stop_atr_mult"] == 1.2
    assert cfg["formal_path_a"]["reward_rr"] == 1.5
    assert cfg["live_trading"] is False
    for name in ("trend_filter.json", "risk_management.json"):
        stub = json.loads((ROOT / "configs" / "order_block" / name).read_text(encoding="utf-8"))
        try:
            params_from_config(stub)
        except ValueError as exc:
            assert "runnable" in str(exc)
        else:
            raise AssertionError(f"{name} must not run")


def test_runner_writes_shadow_output_and_leaves_formal_files(tmp_path):
    before = {
        name: (ROOT / name).read_bytes()
        for name in FORMAL_ARTIFACTS
        if (ROOT / name).is_file()
    }
    assert "execution_rules.json" in before
    rules = json.loads(before["execution_rules.json"])
    assert rules["stop_atr_mult"] == 1.2
    assert rules["reward_rr"] == 1.5

    payload = run_shadow(
        _ohlc(LONG_ROWS + [(18, 19, 15, 18), (18, 30, 17, 28)]),
        ROOT / "configs" / "order_block" / "baseline.json",
        symbol="UNIT",
        root=ROOT,
        out_dir=tmp_path,
    )
    assert payload["formal_path_a_untouched"] is True
    assert payload["live_trading"] is False
    assert payload["evaluation"]["ablation"]["status"] == "stub"
    assert payload["evaluation"]["walk_forward"]["status"] == "stub"
    assert payload["claims"]["alpha"] is False
    written = Path(payload["output_path"])
    assert written.is_file()
    assert written.parent == tmp_path
    for name, blob in before.items():
        assert (ROOT / name).read_bytes() == blob


def test_shadow_destination_refuses_formal_latest_names(tmp_path):
    for name in ("paper_book_latest.json", "l1_report.json", "latest.json", "execution_rules.json"):
        try:
            assert_shadow_destination(ROOT, ROOT / "data" / "order_block" / "shadow" / name)
        except ValueError:
            pass
        else:
            raise AssertionError(name)
    try:
        assert_shadow_destination(ROOT, ROOT / "desk" / "ob.json")
    except ValueError:
        pass
    else:
        raise AssertionError("in-repo path outside the shadow dir must fail")
    allowed = assert_shadow_destination(ROOT, tmp_path / "ob_shadow_UNIT.json")
    assert allowed == (tmp_path / "ob_shadow_UNIT.json").resolve()
    shadow = assert_shadow_destination(
        ROOT, ROOT / "data" / "order_block" / "shadow" / "ob_shadow_demo.json"
    )
    assert shadow.name == "ob_shadow_demo.json"
