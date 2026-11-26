# -*- coding: utf-8 -*-
"""Path-A ~1y paper backtest. Sina/Tencent daily bars, iFinD if those are short."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ifind_call import active_slot, call, usage_report  # noqa: E402
from member_rank import load_member_changes, load_member_seats  # noqa: E402
from path_a_filters import (  # noqa: E402
    carry_bypass_cfg,
    carry_bypass_decision,
    carry_gap_pct,
    entry_block,
    fill_cost,
    load_slippage_ticks,
    seat_decision,
)
from public_curve import curve_coverage, load_curves  # noqa: E402
from book_core import PositionEngine  # noqa: E402
from signal_core import path_a_candidate  # noqa: E402
from vol_factor_combo import vol_bypass_cfg, vol_entry_block  # noqa: E402
from option_hedge import (  # noqa: E402
    attach_hedge_to_position,
    hedge_enabled,
    hedge_params,
    option_payoff,
)
from position_rules import (  # noqa: E402
    apply_portfolio_caps,
    compound_equity,
    risk_budget_yuan,
)
from wyckoff_pullback import (  # noqa: E402
    apply_stop_target,
    apply_stop_target_intraday,
    minute_bars_aligned_with_entry,
    minute_bars_match_daily,
)

LOOKBACK_DAYS = 260
WARMUP = 60
BATCH_LABEL = "2026一年-pathA-nextOpen"
CUTOFF_DAYS = 420
SCHEMA_VERSION = "cta-backtest-v14-execfix"
DEFAULT_FILL_PRICE = "next_open"
EXIT_MINUTE_PERIOD = "15"
# Continuous main-series remains the Path-A fill proxy until contract-level packs land.
# Explicit price_basis="continuous" without allow_continuous_fill still blocks.

# --- P0 lookahead guards -----------------------------------------------------
# Seat rankings / basis are published after the T close (seats ~16:00-17:00),
# so signal on T close fills at T+1 open; lag=1 keeps seats/basis causal.
DEFAULT_AVAILABILITY_LAG = 1
FILL_PRICES = ("close", "next_open")


def _git_sha(root: Path | None = None) -> str | None:
    root = root or ROOT
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return out.strip() or None
    except Exception:
        return None


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def lag_by_trade_dates(book: dict | None, dates: list[str], lag: int) -> dict:
    """Return {d: book[dates[k-lag]]} so the value visible on d is lag sessions old."""
    book = book or {}
    lag = max(0, int(lag))
    if lag == 0:
        return dict(book)
    out = {}
    for k, d in enumerate(dates):
        if k - lag < 0:
            continue
        v = book.get(dates[k - lag])
        if v is not None:
            out[d] = v
    return out


def lag_member(member: dict, dates: list[str], lag: int) -> dict:
    return {c: lag_by_trade_dates(b, dates, lag) for c, b in (member or {}).items()}


def lag_curves_carry(curves: dict, dates: list[str], lag: int) -> dict:
    """Copy curves with carry shifted by lag sessions (does not mutate the cache)."""
    out = {}
    for c, cv in (curves or {}).items():
        if isinstance(cv, dict):
            cv2 = dict(cv)
            if isinstance(cv.get("carry"), dict):
                cv2["carry"] = lag_by_trade_dates(cv["carry"], dates, lag)
            out[c] = cv2
        else:
            out[c] = cv
    return out


def next_open_fill(c: dict, hist: list[dict], i: int) -> dict | None:
    """Move a T-close candidate to the T+1 open; stop/target keep their distance.

    Prefer exact-contract open when contract_pack overlay stamped ``contract_open``.
    """
    if i + 1 >= len(hist):
        return None
    nb = hist[i + 1]
    px = nb.get("contract_open")
    fill_basis = "contract"
    if px is None:
        px = nb.get("open")
        fill_basis = "continuous_proxy"
    if px is None:
        return None
    shift = float(px) - float(c["entry"])
    c2 = dict(c)
    c2["entry"] = float(px)
    c2["stop"] = float(c["stop"]) + shift
    c2["target"] = float(c["target"]) + shift
    c2["entry_date"] = nb["date"]
    c2["mark_from"] = float(px)
    c2["fill_price_basis"] = fill_basis
    if fill_basis == "contract" and nb.get("contract"):
        c2["fill_contract"] = nb.get("contract")
    return c2


def manage_ohlc_bar(bar: dict, basis: str | None) -> dict | None:
    """OHLC for stop/target/mark — locked to the position's fill_price_basis.

    Contract fills must not be managed on continuous high/low (false same-day
    stop/target). Returns None when contract basis is requested but contract
    OHLC is missing for this bar (caller must not fall back to continuous).
    """
    b = str(basis or "continuous_proxy").strip().lower()
    if b == "contract":
        if (
            bar.get("contract_high") is None
            or bar.get("contract_low") is None
            or bar.get("contract_close") is None
        ):
            return None
        try:
            close = float(bar["contract_close"])
            high = float(bar["contract_high"])
            low = float(bar["contract_low"])
            open_px = (
                float(bar["contract_open"])
                if bar.get("contract_open") is not None
                else close
            )
        except (TypeError, ValueError):
            return None
        return {
            "open": open_px,
            "high": high,
            "low": low,
            "close": close,
            "date": bar.get("date"),
        }
    try:
        return {
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "date": bar.get("date"),
        }
    except (KeyError, TypeError, ValueError):
        return None


MIN_SEAT_DAYS = 60  # varieties with <60 seat sessions (as of T) skip the formal seat filter
ENTRY_DELIVERY_BUFFER = 10  # contract fill with <10 sessions before delivery month is not taken on that contract
ENTRY_DELIVERY_ACTION = "proxy"  # "proxy": fill/manage on continuous main (rolls); "block": skip entry
MAX_STALE_DAYS = 3  # >3 consecutive days without same-contract OHLC => force exit ("freeze")


def contract_delivery_ym(contract: str | None) -> str | None:
    """'L2601' -> '2026-01'; 'FG605' (CZCE 3-digit) -> '2026-05'. None if unparsable."""
    import re as _re

    m = _re.search(r"(\d{3,4})$", str(contract or ""))
    if not m:
        return None
    dg = m.group(1)
    if len(dg) == 3:
        yy, mm = 20 + int(dg[0]), int(dg[1:])
    else:
        yy, mm = int(dg[:2]), int(dg[2:])
    if not 1 <= mm <= 12:
        return None
    return f"{2000 + yy if yy < 100 else yy:04d}-{mm:02d}"


def manage_bar_fixed(
    bar: dict,
    p: dict,
    *,
    use_main: bool = False,
    main_now: str | None = None,
    contract_ohlc: dict | None = None,
    last_close: float | None = None,
    last_close_date: str | None = None,
) -> tuple[dict | None, bool, str | None]:
    """Freeze-fix manage bar (shadow fix3 + R6a, main-map gate from R6b-fix).

    Contract fills: the held contract's own real OHLC (snapshot ``contract_*``
    or ``.cache/contracts``) is used whenever it exists.  Only without it may
    ``continuous + basis_off`` be used — and only while the actual main contract
    of today (``main_now``) equals the main contract of the day ``basis_off`` was
    computed (``p['basis_off_main']``); otherwise → ``roll_unpriced`` (exit at the
    held contract's last known close, never the new main's price).
    ``use_main=False`` (no main map for this code / legacy callers) keeps the
    plain continuous + basis_off proxy.
    Returns (mbar, proxied, force_reason).
    """
    basis = str(p.get("fill_price_basis") or "continuous_proxy").strip().lower()
    if basis != "contract":
        return manage_ohlc_bar(bar, "continuous_proxy"), False, None
    fc = p.get("fill_contract")
    same = fc is None or bar.get("contract") in (None, fc)
    if same:
        cb = manage_ohlc_bar(bar, "contract")
        if cb is not None:
            try:
                p["basis_off"] = float(bar["contract_close"]) - float(bar["close"])
                p["basis_off_contract"] = str(bar.get("contract") or fc or "")
                p["basis_off_main"] = main_now
            except (KeyError, TypeError, ValueError):
                pass
            return cb, False, None
    if contract_ohlc is not None:
        try:
            p["basis_off"] = float(contract_ohlc["close"]) - float(bar["close"])
            p["basis_off_contract"] = str(fc or bar.get("contract") or "")
            p["basis_off_main"] = main_now
        except (KeyError, TypeError, ValueError):
            pass
        return {
            "open": float(contract_ohlc["open"]),
            "high": float(contract_ohlc["high"]),
            "low": float(contract_ohlc["low"]),
            "close": float(contract_ohlc["close"]),
            "date": bar.get("date"),
        }, False, None
    # basis_off is only valid while the actual main contract is the one it was measured on.
    if use_main and not (main_now is not None and main_now == p.get("basis_off_main")):
        if last_close is not None:
            px = float(last_close)
            return {
                "open": px,
                "high": px,
                "low": px,
                "close": px,
                "date": last_close_date or bar.get("date"),
            }, True, "roll_unpriced"
        return None, True, "roll_unpriced"
    cont = manage_ohlc_bar(bar, "continuous_proxy")
    if cont is None:
        return None, True, None
    off = float(p.get("basis_off") or 0.0)
    return (
        {k: (v + off if k in ("open", "high", "low", "close") else v) for k, v in cont.items()},
        True,
        None,
    )


def roll_open_gaps_through_stop(p: dict, old_open: float) -> bool:
    """Held (old) contract opens at/through the stop on the roll day → real stop gap, no roll."""
    stop = float(p["stop"])
    return (p["direction"] == "多" and float(old_open) <= stop) or (
        p["direction"] == "空" and float(old_open) >= stop
    )


def roll_position_at_open(
    p: dict,
    *,
    old_open: float,
    new_open: float,
    new_contract: str,
    day: str,
    mult: float,
    sign: int,
) -> float:
    """R6b-fix (b): move a continuous_proxy position to the new main at ``day`` open.

    Old contract is closed at ITS open, the new contract is opened at ITS open.
    Returns the price PnL booked on the old leg (``last_mark`` → old open). Stop,
    target and entry are translated by ``new_open - old_open`` (so the R-distance and
    the open are unchanged), ``last_mark`` becomes the new contract's open and
    ``held_contract`` the new contract. The caller books the 2 fill costs.
    """
    pnl = 0.0
    if p.get("last_mark") is not None:
        pnl = (float(old_open) - float(p["last_mark"])) * mult * p["lots"] * sign
    shift = float(new_open) - float(old_open)
    p.setdefault("entry_orig", p["entry"])
    p["entry"] = float(p["entry"]) + shift
    p["stop"] = float(p["stop"]) + shift
    p["target"] = float(p["target"]) + shift
    p["last_mark"] = float(new_open)
    old_contract = p.get("held_contract")
    p["held_contract"] = new_contract
    p.setdefault("roll_events", []).append(
        {
            "date": day,
            "from": old_contract,
            "to": new_contract,
            "old_open": float(old_open),
            "new_open": float(new_open),
            "shift": round(shift, 4),
            "status": "shifted",
        }
    )
    return pnl


def prepare_pack_for_execution(pack, *, root=None) -> dict:
    """Stamp delivery calendar + optional contract-fill overlay onto a backtest pack."""
    series, errors, sources = pack
    root = root or ROOT
    try:
        from research.execution.contract_pack import annotate_pack_calendar, overlay_contract_fills

        annotate_pack_calendar(series, root=root)
        report = overlay_contract_fills(series, root=root)
    except Exception as exc:  # noqa: BLE001
        report = {"ok": False, "error": str(exc), "fill_series": "continuous_proxy"}
    return report


def _fill_quality_bar(
    code: str,
    hist_bar: dict,
    meta: dict | None = None,
    *,
    atr: float | None = None,
    next_open: float | None = None,
    require_next_open: bool = False,
) -> dict:
    """Build classify_bar input for an intended fill (not a signal score)."""
    meta = meta or {}
    basis = str(meta.get("price_basis") or hist_bar.get("price_basis") or "continuous_proxy")
    allow = meta.get("allow_continuous_fill")
    if allow is None:
        allow = hist_bar.get("allow_continuous_fill")
    if allow is None:
        # Default: Path-A continuous main series is an executable proxy until contract packs exist.
        allow = basis in ("continuous_proxy", "continuous", "contract") and basis != "continuous_strict"
    if basis == "continuous" and allow is True:
        basis = "continuous_proxy"
    bar = {
        "code": code,
        "open": hist_bar.get("open"),
        "high": hist_bar.get("high"),
        "low": hist_bar.get("low"),
        "close": hist_bar.get("close"),
        "volume": hist_bar.get("volume"),
        "bar_date": hist_bar.get("date") or hist_bar.get("bar_date"),
        "atr": atr if atr is not None else hist_bar.get("atr"),
        "price_basis": basis,
        "allow_continuous_fill": bool(allow),
        "limit_status": hist_bar.get("limit_status") or hist_bar.get("limit_locked"),
        "limit_locked": hist_bar.get("limit_locked"),
        "delivery_restricted": hist_bar.get("delivery_restricted") or meta.get("delivery_restricted"),
        "near_delivery": hist_bar.get("near_delivery"),
        "roll_blocked": hist_bar.get("roll_blocked") or meta.get("roll_blocked"),
        "no_new_position": hist_bar.get("no_new_position"),
        "listed": hist_bar.get("listed", True),
        "next_open": next_open,
    }
    return bar


def entry_fill_allowed(
    code: str,
    hist_bar: dict,
    meta: dict | None = None,
    *,
    side: str | None = None,
    atr: float | None = None,
    asof: str | None = None,
    next_open: float | None = None,
    require_next_open: bool = False,
) -> tuple[bool, dict]:
    """Return (ok, quality_record). Non-PASS blocks new entries."""
    from research.data_quality import classify_bar

    bar = _fill_quality_bar(
        code,
        hist_bar,
        meta,
        atr=atr,
        next_open=next_open,
        require_next_open=require_next_open,
    )
    q = classify_bar(
        bar,
        asof=asof or str(bar.get("bar_date") or ""),
        side=side,
        require_next_open=require_next_open,
        next_open=next_open,
    )
    return q.get("status") == "PASS", q


def cost_scenario_kpi(out: dict) -> dict:
    """Compact KPI row for Base/Stress contrast tables."""
    return {
        "ok": out.get("ok"),
        "cost_scenario": out.get("cost_scenario"),
        "slippage_ticks": out.get("slippage_ticks"),
        "fee_mult": out.get("fee_mult"),
        "ret_pct": out.get("ret_pct"),
        "gross_ret_pct": out.get("gross_ret_pct"),
        "max_dd_pct": out.get("max_dd_pct"),
        "cost_yuan": out.get("cost_yuan"),
        "equity_end": out.get("equity_end"),
        "closed_trades": out.get("closed_trades"),
        "quality_blocks": out.get("quality_blocks"),
        "proxy_entry_share": out.get("proxy_entry_share"),
        "contract_entry_share": out.get("contract_entry_share"),
        "same_day_exit_n": out.get("same_day_exit_n"),
        "fill_series": out.get("fill_series"),
        "conclusion": out.get("conclusion"),
    }


def attach_cost_scenario_contrast(
    primary: dict,
    p: dict,
    mode: str,
    *,
    pack=None,
    scenarios: tuple[str, ...] = ("stress",),
) -> dict:
    """Re-run simulate on the same pack under stress/extreme; keep primary KPI as Base."""
    if not primary.get("ok"):
        return primary
    primary_name = str(primary.get("cost_scenario") or "base")
    rows = {primary_name: cost_scenario_kpi(primary)}
    try:
        from research.execution.cost_model import load_cost_scenario
    except Exception as exc:  # noqa: BLE001
        primary["cost_scenario_contrast"] = {"ok": False, "error": str(exc), "rows": rows}
        return primary
    pack = pack or (
        _LAST_PACK.get("series") and (_LAST_PACK["series"], _LAST_PACK.get("errors") or {}, _LAST_PACK.get("sources") or {})
    )
    if pack is None:
        primary["cost_scenario_contrast"] = {"ok": False, "error": "no_pack", "rows": rows}
        return primary
    for name in scenarios:
        name = str(name).lower()
        if name == primary_name:
            continue
        try:
            sc = load_cost_scenario(name, root=ROOT)
        except Exception as exc:  # noqa: BLE001
            rows[name] = {"ok": False, "error": str(exc)}
            continue
        other = _simulate_cfg(
            {**p, "slippage_ticks": sc["slippage_ticks"], "fee_mult": sc["fee_mult"], "cost_scenario": name},
            mode,
            pack=pack,
        )
        rows[name] = cost_scenario_kpi(other)
    primary["cost_scenario_contrast"] = {
        "ok": True,
        "primary": primary_name,
        "note": "Primary KPI remains Base; Stress/Extreme are contrast only.",
        "rows": rows,
    }
    return primary


def pack_sha256(series: dict) -> str:
    import hashlib

    blob = json.dumps(
        {k: v.get("hist") for k, v in sorted((series or {}).items())},
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_LAST_PACK: dict = {}


def _stable_sha256(obj) -> str:
    import hashlib

    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def n_trials_census(root: Path | None = None) -> dict:
    """Trials searched so far (DSR deflation): the max of 1 + archived parameter sets, the Path-A PBO
    trial matrix width and the rows summed over archive/shadow_strategy_*.json."""
    root = root or ROOT
    out: dict = {"archived_params_plus_current": 1, "pbo_matrix_n_trials": 0, "shadow_strategy_rows": 0,
                 "shadow_strategy_files": {}}
    try:
        rules = json.loads((root / "execution_rules.json").read_text(encoding="utf-8"))
        out["archived_params_plus_current"] = 1 + len(rules.get("archived_params") or [])
    except Exception:  # noqa: BLE001
        pass
    vdir = root / "lab" / "research" / "validation"
    for name in ("pbo_path_a_latest.json", "pbo_path_a_matrix.json"):
        try:
            obj = json.loads((vdir / name).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        k = (obj.get("matrix_meta") or {}).get("n_trials") or obj.get("n_trials")
        if k:
            out["pbo_matrix_n_trials"] = int(k)
            out["pbo_matrix_source"] = f"lab/research/validation/{name}"
            break
    for f in sorted((root / "archive").glob("shadow_strategy_*.json")):
        try:
            rows = json.loads(f.read_text(encoding="utf-8")).get("rows") or []
        except Exception:  # noqa: BLE001
            continue
        out["shadow_strategy_files"][f.name] = len(rows)
        out["shadow_strategy_rows"] += len(rows)
    out["n_trials"] = max(1, out["archived_params_plus_current"], out["pbo_matrix_n_trials"],
                          out["shadow_strategy_rows"])
    return out


def _carry_subset(curves: dict) -> dict:
    """Extract carry maps from curves; empty dict when mode did not load carry."""
    out = {}
    for c, cv in sorted((curves or {}).items()):
        if isinstance(cv, dict) and isinstance(cv.get("carry"), dict):
            out[c] = cv["carry"]
    return out


def write_input_snapshot(out: dict, argv: list[str], root: Path | None = None) -> dict:
    """Persist bars + post-lag member/seats + post-lag carry from last simulate()."""
    root = root or ROOT
    series = _LAST_PACK.get("series") or {}
    member = _LAST_PACK.get("member") or {}
    carry = _LAST_PACK.get("carry") or {}
    empty_why = []
    if not member:
        empty_why.append("member/seats empty (mode did not load seats/member, or no rows after lag)")
    if not carry:
        empty_why.append("carry empty (mode did not load curves, or no carry after lag)")
    note = "bars + post-lag member/seats + post-lag carry as fed to simulate"
    if empty_why:
        note += "; " + "; ".join(empty_why)
    snap = {
        "argv": list(argv),
        "start": out.get("start"),
        "end": out.get("end"),
        "availability_lag": out.get("availability_lag"),
        "fill_price": out.get("fill_price"),
        "slippage_ticks": out.get("slippage_ticks"),
        "git_sha": out.get("git_sha") or _git_sha(root),
        "universe_sha256": out.get("universe_sha256") or _file_sha256(root / "universe.json"),
        "execution_rules_sha256": out.get("execution_rules_sha256")
        or _file_sha256(root / "execution_rules.json"),
        "schema_version": out.get("schema_version") or SCHEMA_VERSION,
        "entry_filter": out.get("entry_filter"),
        "sources": _LAST_PACK.get("sources"),
        "errors": _LAST_PACK.get("errors"),
        "bars": {k: v.get("hist") for k, v in sorted(series.items())},
        "member": member,
        "carry": carry,
        "note": note,
    }
    # R7a-D: every listing-calendar candidate of the window, bars <= snapshot end, so replays need
    # no local contract cache.
    try:
        from research.data_quality.contract_cache import listed_candidates
        from research.data_quality.contract_store import build_bundle, resolve_store

        wanted = sorted({c for v in listed_candidates(series).values() for c in v})
        snap["contract_bars"] = build_bundle(
            resolve_store(_LAST_PACK.get("contract_root") or root), wanted, end=out.get("end"),
            meta={"source": "historical_backtest.write_input_snapshot"},
        )
    except Exception as exc:  # noqa: BLE001
        snap["contract_bars"] = {"error": str(exc)[:200]}
    blob = json.dumps(snap, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    sha = _stable_sha256(snap)
    d = root / "archive" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    tag = str(out.get("end") or "na").replace("-", "")
    f = d / f"bt_input_{tag}_{sha[:12]}.json"
    f.write_bytes(blob)
    return {
        "path": str(f.relative_to(root)),
        "sha256": sha,
        "bars_sha256": pack_sha256(series),
        "member_sha256": _stable_sha256(member),
        "seats_sha256": _stable_sha256(member),
        "carry_sha256": _stable_sha256(carry),
        "contract_bars_sha256": _stable_sha256(snap.get("contract_bars") or {}),
        "contract_bars_n": (snap.get("contract_bars") or {}).get("n_contracts"),
        "symbols": len(series),
    }


def _load_cfg():
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    observe = cfg.get("observe") or {}
    use_observe = "--observe" in sys.argv
    # Observe mode: amplify equity base for 1-lot futures + option-premium overlay.
    if use_observe and observe.get("equity") is not None:
        equity = float(observe["equity"])
    else:
        equity = float(cfg.get("equity", 200_000))
    compound = bool(cfg.get("equity_compound", True))
    risk_pct = float(cfg.get("risk_pct", 1.5))
    l1_mult = float(cfg.get("l1_mult", 1.0))
    max_positions = int(cfg.get("max_positions", 3))
    max_gross_pct = float(cfg.get("max_gross_exposure_pct", 50))
    max_port_risk = float(cfg.get("max_portfolio_risk_pct", 8))
    max_per_bucket = int(cfg.get("max_per_bucket", 1))
    min_r20 = float(cfg.get("min_r20_pct", 3))
    min_r60 = float(cfg.get("min_r60_pct", 5))
    min_lots = int(observe.get("min_lots") if use_observe else cfg.get("min_lots") or 0)
    oh_src = observe if use_observe and (observe.get("option_hedge") or hedge_enabled(observe)) else cfg
    oh = hedge_params(oh_src) if hedge_enabled(oh_src) else {"premium_atr_mult": 0.0, "strike_atr_mult": 0.0}
    sel = cfg.get("selection") or {}
    reward_rr = float(sel.get("reward_rr") or cfg.get("reward_rr") or 2)
    stop_atr_mult = float(sel.get("stop_atr_mult") or cfg.get("stop_atr_mult") or 1)
    return {
        "cfg": cfg,
        "equity0": equity,
        "compound": compound,
        "risk_pct": risk_pct,
        "l1_mult": l1_mult,
        "max_positions": max_positions,
        "max_gross_pct": max_gross_pct,
        "max_port_risk": max_port_risk,
        "max_per_bucket": max_per_bucket,
        "min_r20": min_r20,
        "min_r60": min_r60,
        "min_lots": min_lots,
        "option_hedge": hedge_enabled(oh_src),
        "premium_atr_mult": float(oh.get("premium_atr_mult") or 0),
        "strike_atr_mult": float(oh.get("strike_atr_mult") or 0),
        "observe_mode": use_observe,
        "reward_rr": reward_rr,
        "stop_atr_mult": stop_atr_mult,
        "entry_filter": cfg.get("entry_filter") or "base",
        "carry_bypass": carry_bypass_cfg(cfg.get("carry_bypass")),
        "vol_bypass": vol_bypass_cfg(cfg.get("vol_bypass")),
        "availability_lag": _cli_int(
            "--lag",
            int((cfg.get("backtest") or {}).get("availability_lag_days", DEFAULT_AVAILABILITY_LAG)),
        ),
        "fill_price": _cli_str(
            "--fill",
            str((cfg.get("backtest") or {}).get("fill_price", DEFAULT_FILL_PRICE)),
        ),
        "slippage_ticks": float(
            (cfg.get("slippage_ticks") if cfg.get("slippage_ticks") is not None else load_slippage_ticks(ROOT))
        ),
    }


def _cli_val(flag: str):
    for k, a in enumerate(sys.argv):
        if a == flag and k + 1 < len(sys.argv):
            return sys.argv[k + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def _cli_int(flag: str, default: int) -> int:
    v = _cli_val(flag)
    return int(v) if v is not None else int(default)


def _cli_str(flag: str, default: str) -> str:
    v = _cli_val(flag)
    return v if v is not None else default


# R8 research-only overrides.  They only take effect together with --out (never on the formal path).
R8_VALUE_FLAGS = ("--equity",)
R8_SWITCH_FLAGS = ("--filter-unit-risk", "--filter-atr-spike")


def _r8_flags_present() -> bool:
    for a in sys.argv:
        if a in R8_SWITCH_FLAGS:
            return True
        if any(a == f or a.startswith(f + "=") for f in R8_VALUE_FLAGS):
            return True
    return False


def r8_overrides_from_argv() -> dict:
    """Parse ``--equity YUAN`` / ``--filter-unit-risk`` / ``--filter-atr-spike`` into p-keys
    (``equity0`` / ``filter_unit_risk`` / ``filter_atr_spike``).  Only flags that were given appear.

    Raises ValueError for ``--equity`` without a value or with a malformed / non-positive value."""
    out: dict = {}
    if any(a == "--equity" or a.startswith("--equity=") for a in sys.argv):
        raw = _cli_val("--equity")
        if raw is None:
            raise ValueError("--equity needs a value")
        try:
            v = float(raw)
        except ValueError as exc:
            raise ValueError(f"--equity: bad value {raw!r}") from exc
        if not v > 0:
            raise ValueError(f"--equity: {raw!r} must be > 0")
        out["equity0"] = v
    if "--filter-unit-risk" in sys.argv:
        out["filter_unit_risk"] = True
    if "--filter-atr-spike" in sys.argv:
        out["filter_atr_spike"] = True
    return out


def _answer_text(res: dict) -> str:
    if not res.get("ok"):
        raise RuntimeError(json.dumps(res, ensure_ascii=False)[:400])
    text = res["data"]["result"]["content"][0]["text"]
    try:
        payload = json.loads(text)
        return payload.get("data", {}).get("answer", text)
    except Exception:
        return text


def _to_float(x):
    if x is None:
        return None
    s = str(x).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "—", "NA", "N/A", "\t"):
        return None
    # 成交量 occasionally like 101.96万
    m = re.match(r"^(-?\d+\.?\d*)\s*万$", s)
    if m:
        return float(m.group(1)) * 10_000
    try:
        return float(s)
    except Exception:
        return None


def _looks_like_yyyymmdd(n: float | None) -> bool:
    if n is None:
        return False
    if abs(n - round(n)) > 1e-9:
        return False
    v = int(round(n))
    if not (20000101 <= v <= 20991231):
        return False
    mm, dd = (v // 100) % 100, v % 100
    return 1 <= mm <= 12 and 1 <= dd <= 31


def _norm_date(s: str) -> str | None:
    s = str(s or "").strip()
    if re.fullmatch(r"20\d{6}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if re.fullmatch(r"20\d{2}-\d{1,2}-\d{1,2}", s):
        y, m, d = s.split("-")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return None


def _col_key(h: str) -> str:
    h = str(h or "").strip().lower()
    if "日期" in h or h in ("date", "time"):
        return "date"
    if "开盘" in h or h == "open":
        return "open"
    if "最高" in h or h == "high":
        return "high"
    if "最低" in h or h == "low":
        return "low"
    if "收盘" in h or h in ("close", "settle", "结算"):
        return "close"
    if "成交量" in h or "volume" in h or "量" == h:
        return "volume"
    if "成交额" in h or "amount" in h:
        return "amount"
    if "代码" in h or "code" in h:
        return "code"
    if "名称" in h or "name" in h:
        return "name"
    return h


def _parse_md_tables(ans: str) -> list[list[dict]]:
    """Parse all markdown tables into list of row dicts keyed by normalized headers."""
    lines = [ln.strip() for ln in ans.splitlines()]
    tables = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("|"):
            i += 1
            continue
        block = []
        while i < len(lines) and lines[i].startswith("|"):
            block.append(lines[i])
            i += 1
        if len(block) < 2:
            continue
        headers = [c.strip() for c in block[0].strip("|").split("|")]
        body = block[1:]
        if body and re.match(r"^\|[\s\-:|]+\|$", body[0]):
            body = body[1:]
        rows = []
        for ln in body:
            if re.match(r"^\|[\s\-:|]+\|$", ln):
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) < 2:
                continue
            row = {}
            for j, h in enumerate(headers):
                if j >= len(cells):
                    break
                row[_col_key(h)] = cells[j]
            rows.append(row)
        if rows:
            tables.append(rows)
    return tables


def _row_to_bar(row: dict) -> dict | None:
    d = _norm_date(row.get("date") or "")
    if not d:
        # sometimes date is a bare YYYYMMDD in a wrong column
        for v in row.values():
            d = _norm_date(str(v))
            if d:
                break
    if not d:
        return None
    close = _to_float(row.get("close"))
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    open_ = _to_float(row.get("open"))
    # if only one price field filled, use it
    prices = [p for p in (close, high, low, open_) if p is not None and not _looks_like_yyyymmdd(p)]
    if not prices:
        return None
    if close is None or _looks_like_yyyymmdd(close):
        close = prices[-1]
    if high is None or _looks_like_yyyymmdd(high):
        high = max(prices)
    if low is None or _looks_like_yyyymmdd(low):
        low = min(prices)
    if not (50 <= abs(close) <= 200_000):
        return None
    if high < low:
        high, low = low, high
    if low <= 0 or close <= 0 or not (low <= close <= high):
        return None
    if high / low > 5:
        return None
    return {
        "date": d,
        "high": high,
        "low": low,
        "close": close,
        "open": open_ if open_ is not None and not _looks_like_yyyymmdd(open_) and low <= open_ <= high else None,
        "volume": _to_float(row.get("volume")),
    }


def _parse_zl_history(ans: str, *, max_date: date | None = None) -> list[dict]:
    """Parse iFinD history and reject dates beyond the latest closed CN session."""
    if max_date is None:
        from market_data import latest_expected_session_date

        max_date = latest_expected_session_date()
    max_iso = max_date.isoformat()
    bars = {}
    for table in _parse_md_tables(ans):
        for row in table:
            bar = _row_to_bar(row)
            if bar and bar["date"] <= max_iso:
                bars[bar["date"]] = bar
    # fallback regex for date + 3 numbers (legacy)
    if len(bars) < 10:
        for line in ans.splitlines():
            m = re.search(
                r"(20\d{6}|20\d{2}-\d{1,2}-\d{1,2}).{0,80}?(\d+\.?\d*).{0,40}?(\d+\.?\d*).{0,40}?(\d+\.?\d*)",
                line,
            )
            if not m:
                continue
            d = _norm_date(m.group(1))
            if not d or d > max_iso:
                continue
            nums = [_to_float(m.group(i)) for i in (2, 3, 4)]
            nums = [n for n in nums if n is not None and not _looks_like_yyyymmdd(n) and 50 <= abs(n) <= 200_000]
            if len(nums) < 1:
                continue
            if len(nums) >= 3:
                high, low, cl = nums[0], nums[1], nums[2]
            else:
                high = low = cl = nums[0]
            if high < low:
                high, low = low, high
            if low <= 0 or cl <= 0 or not (low <= cl <= high) or high / low > 5:
                continue
            bars[d] = {"date": d, "high": high, "low": low, "close": cl, "volume": None}
    cutoff = (date.today() - timedelta(days=CUTOFF_DAYS)).isoformat()
    from market_data import filter_bars_asof

    return filter_bars_asof(
        [bars[k] for k in sorted(bars) if cutoff <= k <= max_iso],
        max_date=max_date,
    )


def _ifind_ready() -> bool:
    """True when an iFinD token is actually usable (last-resort fill)."""
    try:
        from ifind_call import AUTH_TOKEN, CONFIG

        if AUTH_TOKEN:
            return True
        cfg = CONFIG or {}
        return bool(cfg.get("auth_token") or cfg.get("auth_token_backup"))
    except Exception:
        return False


def _fetch_ifind_recent_history(u: dict, expected: date) -> list[dict]:
    """One bounded iFinD request to fill a recent gap; never refetch a full year."""
    if not _ifind_ready():
        return []
    ticker = u.get("ticker") or ""
    name = u.get("name") or ticker
    start = (expected - timedelta(days=20)).isoformat()
    q = (
        f"证券代码{ticker}（{name}主力连续）从{start}到{expected.isoformat()}的交易日行情，"
        "只返回实际已发生交易日期；字段为日期、开盘价、最高价、最低价、收盘价、成交量。"
        "按日期升序输出Markdown表，不得补造、推测或输出未来日期。"
    )
    try:
        ans = _answer_text(call("future", "future_quotes", {"query": q}))
    except Exception as exc:
        print(f"    {ticker} recent-gap fetch failed: {exc}")
        return []
    rows = _parse_zl_history(ans, max_date=expected)
    floor = (expected - timedelta(days=20)).isoformat()
    return [row for row in rows if floor <= row["date"] <= expected.isoformat()]


def _fetch_ifind_history(u: dict, n: int = LOOKBACK_DAYS):
    """iFinD 主力连续 fallback. Only after free + TqSdk still short/stale."""
    if not _ifind_ready():
        return []
    name = u["name"]
    ticker = u.get("ticker") or ""
    by = {}
    last_ans = ""

    # Prefer ticker-targeted monthly/quarterly chunks
    today = date.today()
    cursor = today.replace(day=1)
    chunks = []
    for _ in range(5):
        y, m = cursor.year, cursor.month
        m0 = m - 2
        y0 = y
        while m0 <= 0:
            m0 += 12
            y0 -= 1
        chunks.append((f"{y0}-{m0:02d}", f"{y}-{m:02d}"))
        m -= 3
        while m <= 0:
            m += 12
            y -= 1
        cursor = date(y, m, 1)

    for start_ym, end_ym in reversed(chunks):
        q = (
            f"证券代码{ticker}（{name}主力连续）从{start_ym}到{end_ym}每个交易日的"
            f"日期、开盘价、最高价、最低价、收盘价、成交量。"
            f"一张Markdown表；日期用YYYYMMDD或YYYY-MM-DD；价格为真实行情。"
        )
        try:
            ans = _answer_text(call("future", "future_quotes", {"query": q}))
            last_ans = ans
            for h in _parse_zl_history(ans):
                by[h["date"]] = h
            print(f"    {ticker} chunk {start_ym}->{end_ym} bars={len(by)}")
        except Exception as e:
            print(f"    {ticker} chunk fail {start_ym}: {e}")

    if len(by) < WARMUP + 20:
        q2 = (
            f"{ticker} {name}主力连续最近{n}个交易日日期、最高价、最低价、收盘价、成交量，"
            f"Markdown表"
        )
        try:
            ans2 = _answer_text(call("future", "future_quotes", {"query": q2}))
            last_ans = ans2
            for h in _parse_zl_history(ans2):
                by[h["date"]] = h
        except Exception as e:
            print(f"    fallback fail: {e}")

    hist = [by[k] for k in sorted(by)]
    return hist


def fetch_history(u: dict, n: int = LOOKBACK_DAYS):
    """Sina first; TqSdk main continuous; iFinD only if still short/stale."""
    from market_data import (
        fill_main_with_tqsdk,
        latest_expected_session_date,
        load_free_bars,
        merge_bars,
        save_chart_history,
        series_sufficient,
        trim_bars,
    )

    code = u.get("code") or ""
    free, meta = load_free_bars(code)
    need = max(80, WARMUP + 20)
    expected = latest_expected_session_date()
    expected_iso = expected.isoformat()
    meta["expected_session_date"] = expected_iso
    # Defensive filter: even a poisoned local/free cache must not move the
    # strategy or seat calendar into the future.
    free = [bar for bar in free if str(bar.get("date") or "") <= expected_iso]
    meta["free_n"] = len(free)
    meta["last"] = free[-1]["date"] if free else None
    meta["tqsdk"] = False
    meta["tqsdk_n"] = 0
    meta["ifind"] = False
    meta["ifind_n"] = 0

    bars = free
    chart_dirty = False

    def _tag_source(extra: str) -> None:
        cur = meta.get("source") or ""
        meta["source"] = f"{cur}+{extra}" if cur else extra

    def _apply_tqsdk(*, length: int, need_date: date | None) -> None:
        nonlocal bars, chart_dirty
        filled, tmeta = fill_main_with_tqsdk(
            code, bars, need_date=need_date, root=ROOT, length=length
        )
        meta["tqsdk"] = bool(tmeta.get("tqsdk"))
        meta["tqsdk_n"] = int(tmeta.get("tqsdk_n") or 0)
        meta["tqsdk_error"] = tmeta.get("tqsdk_error") or ""
        meta["tqsdk_source"] = tmeta.get("tqsdk_source") or ""
        if tmeta.get("tqsdk"):
            bars = [bar for bar in filled if str(bar.get("date") or "") <= expected_iso]
            _tag_source("tqsdk")
            chart_dirty = True

    if series_sufficient(free, need):
        if free and free[-1]["date"] < expected_iso:
            # Enough history: recent gap only — TqSdk first, iFinD last resort.
            _apply_tqsdk(length=max(40, need), need_date=expected)
            if not bars or bars[-1]["date"] < expected_iso:
                ifind = _fetch_ifind_recent_history(u, expected)
                if ifind:
                    bars = merge_bars(bars, ifind)
                    bars = [bar for bar in bars if str(bar.get("date") or "") <= expected_iso]
                    meta["ifind"] = True
                    meta["ifind_n"] = len(ifind)
                    _tag_source("ifind")
                    chart_dirty = True
        else:
            bars = free
    else:
        # Short history: TqSdk main continuous first; iFinD only if still insufficient.
        _apply_tqsdk(length=max(n, need + 20), need_date=None)
        if not series_sufficient(bars, need) or (
            bars and bars[-1]["date"] < expected_iso
        ):
            ifind = _fetch_ifind_history(u, n)
            if ifind:
                bars = merge_bars(bars, ifind)
                bars = [bar for bar in bars if str(bar.get("date") or "") <= expected_iso]
                meta["ifind"] = True
                meta["ifind_n"] = len(ifind)
                _tag_source("ifind")
                chart_dirty = True

    if chart_dirty:
        chart_cache = save_chart_history(code, bars)
        meta["chart_cache"] = str(chart_cache.relative_to(ROOT)) if chart_cache else None

    # Apply the same upper bound after merging, including any existing cache rows.
    bars = [bar for bar in bars if str(bar.get("date") or "") <= expected_iso]
    bars = trim_bars(bars, CUTOFF_DAYS)
    meta["bars"] = len(bars)
    meta["last"] = bars[-1]["date"] if bars else None
    meta["fresh_for_expected_session"] = bool(bars and bars[-1]["date"] >= expected.isoformat())
    print(
        f"  source={meta.get('source')} sina={meta.get('sina_n')} "
        f"tqsdk={meta.get('tqsdk')} ifind={meta.get('ifind')} bars={len(bars)} "
        f"last={bars[-1]['date'] if bars else '-'}"
    )
    return bars, meta


def atr14(hist, i):
    if i < 14:
        return None
    trs = []
    for j in range(i - 13, i + 1):
        h, l, pc = hist[j]["high"], hist[j]["low"], hist[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / 14.0


def _sma_key(hist, i, n, key):
    if i < n - 1:
        return None
    vals = []
    for j in range(i - n + 1, i + 1):
        v = hist[j].get(key)
        if v is None:
            return None
        vals.append(float(v))
    return sum(vals) / n


def composite_trend(hist, i, short=20, long=60, vol_n=20):
    """F = ((MA_s-MA_l)/MA_l) * (mean range / today's range) * (volume / MA volume)."""
    if i < long - 1:
        return None
    ma_s = _sma_key(hist, i, short, "close")
    ma_l = _sma_key(hist, i, long, "close")
    if not ma_s or not ma_l:
        return None
    trend = (ma_s - ma_l) / ma_l
    ranges = []
    for j in range(i - vol_n + 1, i + 1):
        high, low, close = hist[j].get("high"), hist[j].get("low"), hist[j].get("close")
        if high is None or low is None or not close:
            return None
        ranges.append((float(high) - float(low)) / float(close))
    today_r = ranges[-1]
    mean_r = sum(ranges) / len(ranges)
    if today_r <= 0 or mean_r <= 0:
        return None
    vols = []
    for j in range(i - vol_n + 1, i + 1):
        v = hist[j].get("volume")
        if v is None:
            vols = None
            break
        vols.append(float(v))
    if not vols or sum(vols) <= 0:
        q = 1.0
    else:
        ma_v = sum(vols) / len(vols)
        q = (vols[-1] / ma_v) if ma_v > 0 else 1.0
    return {"f": trend * (mean_r / today_r) * q, "t": trend, "r": today_r, "q": q}


def ret_n(hist, i, n):
    if i < n:
        return None
    a, b = hist[i - n]["close"], hist[i]["close"]
    if not a:
        return None
    return (b / a - 1.0) * 100.0


def _book_usage(pos, idx, series, d, *, atr_fn=None, close_fn=None):
    """Open-book usage on day ``d`` (R4): (used_gross, used_risk, held_buckets).

    * notional = lots × close × mult.  ``close_fn(code, p, i, d)`` may supply the held
      contract's real close (contract positions); default = continuous close.
    * risk = lots × ATR × mult with ``atr_fn(code, hist, i)`` (simulate passes the R6c
      adjusted ATR); falls back to the position's entry ATR.
    * a position with no bar on ``d`` is still counted (last mark / entry price) —
      leaving it out would only under-state the book.
    """
    used_gross = used_risk = 0.0
    buckets: dict[str, int] = {}
    for code_, p_ in pos.items():
        b_ = str(p_.get("bucket") or "_")
        buckets[b_] = buckets.get(b_, 0) + 1
        h_ = series[code_]["hist"]
        m_ = float(series[code_]["meta"]["mult"])
        n_ = abs(int(p_["lots"]))
        i_ = idx[code_].get(d)
        if i_ is None:
            px_ = p_.get("last_mark") or p_.get("entry") or 0.0
            used_gross += n_ * float(px_) * m_
            used_risk += n_ * float(p_.get("atr") or 0.0) * m_
            continue
        px_ = None
        if close_fn is not None:
            px_ = close_fn(code_, p_, i_, d)
        if px_ is None:
            px_ = h_[i_]["close"]
        used_gross += n_ * float(px_) * m_
        a_ = (atr_fn(code_, h_, i_) if atr_fn is not None else atr14(h_, i_)) or float(p_.get("atr") or 0.0)
        used_risk += n_ * float(a_) * m_
    return used_gross, used_risk, buckets


def _downsample_weekly(curve: list[dict]) -> list[dict]:
    if not curve:
        return []
    out = []
    last_week = None
    for row in curve:
        y, m, d = row["date"].split("-")
        week = f"{y}-W{int(d) // 7}"
        if week != last_week:
            out.append(row)
            last_week = week
    if curve and (not out or out[-1]["date"] != curve[-1]["date"]):
        out.append(curve[-1])
    return out


def _write_equity_svg(curve: list[dict], path: Path, title: str):
    if len(curve) < 2:
        return None
    eq = [c["equity"] for c in curve]
    lo, hi = min(eq), max(eq)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    w, h, l, r, t, b = 920, 360, 56, 24, 36, 40
    pw, ph = w - l - r, h - t - b

    def x(i):
        return l + pw * (i / (len(curve) - 1))

    def y(v):
        return t + ph * (1 - (v - lo) / (hi - lo))

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(eq))
    grids = []
    for k in range(5):
        yy = t + ph * k / 4
        val = hi - (hi - lo) * k / 4
        grids.append(
            f'<line x1="{l}" y1="{yy:.1f}" x2="{w-r}" y2="{yy:.1f}" stroke="#e5e5e5"/>'
            f'<text x="{l-8}" y="{yy+4:.1f}" text-anchor="end" font-size="11" fill="#666">{val:,.0f}</text>'
        )
    labels = []
    for i in (0, len(curve) // 2, len(curve) - 1):
        labels.append(
            f'<text x="{x(i):.1f}" y="{h-12}" text-anchor="middle" font-size="11" fill="#666">{curve[i]["date"]}</text>'
        )
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <rect width="100%" height="100%" fill="#fff"/>
  <text x="{l}" y="22" font-size="15" font-family="Segoe UI,sans-serif" fill="#111">{title}</text>
  {''.join(grids)}
  <polyline fill="none" stroke="#2563eb" stroke-width="2" points="{pts}"/>
  {''.join(labels)}
  <text x="{w/2}" y="{h-2}" text-anchor="middle" font-size="10" fill="#999">主力连续 ZL · Path-A TSMOM+ATR</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")
    return path


def _fetch_pack(symbols):
    series = {}
    errors = {}
    sources = {}
    for u in symbols:
        code = u["code"]
        print(f"[bt] fetch {code} {u.get('ticker')} {u['name']}...")
        try:
            hist, meta = fetch_history(u)
            series[code] = {"meta": u, "hist": hist}
            sources[code] = {k: v for k, v in (meta or {}).items() if k != "code"}
            print(
                f"  bars={len(hist)} "
                f"range={hist[0]['date'] if hist else '-'}→{hist[-1]['date'] if hist else '-'}"
            )
        except Exception as e:
            errors[code] = str(e)[:200]
            print(f"  ERR {e}")
    return series, errors, sources


# Target reward:risk and stop width, in ATR units. Execution book only (no option overlay).
RR_GRID = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
STOP_GRID = (0.8, 1.0, 1.2)

# name, strike_atr_mult, premium_atr_mult. None = futures only, same equity and min lot.
HEDGE_GRID = (
    ("fut_only", None, None),
    ("k1_p2", 1.0, 2.0),
    ("atm_p2", 0.0, 2.0),
    ("k1_p06", 1.0, 0.6),
    ("atm_p06", 0.0, 0.6),
)


def simulate(
    symbols,
    equity0,
    *,
    compound=True,
    risk_pct=1.5,
    l1_mult=1.0,
    max_positions=3,
    max_gross_pct=50.0,
    max_port_risk=8.0,
    max_per_bucket=1,
    min_r20=3.0,
    min_r60=5.0,
    min_lots=0,
    option_hedge=False,
    premium_atr_mult=2.0,
    strike_atr_mult=1.0,
    reward_rr=2.0,
    stop_atr_mult=1.0,
    mode="p0",
    pack=None,
    carry_bypass=None,
    vol_bypass=None,
    availability_lag=DEFAULT_AVAILABILITY_LAG,
    fill_price=DEFAULT_FILL_PRICE,
    slippage_ticks=None,
    fee_mult=1.0,
    cost_scenario="base",
    enforce_tradability=True,
    freeze_fix=True,
    max_stale_days=MAX_STALE_DAYS,
    delivery_guard=True,
    min_seat_days=MIN_SEAT_DAYS,
    entry_delivery_buffer=ENTRY_DELIVERY_BUFFER,
    entry_delivery_action=ENTRY_DELIVERY_ACTION,
    adjusted_signals=None,
    caps_include_book=None,
    candidate_log=None,
    contract_root=None,
    state_log=None,
    filter_unit_risk=False,
    filter_atr_spike=False,
    filter_unit_risk_budget=False,
    long_sample=None,
):
    # R8 long-sample hooks (research only; ``None`` = formal behaviour, byte-identical).  Keys:
    #   main_map                prebuilt MainMap (official-data main, guard applied) replacing build_main_map
    #   skip_contract_overlay   do not stamp the calendar front-contract overlay (series is already the stitched main)
    #   no_minute               never read the local 15m minute cache (official-data-only run)
    #   candidate_pool          object with begin_day(d, equity) / allows(code, d) (candidate C); see entry_filters
    _ls = long_sample or {}
    if fill_price not in FILL_PRICES:
        raise ValueError(f"fill_price must be one of {FILL_PRICES}")
    cost_scenario = str(cost_scenario or "base").strip().lower()
    if slippage_ticks is None:
        try:
            slippage_ticks = load_slippage_ticks(ROOT, scenario=cost_scenario)
        except Exception:
            slippage_ticks = load_slippage_ticks(ROOT)
    slippage_ticks = float(slippage_ticks)
    fee_mult = abs(float(fee_mult if fee_mult is not None else 1.0))
    if fee_mult == 1.0 and cost_scenario != "base":
        try:
            from research.execution.cost_model import load_cost_scenario as _lcs

            fee_mult = float(_lcs(cost_scenario, root=ROOT).get("fee_mult") or 1.0)
        except Exception:
            pass
    bypass = carry_bypass_cfg(carry_bypass)
    vbypass = vol_bypass_cfg(vol_bypass)
    if pack is None:
        series, errors, sources = _fetch_pack(symbols)
        pack = (series, errors, sources)
    else:
        series, errors, sources = pack
    from research.data_quality.contract_store import ContractStore

    # R5a / R7a-D: injectable contract source (a cache root or a ContractStore, e.g. a snapshot bundle)
    _croot = (
        contract_root if isinstance(contract_root, ContractStore)
        else (Path(contract_root) if contract_root else ROOT)
    )
    if _ls.get("skip_contract_overlay"):
        contract_pack_report = {
            "ok": True,
            "fill_series": "continuous_proxy",
            "note": "long_sample: stitched official main-contract series; no calendar front-contract overlay",
        }
    else:
        contract_pack_report = prepare_pack_for_execution(pack, root=_croot)
    series, errors, sources = pack
    _LAST_PACK.clear()
    _LAST_PACK.update(
        {
            "series": series,
            "sources": sources,
            "errors": errors,
            "member": {},
            "carry": {},
            "contract_pack": contract_pack_report,
            "contract_root": _croot,
        }
    )

    date_hits = Counter()
    for s in series.values():
        for h in s["hist"]:
            date_hits[h["date"]] += 1
    min_cover = max(3, len(series) // 3)
    dates = sorted(d for d, c in date_hits.items() if c >= min_cover)
    if len(dates) < WARMUP + 5:
        dates = sorted(date_hits.keys())[-LOOKBACK_DAYS:]
    if len(dates) < WARMUP + 5:
        return {
            "ok": False,
            "error": "history too short after Sina/Tencent window",
            "errors": errors,
            "bars": {k: len(v["hist"]) for k, v in series.items()},
        }

    idx = {code: {h["date"]: i for i, h in enumerate(s["hist"])} for code, s in series.items()}

    equity = equity0
    gross_equity = equity0
    peak = equity
    gross_peak = equity0
    max_dd = 0.0
    gross_max_dd = 0.0
    cost_total = 0.0
    premium_total = 0.0
    hedge_payoff_total = 0.0
    curve = []
    day_pnls = []
    pos: dict = {}
    trade_exits = {"target": 0, "stop": 0, "signal": 0}
    freeze_stats = {"proxied_bar_days": 0, "delivery_exits": 0, "freeze_exits": 0}
    closed_pnls = []
    block_counts: dict[str, int] = {}
    quality_blocks: dict[str, int] = {}

    trade_dates = dates[WARMUP:]
    curves = {}
    if mode == "roll" or mode not in ("base", "seats", "ctf") or bypass.get("enabled"):
        curves = load_curves([u["code"] for u in symbols])
        curves = lag_curves_carry(curves, dates, availability_lag)
    member = {}
    lag = max(0, int(availability_lag))
    # fix3-opt ③: load seats over the whole bar window (incl. WARMUP) so the as-of-T
    # seat-day count includes real pre-window sessions (CZCE/SHFE prints from 2025-09-22).
    member_dates = dates
    if mode == "member":
        member = lag_member(load_member_changes(member_dates, [c for c in series]), member_dates, lag)
    elif mode in ("seats", "roll"):
        member = lag_member(load_member_seats(member_dates, [c for c in series]), member_dates, lag)
    # fix3: seat coverage gate: a variety with < min_seat_days post-lag seat
    # sessions as of T skips the formal seat filter that day (missing book => no block).
    # As-of-T: count post-lag seat sessions visible on/before T (truncation-safe).
    import bisect as _bisect

    seat_dates = {c: sorted(str(k) for k, v in (m or {}).items() if isinstance(v, dict)) for c, m in member.items()}
    seat_cov = {c: len(v) for c, v in seat_dates.items()}
    seat_short: dict[str, int] = {}

    def _seat_days_upto(code_: str, day_: str) -> int:
        return _bisect.bisect_right(seat_dates.get(code_) or [], str(day_))

    delivery_entry_blocks: dict[str, int] = {}

    # Snapshot inputs must match what the backtest actually consumes (post-lag).
    _LAST_PACK["member"] = member
    _LAST_PACK["carry"] = _carry_subset(curves)
    seat_follows: dict[str, int] = {}
    sleeve_counts: dict[str, int] = {}
    bypass_counts: dict[str, int] = {}
    vol_bypass_counts: dict[str, int] = {}
    try:
        from research.data_quality.main_map import build_main_map
    except Exception:  # noqa: BLE001
        build_main_map = None  # type: ignore[assignment]
    main_map = None
    if freeze_fix and _ls.get("main_map") is not None:
        main_map = _ls["main_map"]
    elif freeze_fix and build_main_map is not None:
        main_map = build_main_map(series, root=_croot, start=trade_dates[0])
    _pool = _ls.get("candidate_pool")
    pool_blocked: dict[str, int] = {}
    # R6c: roll-free r20/r60, same-contract ATR14 and vol for SIGNALS only (fills, stops,
    # target tests and mark-to-market keep using real prices).  ``adjusted_signals=False``
    # reproduces the R6b-fix signal inputs (raw continuous series).
    use_adjusted = bool(freeze_fix if adjusted_signals is None else adjusted_signals)
    adj: dict = {}
    if use_adjusted and main_map is not None:
        from research.data_quality.adjusted import build_adjusted_pack

        adj = build_adjusted_pack(series, main_map, root=_croot)
    signal_candidates_n = 0
    # R4: portfolio caps (gross / ATR risk / bucket) count the open book.  ``False`` reproduces
    # the R6c behaviour (caps applied to the day's candidates only) but still measures usage.
    use_book_caps = bool(freeze_fix if caps_include_book is None else caps_include_book)
    caps_entry_gross_max = 0.0
    caps_entry_risk_max = 0.0
    caps_scaled_n = 0
    caps_topup_lots = 0
    caps_topup_revived = 0
    caps_entry_days = 0
    caps_entry_log: list[dict] = []
    # R8b research-only entry filters (all OFF by default; see research/execution/entry_filters.py)
    entry_filters_on = bool(filter_unit_risk or filter_atr_spike or filter_unit_risk_budget)
    ef_hits = {"unit_notional": 0, "unit_risk": 0, "atr_spike": 0, "atr_spike_unavailable": 0, "evaluated": 0}
    ef_log: list[dict] = []
    if entry_filters_on:
        from research.execution import entry_filters as _ef

    # R5b: position management and T+1 fills live in book_core (shared with paper_book).
    eng = PositionEngine(
        series=series,
        idx=idx,
        main_map=main_map,
        adj=adj,
        curves=curves,
        mode=mode,
        contract_root=_croot,
        minute_root=ROOT,
        freeze_fix=freeze_fix,
        delivery_guard=delivery_guard,
        max_stale_days=max_stale_days,
        fill_price=fill_price,
        slippage_ticks=slippage_ticks,
        fee_mult=fee_mult,
        enforce_tradability=enforce_tradability,
        entry_delivery_buffer=entry_delivery_buffer,
        entry_delivery_action=entry_delivery_action,
        option_hedge=option_hedge,
        premium_atr_mult=premium_atr_mult,
        strike_atr_mult=strike_atr_mult,
        max_positions=max_positions,
        max_per_bucket=max_per_bucket,
        trade_exits=trade_exits,
        freeze_stats=freeze_stats,
        sleeve_counts=sleeve_counts,
        quality_blocks=quality_blocks,
        block_counts=block_counts,
        delivery_entry_blocks=delivery_entry_blocks,
        closed=closed_pnls,
    )
    if _ls.get("no_minute"):
        eng._load_minute = None  # official-data-only run: never read the local 15m minute cache
    _held_close = eng.held_close
    _ret = eng.ret
    _atr = eng.atr
    _delivery_window_block = eng.delivery_window_block
    for di, d in enumerate(trade_dates):
        price_pnl = 0.0
        day_cost = 0.0
        prev_d = trade_dates[di - 1] if di > 0 else None

        # 1) manage open positions: stop / target / signal flip (+ option payoff)
        nxt = trade_dates[di + 1] if di + 1 < len(trade_dates) else None
        _acc = {"price_pnl": price_pnl, "day_cost": day_cost}
        for code, p in list(pos.items()):
            _row = eng.manage(code, p, d, prev_d=prev_d, nxt=nxt, acc=_acc)
            if _row is not None:
                if str(_row.get("entry_date") or "")[:10] > str(d)[:10]:
                    raise AssertionError(f"exit before entry: {code} entry={_row.get('entry_date')} exit={d}")
                del pos[code]
        price_pnl, day_cost = _acc["price_pnl"], _acc["day_cost"]

        # 2) Path-A entries with ATR stop/target (RR=reward_rr)
        cands = []
        _verd: dict = {}
        _day_entry_cost = 0.0
        _day_selected: list = []
        sizing_eq = compound_equity(equity, equity0, compound)
        day_risk = risk_budget_yuan(sizing_eq, risk_pct, l1_mult)
        slots_left = max(0, int(max_positions) - len(pos))
        if _pool is not None:
            _pool.begin_day(d, equity)  # equity at the previous close (= last day of the previous month on a month's first day)
        if slots_left > 0:
            for code, s in series.items():
                if code in pos:
                    continue
                i = idx[code].get(d)
                if i is None or i < WARMUP:
                    continue
                hist = s["hist"]
                def _peer_r20(code=code, s=s):
                    bucket_ = s["meta"].get("bucket")
                    out_ = []
                    for other, other_s in series.items():
                        if other == code or other_s["meta"].get("bucket") != bucket_:
                            continue
                        oi = idx[other].get(d)
                        if oi is None:
                            continue
                        out_.append(_ret(other, other_s["hist"], oi, 20))
                    return [p for p in out_ if p is not None]

                # R5a: candidate construction is shared with daily_update (signal_core).
                _res = path_a_candidate(
                    code,
                    hist,
                    i,
                    adj=adj.get(code),
                    meta=s["meta"],
                    params={
                        "mode": mode,
                        "min_r20": min_r20,
                        "min_r60": min_r60,
                        "stop_atr_mult": stop_atr_mult,
                        "reward_rr": reward_rr,
                        "day_risk": day_risk,
                        "min_lots": min_lots,
                        "bypass": bypass,
                        "vbypass": vbypass,
                    },
                    ctx={
                        "day": d,
                        "curves": curves,
                        "member": member,
                        "min_seat_days": min_seat_days,
                        "seat_days_upto": _seat_days_upto,
                        "peer_r20_fn": _peer_r20,
                    },
                    composite_trend_fn=composite_trend,
                    entry_block_fn=entry_block,
                    seat_decision_fn=seat_decision,
                    carry_decision_fn=carry_bypass_decision,
                    vol_block_fn=vol_entry_block,
                )
                _st = _res["status"]
                if candidate_log is not None:
                    _verd[code] = {
                        k_: _res.get(k_)
                        for k_ in ("status", "r20", "r60", "atr", "direction", "aligned", "gate_ok", "blocked", "block_kind", "seat_label", "seat_short", "vol_reason", "lots")
                    }
                    _verd[code]["carry"] = None if _res["carry"] is None else _res["carry"]["label"]
                    _verd[code]["stop_dist"] = None if _res["sizing"] is None else _res["sizing"]["stop_dist"]
                    _verd[code]["target_dist"] = None if _res["sizing"] is None else _res["sizing"]["target_dist"]
                if _st in ("no_atr", "no_ret", "no_signal"):
                    continue
                signal_candidates_n += 1
                if _res["seat_short"]:
                    seat_short[code] = seat_short.get(code, 0) + 1
                if _res["seat_label"] is not None:
                    seat_follows[_res["seat_label"]] = seat_follows.get(_res["seat_label"], 0) + 1
                _cy = _res["carry"]
                if _cy is not None and not _cy["reason"] and _cy["mult"] < 1.0:
                    bypass_counts[_cy["label"]] = bypass_counts.get(_cy["label"], 0) + 1
                if _st == "blocked":
                    _why = _res["blocked"]
                    if _res["block_kind"] == "carry":
                        bypass_counts[_why] = bypass_counts.get(_why, 0) + 1
                    elif _res["block_kind"] == "vol":
                        vol_bypass_counts[_why] = vol_bypass_counts.get(_why, 0) + 1
                    block_counts[_why] = block_counts.get(_why, 0) + 1
                    continue
                if _st != "ok":
                    continue
                if entry_filters_on:
                    # R8b: judged on T's close only (sizing equity, T's bar, ATR windows ending at T); T+1 fill.
                    _cd, _sz = _res["candidate"], _res["sizing"]
                    ef_hits["evaluated"] += 1
                    _why = None
                    _a14 = _res.get("atr")
                    _a100 = _ef.long_atr(adj.get(code), hist, i) if filter_atr_spike else None
                    if filter_unit_risk_budget and _ef.unit_risk_exceeds(_sz["risk_per_lot"], day_risk):
                        _why = "unit_risk"
                    elif filter_unit_risk and _ef.unit_notional_exceeds(
                        _cd["close"], _cd["mult"], sizing_eq, max_gross_pct
                    ):
                        _why = "unit_notional"
                    if _why is None and filter_atr_spike:
                        _sp = _ef.atr_spike(_a14, _a100)
                        if _sp is None:
                            ef_hits["atr_spike_unavailable"] += 1
                        elif _sp:
                            _why = "atr_spike"
                    if _why is not None:
                        ef_hits[_why] += 1
                        ef_log.append(
                            {
                                "date": d,
                                "code": code,
                                "reason": _why,
                                "close": _cd["close"],
                                "mult": _cd["mult"],
                                "sizing_eq": sizing_eq,
                                "unit_notional": _ef.unit_notional(_cd["close"], _cd["mult"]),
                                "gross_cap_amount": _ef.gross_cap_amount(sizing_eq, max_gross_pct),
                                "risk_per_lot": _sz["risk_per_lot"],
                                "day_risk": day_risk,
                                "atr14": _a14,
                                "atr100": _a100,
                            }
                        )
                        continue
                if _pool is not None and not _pool.allows(code, d):
                    pool_blocked[code] = pool_blocked.get(code, 0) + 1
                    continue
                cands.append(_res["candidate"])
            # R4: usage of the open book on d's close (adjusted ATR; held contract's real close)
            used_g, used_r, held_buckets = _book_usage(
                pos, idx, series, d, atr_fn=_atr, close_fn=_held_close
            )
            eq_ = sizing_eq if sizing_eq > 0 else 1.0
            _caps_kw = dict(
                equity=sizing_eq,
                max_positions=slots_left,
                max_per_bucket=max_per_bucket,
                min_r20_pct=0.0 if mode == "ctf" else min_r20,
                min_r60_pct=0.0 if mode == "ctf" else min_r60,
                min_lots=min_lots,
            )
            if use_book_caps:
                gross_left_main = max(0.0, float(max_gross_pct) - used_g / eq_ * 100.0)
                risk_left_main = max(0.0, float(max_port_risk) - used_r / eq_ * 100.0)
                selected, _meta = apply_portfolio_caps(
                    cands,
                    max_gross_exposure_pct=gross_left_main,
                    max_portfolio_risk_pct=risk_left_main,
                    existing_buckets=held_buckets,
                    topup=True,
                    **_caps_kw,
                )
                caps_topup_lots += int(_meta.get("topup_lots", 0) or 0)
                caps_topup_revived += int(_meta.get("topup_revived", 0) or 0)
                # counterfactual with the full caps (no book): how many candidates the book scaled/dropped
                if cands and used_g + used_r > 0:
                    _sel_old, _ = apply_portfolio_caps(
                        cands,
                        max_gross_exposure_pct=max_gross_pct,
                        max_portfolio_risk_pct=max_port_risk,
                        existing_buckets=held_buckets,
                        topup=True,
                        **_caps_kw,
                    )
                    _new_lots = {c_["code"]: int(c_["lots"]) for c_ in selected}
                    for c_ in _sel_old:
                        if _new_lots.get(c_["code"], 0) < int(c_["lots"]):
                            caps_scaled_n += 1
            else:
                selected, _meta = apply_portfolio_caps(
                    cands,
                    max_gross_exposure_pct=max_gross_pct,
                    max_portfolio_risk_pct=max_port_risk,
                    topup=False,  # caps_include_book=False reproduces the pre-R4 caps exactly
                    **_caps_kw,
                )
            if candidate_log is not None:
                candidate_log.append(
                    {
                        "date": d,
                        "sizing_eq": sizing_eq,
                        "day_risk": day_risk,
                        "slots_left": slots_left,
                        "verdicts": _verd,
                        "cands": [dict(c_) for c_ in cands],
                        "held": {
                            k_: {
                                "lots": p_.get("lots"), "direction": p_.get("direction"), "bucket": p_.get("bucket"),
                                "entry": p_.get("entry"), "atr": p_.get("atr"),
                                "fill_price_basis": p_.get("fill_price_basis"), "fill_contract": p_.get("fill_contract"),
                            }
                            for k_, p_ in pos.items()
                        },
                        "selected": [(c_["code"], int(c_["lots"])) for c_ in selected],
                        "selected_full": [dict(c_) for c_ in selected],
                    }
                )
            # order-time check on d's close: open book + new orders within the caps
            _new_g = sum(
                int(c_["lots"]) * float(c_["close"]) * float(c_["mult"]) for c_ in selected
            )
            _new_r = sum(
                int(c_["lots"]) * float(c_.get("atr") or 0.0) * float(c_["mult"]) for c_ in selected
            )
            _sel_usage = {
                c_["code"]: (
                    int(c_["lots"]) * float(c_["close"]) * float(c_["mult"]),
                    int(c_["lots"]) * float(c_.get("atr") or 0.0) * float(c_["mult"]),
                )
                for c_ in selected
            }
            _ent_g = _ent_r = 0.0
            _ent_codes: list[str] = []
            if selected and use_book_caps:
                assert (used_g + _new_g) / eq_ * 100.0 <= float(max_gross_pct) + 1e-6, (
                    f"R4 order-time gross {(used_g + _new_g) / eq_ * 100.0:.2f}% > {max_gross_pct}% on {d}"
                )
                assert (used_r + _new_r) / eq_ * 100.0 <= float(max_port_risk) + 1e-6, (
                    f"R4 order-time ATR risk {(used_r + _new_r) / eq_ * 100.0:.2f}% > {max_port_risk}% on {d}"
                )
            _acc = {"price_pnl": price_pnl, "day_cost": day_cost}
            _entered, open_buckets = eng.fill_selected(selected, pos, d, acc=_acc)
            price_pnl, day_cost = _acc["price_pnl"], _acc["day_cost"]
            _day_entry_cost = eng.last_fill_cost
            _day_selected = [dict(c_) for c_ in selected]
            for _code_e in _entered:
                _g_, _r_ = _sel_usage.get(_code_e, (0.0, 0.0))
                _ent_g += _g_
                _ent_r += _r_
                _ent_codes.append(_code_e)
            if _ent_codes:
                _tot_g = (used_g + _ent_g) / eq_ * 100.0
                _tot_r = (used_r + _ent_r) / eq_ * 100.0
                caps_entry_days += 1
                caps_entry_gross_max = max(caps_entry_gross_max, _tot_g)
                caps_entry_risk_max = max(caps_entry_risk_max, _tot_r)
                caps_entry_log.append(
                    {
                        "date": d,
                        "new": _ent_codes,
                        "held_before": sorted(set(pos) - set(_ent_codes)),
                        "gross_pct": round(_tot_g, 2),
                        "risk_pct": round(_tot_r, 2),
                    }
                )

            # Idle slots earn short-end roll: long backwardation, short contango.
            if mode == "roll" and len(pos) < int(max_positions):
                roll_cands = []
                for code, s in series.items():
                    if code in pos:
                        continue
                    i = idx[code].get(d)
                    if i is None or i < WARMUP:
                        continue
                    pair = ((curves.get(code) or {}).get("carry") or {}).get(d)
                    gap = carry_gap_pct(pair)
                    if gap is None or abs(gap) < 0.5:
                        continue
                    hist = s["hist"]
                    a = _atr(code, hist, i)
                    if a is None or a <= 0:
                        continue
                    direction = "空" if gap > 0 else "多"
                    close = hist[i]["close"]
                    stop_dist = stop_atr_mult * a
                    if direction == "多":
                        stop = close - stop_dist
                        target = close + reward_rr * stop_dist
                    else:
                        stop = close + stop_dist
                        target = close - reward_rr * stop_dist
                    risk_per_lot = stop_dist * s["meta"]["mult"]
                    lots = int(math.floor(day_risk / risk_per_lot)) if risk_per_lot > 0 else 0
                    if lots <= 0:
                        continue
                    score = abs(gap)
                    roll_cands.append(
                        {
                            "code": code,
                            "direction": direction,
                            "lots": lots,
                            "close": close,
                            "mult": s["meta"]["mult"],
                            "r20": score,
                            "r60": score,
                            "atr": round(a, 2),
                            "bucket": s["meta"].get("bucket"),
                            "entry": close,
                            "stop": stop,
                            "target": target,
                            "reason": "roll_carry",
                        }
                    )
                used_gross, used_risk, _held_b = _book_usage(
                    pos, idx, series, d, atr_fn=_atr, close_fn=_held_close if use_book_caps else None
                )
                eq_base = sizing_eq if sizing_eq > 0 else 1.0
                gross_left = max(0.0, float(max_gross_pct) - used_gross / eq_base * 100.0)
                risk_left = max(0.0, float(max_port_risk) - used_risk / eq_base * 100.0)
                if max_per_bucket > 0:
                    roll_cands = [
                        c
                        for c in roll_cands
                        if open_buckets.get(str(c.get("bucket") or "_"), 0) < int(max_per_bucket)
                    ]
                roll_selected = []
                if roll_cands and gross_left > 0 and risk_left > 0:
                    roll_selected, _roll_meta = apply_portfolio_caps(
                        roll_cands,
                        equity=sizing_eq,
                        max_positions=max(0, int(max_positions) - len(pos)),
                        max_gross_exposure_pct=gross_left,
                        max_portfolio_risk_pct=risk_left,
                        max_per_bucket=max_per_bucket,
                        min_r20_pct=0.0,
                        min_r60_pct=0.0,
                        topup=use_book_caps,
                    )
                    caps_topup_lots += int(_roll_meta.get("topup_lots", 0) or 0)
                    caps_topup_revived += int(_roll_meta.get("topup_revived", 0) or 0)
                for c in roll_selected:
                    if int(c.get("lots") or 0) <= 0 or len(pos) >= int(max_positions):
                        continue
                    bucket = str(c.get("bucket") or "_")
                    if max_per_bucket > 0 and open_buckets.get(bucket, 0) >= int(max_per_bucket):
                        continue
                    sig_i = idx[c["code"]][d]
                    hist_c = series[c["code"]]["hist"]
                    if fill_price == "next_open":
                        c = next_open_fill(c, hist_c, sig_i)
                        if c is None:
                            quality_blocks["missing_next_open"] = quality_blocks.get("missing_next_open", 0) + 1
                            continue
                        fill_bar = hist_c[sig_i + 1]
                    else:
                        fill_bar = hist_c[sig_i]
                    if _delivery_window_block(c, fill_bar):
                        block_counts["delivery_window"] = block_counts.get("delivery_window", 0) + 1
                        continue
                    if enforce_tradability:
                        ok_q, qrec = entry_fill_allowed(
                            c["code"],
                            fill_bar,
                            series[c["code"]]["meta"],
                            side=c["direction"],
                            atr=c.get("atr"),
                            asof=str(fill_bar.get("date") or d),
                        )
                        if not ok_q:
                            key = f"quality:{qrec.get('status') or 'BLOCK'}"
                            quality_blocks[key] = quality_blocks.get(key, 0) + 1
                            block_counts[key] = block_counts.get(key, 0) + 1
                            continue
                    pos[c["code"]] = {
                        "code": c["code"],
                        "direction": c["direction"],
                        "lots": int(c["lots"]),
                        "entry": float(c["entry"]),
                        "entry_date": c.get("entry_date") or d,
                        "stop": float(c["stop"]),
                        "target": float(c["target"]),
                        "atr": c.get("atr"),
                        "r20": c.get("r20"),
                        "r60": c.get("r60"),
                        "bucket": c.get("bucket"),
                        "reason": "roll_carry",
                    }
                    if c.get("mark_from") is not None:
                        pos[c["code"]]["mark_from"] = c["mark_from"]
                    day_cost += fill_cost(
                        series[c["code"]]["meta"],
                        c["entry"],
                        c["lots"],
                        slippage_ticks=slippage_ticks,
                        fee_mult=fee_mult,
                    )
                    open_buckets[bucket] = open_buckets.get(bucket, 0) + 1

        pnl = price_pnl - day_cost
        cost_total += day_cost
        equity += pnl
        if state_log is not None:
            import copy as _copy

            state_log.append(
                {
                    "date": d,
                    "equity": equity,
                    "pos": _copy.deepcopy(pos),
                    "entry_cost": _day_entry_cost,
                    "selected": _day_selected,
                }
            )
        gross_equity += price_pnl
        day_pnls.append({"date": d, "pnl": round(pnl, 2), "equity": round(equity, 2)})
        peak = max(peak, equity)
        gross_peak = max(gross_peak, gross_equity)
        dd = (peak - equity) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)
        gdd = (gross_peak - gross_equity) / gross_peak * 100 if gross_peak else 0
        gross_max_dd = max(gross_max_dd, gdd)

        gross = 0.0
        for c, p in pos.items():
            ii = idx[c].get(d)
            if ii is None:
                continue
            gross += abs(p["lots"]) * series[c]["hist"][ii]["close"] * series[c]["meta"]["mult"]
        curve.append(
            {
                "date": d,
                "equity": round(equity, 2),
                "held": len(pos),
                "pnl": round(pnl, 2),
                "dd_pct": round(dd, 3),
                "gross_pct": round(gross / equity * 100, 2) if equity else 0,
                "codes": sorted(pos.keys()),
            }
        )

    minute_exit_n = eng.stats["minute_exit_n"]
    minute_rejected_mismatch = eng.stats["minute_rejected_mismatch"]
    minute_manage_checks = eng.stats["minute_manage_checks"]
    daily_exit_fallback_n = eng.stats["daily_exit_fallback_n"]
    roll_shifted_n = eng.stats["roll_shifted_n"]
    roll_unpriced_cont_n = eng.stats["roll_unpriced_cont_n"]
    roll_unpriced_n = eng.stats["roll_unpriced_n"]
    held_missing_n = eng.stats["held_missing_n"]
    roll_held_bar_days_n = eng.stats["roll_held_bar_days_n"]
    roll_open_gap_stops_n = eng.stats["roll_open_gap_stops_n"]
    premium_total += eng.premium_total
    hedge_payoff_total += eng.hedge_payoff_total
    wins_day = sum(1 for x in day_pnls if x["pnl"] > 0)
    n = len(day_pnls)
    ret_pct = (equity / equity0 - 1) * 100
    gross_ret_pct = (gross_equity / equity0 - 1) * 100
    avg_held = (sum(c["held"] for c in curve) / len(curve)) if curve else 0
    closed_n = len(closed_pnls)
    win_rs = [float(t["R"]) for t in closed_pnls if float(t.get("R") or 0) > 0]
    loss_rs = [float(t["R"]) for t in closed_pnls if float(t.get("R") or 0) <= 0]
    trade_wins = len(win_rs)
    trade_wr = (trade_wins / closed_n * 100) if closed_n else None
    avg_win_r = (sum(win_rs) / len(win_rs)) if win_rs else None
    avg_loss_r = (sum(loss_rs) / len(loss_rs)) if loss_rs else None
    realized_rr = (
        avg_win_r / abs(avg_loss_r) if avg_win_r is not None and avg_loss_r not in (None, 0) else None
    )
    expectancy_r = (sum(float(t["R"]) for t in closed_pnls) / closed_n) if closed_n else None
    breakeven_wr = 100.0 / (1.0 + reward_rr) if reward_rr > 0 else None
    proxy_entries = sum(
        1
        for t in closed_pnls
        if str(t.get("fill_price_basis") or "") == "continuous_proxy"
    )
    contract_entries = sum(
        1 for t in closed_pnls if str(t.get("fill_price_basis") or "") == "contract"
    )
    same_day_exit_n = sum(
        1
        for t in closed_pnls
        if str(t.get("entry_date") or "")[:10] == str(t.get("date") or "")[:10]
    )
    proxy_entry_share = (proxy_entries / closed_n) if closed_n else None
    contract_entry_share = (contract_entries / closed_n) if closed_n else None
    if max_dd >= 20:
        conclusion = "暂停"
    elif max_dd >= 12 or ret_pct <= -5:
        conclusion = "减仓观察"
    else:
        conclusion = "继续L1"
    # Credibility warning — does not change strategy params.
    if proxy_entry_share is not None and proxy_entry_share >= 0.5:
        conclusion = f"{conclusion}·proxy偏高"
    if same_day_exit_n and closed_n and same_day_exit_n / closed_n >= 0.4:
        conclusion = f"{conclusion}·当日进出偏多"

    pool = ",".join(u["code"] for u in symbols)
    hedge_net = hedge_payoff_total - premium_total
    try:
        from research.data_quality import config_version_stamp

        cfg_stamp = config_version_stamp(ROOT)
    except Exception:  # noqa: BLE001
        cfg_stamp = {
            "git_commit": (_git_sha(ROOT) or "")[:7] or None,
            "execution_rules_sha256": _file_sha256(ROOT / "execution_rules.json"),
            "universe_sha256": _file_sha256(ROOT / "universe.json"),
            "research_cost_sha256": _file_sha256(ROOT / "research_cost.json"),
        }
    n_trials_breakdown = n_trials_census(ROOT)
    n_trials_assumed = n_trials_breakdown["n_trials"]
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "batch": BATCH_LABEL,
        "strategy": "path_a_atr_rr1_5_opt_hedge" if option_hedge else "path_a_atr_rr1_5",
        "mode": mode,
        "cost_scenario": cost_scenario,
        "fee_mult": fee_mult,
        "enforce_tradability": bool(enforce_tradability),
        "fill_series": (contract_pack_report or {}).get("fill_series") or "continuous_proxy",
        "contract_pack": contract_pack_report,
        "config_version": cfg_stamp,
        "quality_blocks": quality_blocks,
        "n_trials_assumed": n_trials_assumed,
        "n_trials_breakdown": n_trials_breakdown,
        "data_source": "sina primary, TqSdk then iFinD fallback",
        "curve_coverage": curve_coverage(curves),
        "sources": sources,
        "reward_rr": reward_rr,
        "stop_atr_mult": stop_atr_mult,
        "equity_compound": compound,
        "max_positions": max_positions,
        "max_gross_exposure_pct": max_gross_pct,
        "max_portfolio_risk_pct": max_port_risk,
        "max_per_bucket": max_per_bucket,
        "min_r20_pct": min_r20,
        "min_r60_pct": min_r60,
        "min_lots": min_lots,
        # present only when an R8b research filter was switched on (formal output keeps its exact key set)
        **(
            {
                "entry_filters": {
                    "filter_unit_risk": bool(filter_unit_risk),
                    "filter_atr_spike": bool(filter_atr_spike),
                    "filter_unit_risk_budget": bool(filter_unit_risk_budget),
                    "unit_notional_frac": _ef.UNIT_NOTIONAL_FRAC,
                    "atr_spike_ratio": _ef.ATR_SPIKE_RATIO,
                    "atr_long_n": _ef.ATR_LONG_N,
                    "hits": dict(ef_hits),
                    "log": ef_log,
                }
            }
            if entry_filters_on
            else {}
        ),
        **(
            {
                "long_sample": {
                    "main_map_override": _ls.get("main_map") is not None,
                    "skip_contract_overlay": bool(_ls.get("skip_contract_overlay")),
                    "no_minute": bool(_ls.get("no_minute")),
                    "pool_blocked_signals": dict(pool_blocked),
                    "pool": (_pool.report() if _pool is not None and hasattr(_pool, "report") else None),
                }
            }
            if _ls
            else {}
        ),
        "option_hedge": option_hedge,
        "premium_atr_mult": premium_atr_mult if option_hedge else None,
        "strike_atr_mult": strike_atr_mult if option_hedge else None,
        "premium_yuan": round(premium_total, 2),
        "hedge_payoff_yuan": round(hedge_payoff_total, 2),
        "hedge_net_yuan": round(hedge_net, 2),
        "ifind_slot": active_slot(),
        "universe_n": len(symbols),
        "universe": pool,
        "start": trade_dates[0],
        "end": trade_dates[-1],
        "trade_days": n,
        "equity_start": equity0,
        "equity_end": round(equity, 2),
        "gross_equity_end": round(gross_equity, 2),
        "ret_pct": round(ret_pct, 3),
        "gross_ret_pct": round(gross_ret_pct, 3),
        "cost_yuan": round(cost_total, 2),
        "max_dd_pct": round(max_dd, 3),
        "gross_max_dd_pct": round(gross_max_dd, 3),
        "blocks": block_counts,
        "carry_bypass": bypass,
        "availability_lag": int(availability_lag),
        "fill_price": fill_price,
        "exit_check": "minute_15",
        "exit_minute_period": EXIT_MINUTE_PERIOD,
        "minute_stop_exits": minute_exit_n,
        "minute_rejected_mismatch": minute_rejected_mismatch,
        "minute_manage_checks": minute_manage_checks,
        "daily_exit_fallback_checks": daily_exit_fallback_n,
        "roll_shifted": roll_shifted_n,
        "roll_unpriced_cont": roll_unpriced_cont_n,
        "roll_unpriced": roll_unpriced_n,
        "held_contract_missing": held_missing_n,
        "roll_held_bar_days": roll_held_bar_days_n,
        "roll_open_gap_stops": roll_open_gap_stops_n,
        "caps_include_book": use_book_caps,
        "caps_entry_days": caps_entry_days,
        "caps_entry_gross_max": round(caps_entry_gross_max, 2),
        "caps_entry_risk_max": round(caps_entry_risk_max, 2),
        "caps_scaled_n": caps_scaled_n,
        "caps_topup_lots": caps_topup_lots,
        "caps_topup_revived": caps_topup_revived,
        "caps_drift_days_gt55": sum(1 for c_ in curve if float(c_.get("gross_pct") or 0) > 55.0),
        "caps_entry_log": caps_entry_log,
        "adjusted_signals": bool(adj),
        "signal_candidates": signal_candidates_n,
        "adj_fallback_days": sum(a_.fallback_days() for a_ in adj.values()) if adj else None,
        "adj_fallback_days_in_window": (
            sum(a_.fallback_days(since=trade_dates[0]) for a_ in adj.values()) if adj else None
        ),
        "adj_roll_days": (
            {c_: a_.roll_days() for c_, a_ in sorted(adj.items()) if a_.roll_days()} if adj else None
        ),
        "adj_roll_days_in_window": (
            {
                c_: a_.roll_days(since=trade_dates[0])
                for c_, a_ in sorted(adj.items())
                if a_.roll_days(since=trade_dates[0])
            }
            if adj
            else None
        ),
        "main_map_full_history": None
        if main_map is None
        else {
            "days_total": sum(len(m_) for m_ in main_map.maps.values()),
            "none_days_total": sum(1 for m_ in main_map.maps.values() for v_ in m_.values() if v_ is None),
            "coverage": {
                c_: {
                    "days": len(m_),
                    "none_days": sum(1 for v_ in m_.values() if v_ is None),
                    "coverage": round(sum(1 for v_ in m_.values() if v_ is not None) / len(m_), 4)
                    if m_
                    else None,
                }
                for c_, m_ in sorted(main_map.maps.items())
            },
        },
        "main_map": None
        if main_map is None
        else {
            "none_days_total": sum(s["none_days"] for s in main_map.stats.values()),
            "days_total": sum(s["days"] for s in main_map.stats.values()),
            "coverage": {
                c: {k: s[k] for k in ("days", "matched", "none_days", "coverage")}
                for c, s in sorted(main_map.stats.items())
            },
        },
        "slippage_ticks": slippage_ticks,
        "git_sha": _git_sha(ROOT),
        "universe_sha256": cfg_stamp.get("universe_sha256") or _file_sha256(ROOT / "universe.json"),
        "execution_rules_sha256": cfg_stamp.get("execution_rules_sha256")
        or _file_sha256(ROOT / "execution_rules.json"),
        "research_cost_sha256": cfg_stamp.get("research_cost_sha256")
        or _file_sha256(ROOT / "research_cost.json"),
        "carry_bypass_counts": bypass_counts,
        "vol_bypass": vbypass,
        "vol_bypass_counts": vol_bypass_counts,
        "seat_follows": seat_follows,
        "win_rate": round(wins_day / n * 100, 2) if n else None,
        "trade_win_rate": round(trade_wr, 2) if trade_wr is not None else None,
        "avg_win_r": round(avg_win_r, 3) if avg_win_r is not None else None,
        "avg_loss_r": round(avg_loss_r, 3) if avg_loss_r is not None else None,
        "realized_rr": round(realized_rr, 3) if realized_rr is not None else None,
        "expectancy_r": round(expectancy_r, 3) if expectancy_r is not None else None,
        "breakeven_win_rate": round(breakeven_wr, 2) if breakeven_wr is not None else None,
        "closed_trades": closed_n,
        "proxy_entry_n": proxy_entries,
        "contract_entry_n": contract_entries,
        "proxy_entry_share": round(proxy_entry_share, 4) if proxy_entry_share is not None else None,
        "contract_entry_share": round(contract_entry_share, 4)
        if contract_entry_share is not None
        else None,
        "same_day_exit_n": same_day_exit_n,
        "same_day_exit_share": round(same_day_exit_n / closed_n, 4) if closed_n else None,
        "exits": trade_exits,
        "seat_gate": {"min_seat_days": min_seat_days, "seat_days": seat_cov, "skipped_seat_filter_signals": seat_short, "rule": "as_of_T_post_lag"},
        "delivery_entry_block": {"buffer_sessions": entry_delivery_buffer, "blocked": delivery_entry_blocks},
        "freeze_fix": {"enabled": bool(freeze_fix), "max_stale_days": max_stale_days, "delivery_guard": bool(delivery_guard), **freeze_stats},
        "sleeve_counts": sleeve_counts,
        "avg_held": round(avg_held, 2),
        "conclusion": conclusion,
        "errors": errors,
        "bars": {k: len(v["hist"]) for k, v in series.items()},
        "final_positions": pos,
        "equity_curve": curve,
        "equity_curve_weekly": _downsample_weekly(curve),
        "day_pnls_tail": day_pnls[-20:],
        "closed_pnls_tail": closed_pnls[-100:],
        "closed_pnls": closed_pnls,
        "entry_exit_rules": {
            "open": (
                "r20/r60同向且|r20|≥min_r20、|r60|≥min_r60（ctf模式改用composite_trend）；"
                "经entry_filter/席位等过滤；升贴水极端旁路（carry_bypass）可禁开或减仓；"
                "再经组合帽（TopN、名义暴露、组合风险、板块上限）；"
                "开仓前 classify_bar：status!=PASS 禁止新开（涨跌停/无量/缺下一开盘等）；"
                "止损=stop_atr_mult×ATR，止盈=reward_rr×止损距；"
                f"正式成交={fill_price}（next_open=T日信号、T+1开盘入场并平移止损止盈）；"
                f"成本情景={cost_scenario}（滑点={slippage_ticks}跳，fee_mult={fee_mult}）。"
            ),
            "close": (
                "持仓期优先用当日15分钟线按时间顺序触及止盈/止损即平"
                "（单根15m内仍先止损后止盈）；无分钟缓存则回退日线OHLC；"
                "未触及则趋势不再同向或composite_trend翻号以signal在收盘价平仓。"
            ),
            "exit_codes": {
                "target": "盘中触及止盈",
                "stop": "盘中触及止损",
                "signal": "趋势/信号失效平仓",
            },
            "params": {
                "reward_rr": reward_rr,
                "stop_atr_mult": stop_atr_mult,
                "min_r20": min_r20,
                "min_r60": min_r60,
                "max_positions": max_positions,
                "mode": mode,
                "exit_check": "minute_15",
                "fill_price": fill_price,
            },
        },

        "ifind_calls": usage_report()["count"],
        "summary": (
            f"PathA{'+OptHedge' if option_hedge else ''} {mode} {trade_dates[0]}→{trade_dates[-1]} "
            f"净权益 {equity:.0f}（{ret_pct:+.2f}%）毛权益 {gross_equity:.0f}（{gross_ret_pct:+.2f}%）"
            f"成本 {cost_total:.0f}"
            + (
                f"/权利金 {premium_total:.0f}/对冲赔付 {hedge_payoff_total:.0f}/对冲净 {hedge_net:.0f}"
                if option_hedge
                else ""
            )
            + f"，净MaxDD {max_dd:.2f}% 毛MaxDD {gross_max_dd:.2f}%，"
            f"成交{closed_n}笔，结论 {conclusion}"
        ),
    }


def _simulate_cfg(
    p,
    mode,
    *,
    pack=None,
    premium_atr_mult=None,
    strike_atr_mult=None,
    option_hedge=None,
    reward_rr=None,
    stop_atr_mult=None,
    freeze_fix=None,
    max_stale_days=None,
    delivery_guard=None,
    min_seat_days=None,
    entry_delivery_buffer=None,
    entry_delivery_action=None,
    adjusted_signals=None,
    caps_include_book=None,
    candidate_log=None,
    contract_root=None,
    state_log=None,
    long_sample=None,
):
    cfg = p["cfg"]
    print(f"[bt] mode={mode} ifind_so_far={usage_report()['count']}")
    return simulate(
        cfg["symbols"],
        p["equity0"],
        compound=p["compound"],
        risk_pct=p["risk_pct"],
        l1_mult=p["l1_mult"],
        max_positions=p["max_positions"],
        max_gross_pct=p["max_gross_pct"],
        max_port_risk=p["max_port_risk"],
        max_per_bucket=p["max_per_bucket"],
        min_r20=p["min_r20"],
        min_r60=p["min_r60"],
        min_lots=p.get("min_lots") or 0,
        option_hedge=bool(p.get("option_hedge") if option_hedge is None else option_hedge),
        premium_atr_mult=float(p.get("premium_atr_mult") if premium_atr_mult is None else premium_atr_mult),
        strike_atr_mult=float(p.get("strike_atr_mult") if strike_atr_mult is None else strike_atr_mult),
        reward_rr=float(p["reward_rr"] if reward_rr is None else reward_rr),
        stop_atr_mult=float(p["stop_atr_mult"] if stop_atr_mult is None else stop_atr_mult),
        mode=mode,
        pack=pack,
        carry_bypass=p.get("carry_bypass"),
        vol_bypass=p.get("vol_bypass"),
        availability_lag=int(p.get("availability_lag", DEFAULT_AVAILABILITY_LAG)),
        fill_price=str(p.get("fill_price") or DEFAULT_FILL_PRICE),
        slippage_ticks=p.get("slippage_ticks"),
        fee_mult=float(p.get("fee_mult") if p.get("fee_mult") is not None else 1.0),
        cost_scenario=str(p.get("cost_scenario") or "base"),
        enforce_tradability=bool(p.get("enforce_tradability", True)),
        freeze_fix=bool(p.get("freeze_fix", True) if freeze_fix is None else freeze_fix),
        max_stale_days=(p.get("max_stale_days", MAX_STALE_DAYS) if max_stale_days is None else max_stale_days),
        delivery_guard=bool(p.get("delivery_guard", True) if delivery_guard is None else delivery_guard),
        min_seat_days=(p.get("min_seat_days", MIN_SEAT_DAYS) if min_seat_days is None else min_seat_days),
        entry_delivery_buffer=(p.get("entry_delivery_buffer", ENTRY_DELIVERY_BUFFER) if entry_delivery_buffer is None else entry_delivery_buffer),
        entry_delivery_action=str(p.get("entry_delivery_action", ENTRY_DELIVERY_ACTION) if entry_delivery_action is None else entry_delivery_action),
        adjusted_signals=adjusted_signals,
        caps_include_book=caps_include_book,
        candidate_log=candidate_log,
        contract_root=contract_root,
        state_log=state_log,
        filter_unit_risk=bool(p.get("filter_unit_risk")),
        filter_atr_spike=bool(p.get("filter_atr_spike")),
        filter_unit_risk_budget=bool(p.get("filter_unit_risk_budget")),
        long_sample=long_sample,
    )


def _hedge_row(name: str, strike: float, premium: float, out: dict) -> dict:
    return {
        "name": name,
        "strike_atr_mult": strike,
        "premium_atr_mult": premium,
        "ok": out.get("ok"),
        "equity_start": out.get("equity_start"),
        "equity_end": out.get("equity_end"),
        "ret_pct": out.get("ret_pct"),
        "gross_ret_pct": out.get("gross_ret_pct"),
        "max_dd_pct": out.get("max_dd_pct"),
        "gross_max_dd_pct": out.get("gross_max_dd_pct"),
        "premium_yuan": out.get("premium_yuan"),
        "hedge_payoff_yuan": out.get("hedge_payoff_yuan"),
        "hedge_net_yuan": out.get("hedge_net_yuan"),
        "cost_yuan": out.get("cost_yuan"),
        "closed_trades": out.get("closed_trades"),
        "trade_win_rate": out.get("trade_win_rate"),
        "win_rate": out.get("win_rate"),
        "exits": out.get("exits"),
        "avg_held": out.get("avg_held"),
        "conclusion": out.get("conclusion"),
        "summary": out.get("summary"),
    }


def _row(out: dict) -> dict:
    return {
        "mode": out.get("mode"),
        "net_ret_pct": out.get("ret_pct"),
        "gross_ret_pct": out.get("gross_ret_pct"),
        "max_dd_pct": out.get("max_dd_pct"),
        "gross_max_dd_pct": out.get("gross_max_dd_pct"),
        "cost_yuan": out.get("cost_yuan"),
        "closed_trades": out.get("closed_trades"),
        "trade_win_rate": out.get("trade_win_rate"),
        "blocks": out.get("blocks"),
        "conclusion": out.get("conclusion"),
        "ok": out.get("ok"),
    }


def _choose(rows: list[dict]) -> str:
    """Turn on one P1 filter only when it beats the current 20/60 book on net return and max drawdown.

    The comparison book is `base`: same costs, 20/60 entry, no roll blackout and no P1 filter.
    A filter is adopted only when it beats that book. Otherwise the book stays on base.
    """
    base = next((r for r in rows if r.get("mode") == "base" and r.get("ok")), None)
    if not base:
        return "base"
    best = None
    for row in rows:
        if row.get("mode") not in ("carry", "oi", "member", "climax", "seats"):
            continue
        if not row.get("ok"):
            continue
        if row["net_ret_pct"] > base["net_ret_pct"] and row["max_dd_pct"] < base["max_dd_pct"]:
            if best is None or row["net_ret_pct"] > best["net_ret_pct"]:
                best = row
    return best["mode"] if best else "base"


def _write_entry_filter(mode: str, root: Path | None = None) -> Path:
    """Record the --compare pick as a recommendation; never rewrite universe.json."""
    root = root or ROOT
    d = root / "output"
    d.mkdir(exist_ok=True)
    path = d / "entry_filter_recommendation.json"
    path.write_text(
        json.dumps({"entry_filter": mode, "note": "recommendation only; universe.json unchanged"},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main():
    import sys

    compare = "--compare" in sys.argv
    hedge_grid = "--hedge-grid" in sys.argv
    rr_grid = "--rr-grid" in sys.argv
    ctf = "--ctf" in sys.argv
    roll_grid = "--roll-grid" in sys.argv
    p = _load_cfg()
    # R8: research overrides need --out and the default single-run path; they never reach the formal write.
    r8_rec: dict = {}
    if _r8_flags_present():
        if _cli_val("--out") is None:
            print("[bt] --equity / --filter-unit-risk / --filter-atr-spike are research overrides and require "
                  "--out PATH (refusing to run without it)", file=sys.stderr)
            return 2
        if compare or hedge_grid or rr_grid or ctf or roll_grid or p.get("observe_mode"):
            print("[bt] R8 overrides are only supported for the default single run "
                  "(not with --compare/--hedge-grid/--rr-grid/--ctf/--roll-grid/--observe)", file=sys.stderr)
            return 2
        try:
            r8_new = r8_overrides_from_argv()
        except ValueError as exc:
            print(f"[bt] bad R8 override: {exc}", file=sys.stderr)
            return 2
        r8_rec = {"applied": dict(r8_new),
                  "formal_values": {k: p.get(k) for k in r8_new}}
        p.update(r8_new)
    if rr_grid:
        p["equity0"] = float(p["cfg"].get("equity") or 200_000)
        p["min_lots"] = 0
        p["option_hedge"] = False
        p["observe_mode"] = False
    cfg = p["cfg"]
    print(
        f"[bt] pathA-rr{p['reward_rr']:.0f} equity0={p['equity0']} "
        f"stopATR={p['stop_atr_mult']} compound={p['compound']} n={len(cfg['symbols'])} "
        f"max_pos={p['max_positions']} gross≤{p['max_gross_pct']}% "
        f"atr_risk≤{p['max_port_risk']}% bucket≤{p['max_per_bucket']} "
        f"min_r={p['min_r20']}/{p['min_r60']} min_lots={p.get('min_lots')} "
        f"observe={p.get('observe_mode')} optHedge={p.get('option_hedge')} "
        f"premATR={p.get('premium_atr_mult')} strikeATR={p.get('strike_atr_mult')} "
        f"ifind={active_slot()} compare={compare} hedge_grid={hedge_grid} rr_grid={rr_grid} roll_grid={roll_grid}"
        + (
            f" filter_unit_risk={bool(p.get('filter_unit_risk'))} filter_atr_spike={bool(p.get('filter_atr_spike'))}"
            if (p.get("filter_unit_risk") or p.get("filter_atr_spike"))
            else ""
        )
    )
    if roll_grid:
        pack = _fetch_pack(p["cfg"]["symbols"])
        rows = []
        for equity in (100_000, 200_000, 500_000, 1_000_000):
            trial = dict(p)
            trial["equity0"] = float(equity)
            trial["min_lots"] = 0
            trial["option_hedge"] = False
            trial["observe_mode"] = False
            for mode in ("seats", "roll"):
                print(f"[bt] roll-grid equity={equity} mode={mode}")
                one = _simulate_cfg(trial, mode, pack=pack, option_hedge=False)
                rows.append(
                    {
                        "equity": equity,
                        "mode": mode,
                        "ret_pct": one.get("ret_pct"),
                        "max_dd_pct": one.get("max_dd_pct"),
                        "equity_end": one.get("equity_end"),
                        "closed_trades": one.get("closed_trades"),
                        "trade_win_rate": one.get("trade_win_rate"),
                        "expectancy_r": one.get("expectancy_r"),
                        "avg_held": one.get("avg_held"),
                        "sleeve_counts": one.get("sleeve_counts"),
                        "conclusion": one.get("conclusion"),
                    }
                )
                print(
                    f"  ret={one.get('ret_pct')} dd={one.get('max_dd_pct')} "
                    f"trades={one.get('closed_trades')} sleeves={one.get('sleeve_counts')} "
                    f"{one.get('conclusion')}"
                )
        out = {
            "ok": True,
            "strategy": "path_a_plus_roll",
            "roll_grid": rows,
            "summary": " ; ".join(
                f"{r['equity']/10000:.0f}万/{r['mode']} {r['ret_pct']}% dd {r['max_dd_pct']}%"
                for r in rows
            ),
        }
        (ROOT / "archive").mkdir(exist_ok=True)
        grid_path = ROOT / "archive" / "roll_equity_grid.json"
        grid_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(out["summary"])
        print(f"[bt] wrote {grid_path}")
        return 0
    elif rr_grid:
        mode = p["entry_filter"] if p["entry_filter"] in ("base", "p0", "carry", "oi", "member", "climax", "seats") else "base"
        pack = _fetch_pack(p["cfg"]["symbols"])
        rows = []
        saved = {}
        for stop in STOP_GRID:
            for rr in RR_GRID:
                name = f"stop{stop:g}_rr{rr:g}"
                print(f"[bt] rr-grid {name}")
                one = _simulate_cfg(
                    p,
                    mode,
                    pack=pack,
                    option_hedge=False,
                    reward_rr=rr,
                    stop_atr_mult=stop,
                )
                saved[name] = one
                rows.append(
                    {
                        "name": name,
                        "stop_atr_mult": stop,
                        "reward_rr": rr,
                        "ret_pct": one.get("ret_pct"),
                        "max_dd_pct": one.get("max_dd_pct"),
                        "trade_win_rate": one.get("trade_win_rate"),
                        "breakeven_win_rate": one.get("breakeven_win_rate"),
                        "avg_win_r": one.get("avg_win_r"),
                        "avg_loss_r": one.get("avg_loss_r"),
                        "realized_rr": one.get("realized_rr"),
                        "expectancy_r": one.get("expectancy_r"),
                        "closed_trades": one.get("closed_trades"),
                        "exits": one.get("exits"),
                        "equity_end": one.get("equity_end"),
                        "conclusion": one.get("conclusion"),
                        "calmar": round(one["ret_pct"] / one["max_dd_pct"], 3)
                        if one.get("ok") and one.get("max_dd_pct")
                        else None,
                    }
                )
                print(
                    f"  ret={one.get('ret_pct')} dd={one.get('max_dd_pct')} "
                    f"wr={one.get('trade_win_rate')} realized_rr={one.get('realized_rr')} "
                    f"E={one.get('expectancy_r')} {one.get('conclusion')}"
                )
        ranked = [r for r in rows if r.get("calmar") is not None]
        best = max(ranked, key=lambda r: (r["calmar"], r["ret_pct"])) if ranked else rows[0]
        out = saved[best["name"]]
        out["rr_grid"] = rows
        out["rr_grid_best"] = best["name"]
        out["entry_filter"] = mode
        out["summary"] = (
            f"盈亏比对照 best={best['name']} calmar={best.get('calmar')} "
            f"ret={best.get('ret_pct')} dd={best.get('max_dd_pct')} "
            f"realized_rr={best.get('realized_rr')}"
        )
        (ROOT / "archive").mkdir(exist_ok=True)
        (ROOT / "archive" / "rr_grid.json").write_text(
            json.dumps({"best": best, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif hedge_grid:
        mode = p["entry_filter"] if p["entry_filter"] in ("base", "p0", "carry", "oi", "member", "climax", "seats") else "base"
        pack = _fetch_pack(p["cfg"]["symbols"])
        rows = []
        saved = {}
        for name, strike, premium in HEDGE_GRID:
            hedged = strike is not None
            print(f"[bt] hedge-grid {name} strike={strike} premium={premium}")
            one = _simulate_cfg(
                p,
                mode,
                pack=pack,
                premium_atr_mult=0.0 if premium is None else premium,
                strike_atr_mult=0.0 if strike is None else strike,
                option_hedge=hedged,
            )
            saved[name] = one
            rows.append(_hedge_row(name, strike, premium, one))
            print(one.get("summary") or one.get("error"))
        viable = [r for r in rows if r.get("ok") and r.get("ret_pct") is not None]
        best_name = max(viable, key=lambda r: (r["ret_pct"], -r["max_dd_pct"]))["name"] if viable else HEDGE_GRID[0][0]
        out = saved[best_name]
        out["hedge_grid"] = rows
        out["hedge_grid_best"] = best_name
        out["entry_filter"] = mode
        out["summary"] = (
            f"对冲对照 best={best_name} | "
            + " ; ".join(
                f"{r['name']} ret={r.get('ret_pct')} dd={r.get('max_dd_pct')} hedge_net={r.get('hedge_net_yuan')}"
                for r in rows
            )
        )
    elif compare:
        saved = {}
        rows = []
        for mode in ("base", "p0", "carry", "oi", "member", "climax", "seats"):
            one = _simulate_cfg(p, mode)
            saved[mode] = one
            rows.append(_row(one))
            print(one.get("summary") or one.get("error"))
        chosen = _choose(rows)
        current = p["entry_filter"]
        # Keep a manually adopted seats book when the dual-metric pick is still base.
        if chosen == "base" and current == "seats":
            chosen = "seats"
            print("[bt] keep entry_filter=seats (adopted seat book)")
        else:
            _write_entry_filter(chosen)
        print(f"[bt] entry_filter={chosen}")
        out = saved[chosen]
        out["comparison"] = rows
        out["entry_filter"] = chosen
    else:
        prior_cmp = None
        try:
            prior_cmp = json.loads((ROOT / "historical_backtest_latest.json").read_text(encoding="utf-8")).get(
                "comparison"
            )
        except Exception:
            prior_cmp = None
        mode = "ctf" if ctf else (
            p["entry_filter"] if p["entry_filter"] in ("base", "p0", "carry", "oi", "member", "climax", "seats") else "base"
        )
        # R7a-D: fill the contract cache for every listing-calendar main_map candidate first.
        pack = _fetch_pack(cfg["symbols"])
        try:
            from research.data_quality.contract_cache import ensure_listed_contract_bars

            prefetch = ensure_listed_contract_bars(pack[0], ROOT)
        except Exception as exc:  # noqa: BLE001
            prefetch = {"error": str(exc)[:200]}
        print(
            f"[bt] contract prefetch requests={prefetch.get('requests')} seconds={prefetch.get('seconds')} "
            f"fetched={len(prefetch.get('fetched') or [])} failed={len(prefetch.get('failed') or [])}"
        )
        out = _simulate_cfg(p, mode, pack=pack)
        out["contract_prefetch"] = prefetch
        out["entry_filter"] = mode
        if r8_rec:
            out["r8_overrides"] = r8_rec  # research-only run: never a formal result
        if prior_cmp:
            out["comparison"] = prior_cmp
        try:
            pack_now = None
            if _LAST_PACK.get("series"):
                pack_now = (
                    _LAST_PACK["series"],
                    _LAST_PACK.get("errors") or {},
                    _LAST_PACK.get("sources") or {},
                )
            if "--no-cost-stress" not in sys.argv:
                attach_cost_scenario_contrast(out, p, mode, pack=pack_now, scenarios=("stress",))
        except Exception as exc:  # noqa: BLE001
            print(f"[bt] cost contrast soft-fail: {exc}")
    try:
        from lab.validation.report import validation_bundle_from_backtest

        out["validation"] = validation_bundle_from_backtest(out)
    except Exception as exc:  # noqa: BLE001
        print(f"[bt] validation soft-fail: {exc}")
    rep = usage_report()
    out["ifind_calls"] = rep["count"]
    out["ifind_call_log"] = rep["calls"]
    out["live_trading"] = False
    print(f"[ifind] calls={rep['count']}")
    try:
        from research_quality import validate_backtest_meta

        q = validate_backtest_meta(
            {
                "start": out.get("start"),
                "end": out.get("end"),
                "trade_days": out.get("trade_days"),
            }
        )
        out["quality"] = q
        out["quality_ok"] = bool(q.get("ok"))
        if not q.get("ok"):
            print(f"[bt] QUALITY GATE FAIL {q.get('failures')}")
            out["ok"] = False
            out["error"] = "quality_gate:" + ",".join(q.get("failures") or [])
            fail_path = ROOT / "historical_backtest_quality_failed.json"
            fail_path.write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            arch = ROOT / "archive"
            arch.mkdir(exist_ok=True)
            if out.get("end"):
                (arch / f"backtest_quality_failed_{str(out['end']).replace('-', '')}.json").write_text(
                    fail_path.read_text(encoding="utf-8"), encoding="utf-8"
                )
            print(f"[bt] formal historical_backtest_latest withheld; wrote {fail_path}")
            return out
    except Exception as exc:  # noqa: BLE001
        print(f"[bt] quality check soft-fail: {exc}")
    try:
        out["input_snapshot"] = write_input_snapshot(out, sys.argv[1:])
    except Exception as exc:  # noqa: BLE001
        print(f"[bt] input snapshot soft-fail: {exc}")
    # R0: --out PATH writes offline research artifact (no formal lock / no archive/backtest_*).
    out_cli = _cli_val("--out")
    formal_latest = (ROOT / "historical_backtest_latest.json").resolve()
    if out_cli is not None:
        path = Path(out_cli).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        else:
            path = path.resolve()
        if path == formal_latest:
            print(
                "[bt] --out must not target root historical_backtest_latest.json",
                file=sys.stderr,
            )
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        chart = path.parent / f"{path.stem}_equity.svg"
        title_prefix = "PathA-out"
    elif "--observe" in sys.argv or bool(out.get("option_hedge")):
        # Observe / option-hedge runs must not overwrite the formal Path-A artifact.
        art = ROOT / "_art_opt"
        art.mkdir(parents=True, exist_ok=True)
        path = art / "historical_backtest_latest.json"
        chart = art / "historical_equity_curve.svg"
        title_prefix = "PathA+OptHedge" if out.get("option_hedge") else "PathA-observe"
    else:
        path = ROOT / "historical_backtest_latest.json"
        chart = ROOT / "historical_equity_curve.svg"
        title_prefix = "PathA"
    if path.parent == ROOT and out_cli is None:
        # fix3-opt: formal write requires the rule lock + a clean working tree.
        from research.execution.rule_lock import RuleLockError, check_clean, check_fill_series, check_rules

        try:
            check_rules(ROOT, _load_cfg())
            check_fill_series(ROOT, out)
            check_clean(ROOT)
        except RuleLockError as exc:
            print(f"[bt] RULE LOCK FAILED — formal historical_backtest_latest not written: {exc}", file=sys.stderr)
            return 2
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    arch = ROOT / "archive"
    arch.mkdir(exist_ok=True)
    if out.get("end") and path.parent == ROOT and out_cli is None:
        (arch / f"backtest_{out['end'].replace('-', '')}.json").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    if out.get("ok") and out.get("equity_curve"):
        _write_equity_svg(
            out["equity_curve"],
            chart,
            f"{title_prefix} {out.get('start')}→{out.get('end')}",
        )
        print(f"[bt] chart {chart}")
    print(out.get("summary") or out.get("error"))
    print(f"[bt] wrote {path}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
