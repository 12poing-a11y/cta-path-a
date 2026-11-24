# -*- coding: utf-8 -*-
"""Shared Path-A position engine (R5b).

``historical_backtest.simulate`` (the backtest) and ``paper_book`` (the daily paper ledger) run
open positions and T+1 entries through the SAME code:

* ``PositionEngine.manage``: one open position on day ``d`` — R6b held-contract roll at the open,
  R6a contract / basis_off manage bar, 15m first touch (``minute_bars_match_daily`` +
  entry-alignment checks) with the daily-OHLC fallback, adjusted-signal exit, delivery / freeze
  exits, mark-to-market, exit cost and the closed-trade row;
* ``PositionEngine.fill_selected``: T-close selections filled at the T+1 open (``next_open_fill``),
  delivery-window proxy, tradability check, the position row (``held_contract``).

Money is accumulated into the caller's ``acc`` dict (``price_pnl`` / ``day_cost``) with exactly the
same sequence of additions the backtest always used, so the refactor is bit-identical.
Counters live in ``self.stats`` and in the dicts / lists the caller passes in.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

STAT_KEYS = (
    "minute_exit_n",
    "minute_rejected_mismatch",
    "minute_manage_checks",
    "daily_exit_fallback_n",
    "roll_shifted_n",
    "roll_unpriced_cont_n",
    "roll_unpriced_n",
    "held_missing_n",
    "roll_held_bar_days_n",
    "roll_open_gap_stops_n",
)


def _hb():
    import historical_backtest as hb

    return hb


class PositionEngine:
    def __init__(
        self,
        *,
        series: dict[str, dict[str, Any]],
        idx: dict[str, dict[str, int]] | None = None,
        main_map: Any = None,
        adj: dict | None = None,
        curves: dict | None = None,
        mode: str = "seats",
        contract_root: Path | None = None,
        minute_root: Path | None = None,
        freeze_fix: bool = True,
        delivery_guard: bool = True,
        max_stale_days: int | None = None,
        fill_price: str = "next_open",
        slippage_ticks: float = 0.0,
        fee_mult: float = 1.0,
        enforce_tradability: bool = True,
        entry_delivery_buffer: int | None = None,
        entry_delivery_action: str = "proxy",
        option_hedge: bool = False,
        premium_atr_mult: float = 2.0,
        strike_atr_mult: float = 1.0,
        max_positions: int = 3,
        max_per_bucket: int = 1,
        trade_exits: dict | None = None,
        freeze_stats: dict | None = None,
        sleeve_counts: dict | None = None,
        quality_blocks: dict | None = None,
        block_counts: dict | None = None,
        delivery_entry_blocks: dict | None = None,
        closed: list | None = None,
    ) -> None:
        hb = _hb()
        self.series = series
        self.idx = idx if idx is not None else {
            code: {h["date"]: i for i, h in enumerate(s["hist"])} for code, s in series.items()
        }
        self.main_map = main_map
        self.adj = adj if adj is not None else {}
        self.curves = curves or {}
        self.mode = mode
        self.croot = Path(contract_root) if contract_root else hb.ROOT
        self.minute_root = Path(minute_root) if minute_root else hb.ROOT
        self.freeze_fix = bool(freeze_fix)
        self.delivery_guard = bool(delivery_guard)
        self.max_stale_days = max_stale_days
        self.fill_price = fill_price
        self.slippage_ticks = float(slippage_ticks)
        self.fee_mult = float(fee_mult)
        self.enforce_tradability = bool(enforce_tradability)
        self.entry_delivery_buffer = entry_delivery_buffer
        self.entry_delivery_action = str(entry_delivery_action)
        self.option_hedge = bool(option_hedge)
        self.premium_atr_mult = float(premium_atr_mult)
        self.strike_atr_mult = float(strike_atr_mult)
        self.max_positions = int(max_positions)
        self.max_per_bucket = int(max_per_bucket)
        self.trade_exits = trade_exits if trade_exits is not None else {"target": 0, "stop": 0, "signal": 0}
        self.freeze_stats = (
            freeze_stats
            if freeze_stats is not None
            else {"proxied_bar_days": 0, "delivery_exits": 0, "freeze_exits": 0}
        )
        self.sleeve_counts = sleeve_counts if sleeve_counts is not None else {}
        self.quality_blocks = quality_blocks if quality_blocks is not None else {}
        self.block_counts = block_counts if block_counts is not None else {}
        self.delivery_entry_blocks = delivery_entry_blocks if delivery_entry_blocks is not None else {}
        self.closed = closed if closed is not None else []
        self.stats: dict[str, int] = {k: 0 for k in STAT_KEYS}
        self.hedge_payoff_total = 0.0
        self.premium_total = 0.0
        self.last_fill_cost = 0.0
        try:
            from minute_data import load_minute_bars_on_trading_day
        except Exception:  # noqa: BLE001
            load_minute_bars_on_trading_day = None  # type: ignore[assignment]
        self._load_minute = load_minute_bars_on_trading_day
        try:
            from research.data_quality.rolls import last_contract_bar, load_contract_bar
        except Exception:  # noqa: BLE001
            last_contract_bar = None  # type: ignore[assignment]
            load_contract_bar = None  # type: ignore[assignment]
        self._last_contract_bar = last_contract_bar
        self._load_contract_bar = load_contract_bar
        self.sessions_by_code: dict[str, list[str]] = {}
        for _code, _pack in series.items():
            self.sessions_by_code[_code] = [
                str(b.get("date") or "")[:10]
                for b in (_pack.get("hist") or [])
                if str(b.get("date") or "")[:10]
            ]

    # ------------------------------------------------------------------ series helpers
    def ret(self, code_: str, hist_: list, i_: int, n_: int):
        a_ = self.adj.get(code_)
        return a_.ret_n(i_, n_) if a_ is not None else _hb().ret_n(hist_, i_, n_)

    def atr(self, code_: str, hist_: list, i_: int):
        a_ = self.adj.get(code_)
        return a_.atr14(i_) if a_ is not None else _hb().atr14(hist_, i_)

    def vol_hist(self, code_: str, hist_: list):
        a_ = self.adj.get(code_)
        return a_.vol_hist() if a_ is not None else hist_

    def held_close(self, code_: str, p_: dict, i_: int, d_: str):
        if (
            str(p_.get("fill_price_basis") or "") == "contract"
            and p_.get("fill_contract")
            and self._load_contract_bar is not None
        ):
            b_ = self._load_contract_bar(
                str(p_["fill_contract"]), d_, root=self.croot, snap_bar=self.series[code_]["hist"][i_]
            )
            if b_ is not None:
                return float(b_["close"])
        return None

    def contract_day_bar(self, contract, day, cont_bar, main_now):
        """Real daily bar of ``contract`` on ``day`` (snapshot contract_*, then cache).

        Falls back to the continuous bar only when the actual main contract of
        ``day`` IS this contract (the continuous bar then is that contract)."""
        if self._load_contract_bar is not None:
            b_ = self._load_contract_bar(str(contract), day, root=self.croot, snap_bar=cont_bar)
            if b_ is not None:
                return b_
        if main_now is not None and str(main_now) == str(contract):
            return _hb().manage_ohlc_bar(cont_bar, "continuous_proxy")
        return None

    def book_usage(self, pos: dict, d: str, *, use_close_fn: bool = True):
        """R4 open-book usage on ``d`` (adjusted ATR; held contract's real close)."""
        return _hb()._book_usage(
            pos, self.idx, self.series, d, atr_fn=self.atr, close_fn=self.held_close if use_close_fn else None
        )

    # ------------------------------------------------------------------ position management
    def manage(
        self,
        code: str,
        p: dict,
        d: str,
        *,
        prev_d: str | None,
        nxt: str | None,
        acc: dict,
    ) -> dict | None:
        """Manage ``p`` on ``d``.  Returns the closed-trade row (caller drops the position) or None."""
        hb = _hb()
        series, idx, main_map = self.series, self.idx, self.main_map
        freeze_fix = self.freeze_fix
        _croot = self.croot
        hist = series[code]["hist"]
        i1 = idx[code].get(d)
        if i1 is None:
            if freeze_fix:
                p["stale_days"] = int(p.get("stale_days") or 0) + 1
            return None
        bar = hist[i1]
        fill_basis = str(p.get("fill_price_basis") or "continuous_proxy")
        proxied = False
        force_reason = None
        pre_exit = None  # (reason, px): stop gapped through at the held contract's own roll open
        held_mbar = None  # manage bar = held contract's own real bar (main ≠ held)
        mult = series[code]["meta"]["mult"]
        sign = 1 if p["direction"] == "多" else -1
        # R6b-fix: actual main-contract map (known only after d closes). It selects
        # WHICH contract's real bar prices day d and schedules a roll for d+1 open.
        use_main = bool(freeze_fix and main_map is not None and main_map.usable(code))
        cur_main = main_map.main(code, d) if use_main else None
        if use_main and fill_basis != "contract":
            held = p.get("held_contract")
            pend = p.get("pending_roll")
            if held is not None and pend:
                # (b) roll scheduled after yesterday's close → execute at d's open:
                # old contract closes at ITS open, new contract opens at ITS open.
                old_b = self.contract_day_bar(held, d, bar, cur_main)
                new_b = self.contract_day_bar(pend, d, bar, cur_main)
                p.pop("pending_roll", None)
                if old_b is None or new_b is None:
                    # (c) no real price: pre-R6 treatment (continuous spread books as PnL).
                    self.stats["roll_unpriced_cont_n"] += 1
                    p["held_contract"] = pend
                    p.setdefault("roll_events", []).append(
                        {"date": d, "from": held, "to": pend, "status": "unpriced_cont"}
                    )
                else:
                    o_open, n_open = float(old_b["open"]), float(new_b["open"])
                    if hb.roll_open_gaps_through_stop(p, o_open):
                        # Real stop gap on the OLD contract at d's open, before any roll.
                        self.stats["roll_open_gap_stops_n"] += 1
                        pre_exit = ("stop", o_open)
                        held_mbar = {
                            "open": o_open,
                            "high": o_open,
                            "low": o_open,
                            "close": o_open,
                            "date": d,
                        }
                    else:
                        acc["price_pnl"] += hb.roll_position_at_open(
                            p,
                            old_open=o_open,
                            new_open=n_open,
                            new_contract=pend,
                            day=d,
                            mult=mult,
                            sign=sign,
                        )
                        self.stats["roll_shifted_n"] += 1
                        for _px in (o_open, n_open):  # 2 fills: close old + open new
                            acc["day_cost"] += hb.fill_cost(
                                series[code]["meta"],
                                _px,
                                p["lots"],
                                slippage_ticks=self.slippage_ticks,
                                fee_mult=self.fee_mult,
                            )
            held = p.get("held_contract")
            if pre_exit is None and held is not None and cur_main is not None and cur_main != held:
                # (a) main moved off our contract: price today on the HELD contract's real bar.
                hb_ = self.contract_day_bar(held, d, bar, cur_main)
                if hb_ is None:
                    self.stats["roll_unpriced_cont_n"] += 1  # (c) pre-R6 continuous treatment from here
                    p["held_contract"] = cur_main
                    p.setdefault("roll_events", []).append(
                        {"date": d, "from": held, "to": cur_main, "status": "unpriced_cont"}
                    )
                else:
                    self.stats["roll_held_bar_days_n"] += 1
                    held_mbar = {
                        "open": float(hb_["open"]),
                        "high": float(hb_["high"]),
                        "low": float(hb_["low"]),
                        "close": float(hb_["close"]),
                        "date": d,
                    }
        contract_ohlc = None
        last_c_close = None
        last_c_date = None
        if fill_basis == "contract" and self._load_contract_bar is not None and p.get("fill_contract"):
            contract_ohlc = self._load_contract_bar(
                str(p["fill_contract"]),
                d,
                root=_croot,
                snap_bar=bar,
            )
            if contract_ohlc is None and self._last_contract_bar is not None:
                lcb = self._last_contract_bar(
                    str(p["fill_contract"]), on_or_before=str(prev_d or d)[:10], root=_croot
                )
                _ed = str(p.get("entry_date") or "")[:10]
                if lcb is not None and (not _ed or lcb["date"] >= _ed):
                    last_c_close, last_c_date = float(lcb["close"]), lcb["date"]
                else:  # never price off a bar dated before entry
                    last_c_close = float(
                        p["last_mark"] if p.get("last_mark") is not None else p["entry"]
                    )
                    last_c_date = _ed or str(d)[:10]
        if freeze_fix:
            if held_mbar is not None:
                mbar, proxied, force_reason = held_mbar, False, None
            else:
                mbar, proxied, force_reason = hb.manage_bar_fixed(
                    bar,
                    p,
                    use_main=use_main,
                    main_now=cur_main,
                    contract_ohlc=contract_ohlc,
                    last_close=last_c_close,
                    last_close_date=last_c_date,
                )
            if force_reason == "roll_unpriced":
                self.stats["roll_unpriced_n"] += 1
            if proxied:
                p["stale_days"] = int(p.get("stale_days") or 0) + 1
                self.freeze_stats["proxied_bar_days"] += 1
            else:
                p["stale_days"] = 0
        else:
            mbar = hb.manage_ohlc_bar(bar, fill_basis)
        if mbar is None:
            # Legacy (ee4476b): contract-locked position without contract
            # OHLC today is skipped (=> freeze; fixed by freeze_fix).
            return None
        # Prefer 15m first-touch only for continuous_proxy fills (minute cache
        # is continuous/month-mixed). Contract fills use same-basis daily OHLC.
        # R2: load by trading day (prev-evening night session belongs to today).
        if pre_exit is not None:
            reason, px = pre_exit
            used_minute = False
        elif force_reason == "roll_unpriced":
            reason, px = "roll_unpriced", float(mbar["close"])
            used_minute = False
        else:
            reason, px = None, mbar["close"]
            used_minute = False
            if (
                fill_basis != "contract"
                and held_mbar is None  # held-contract day: minute cache is the new main's
                and self._load_minute is not None
            ):
                try:
                    m_bars = self._load_minute(
                        self.minute_root,
                        code,
                        d,
                        period=hb.EXIT_MINUTE_PERIOD,
                        sessions=self.sessions_by_code.get(code) or [],
                    )
                except Exception:  # noqa: BLE001
                    m_bars = []
                # R2 (B): daily open is night open → keep full trading-day bars on
                # entry day (no natural-time 09:00 cutoff; night bars are prev calendar).
                if m_bars and not hb.minute_bars_match_daily(
                    m_bars, mbar, tick=float(series[code]["meta"].get("tick") or 0)
                ):
                    self.stats["minute_rejected_mismatch"] += 1
                    m_bars = []
                # Month-contract minute vs continuous entry → reject (false stops).
                if m_bars and not hb.minute_bars_aligned_with_entry(p["entry"], m_bars):
                    m_bars = []
                if m_bars:
                    m_reason, m_px = hb.apply_stop_target_intraday(
                        p["direction"], p["entry"], p["stop"], p["target"], m_bars
                    )
                    used_minute = True
                    self.stats["minute_manage_checks"] += 1
                    if m_reason:
                        reason, px = m_reason, m_px
            if not used_minute:
                reason, px = hb.apply_stop_target(
                    p["direction"], p["entry"], p["stop"], p["target"], mbar
                )
                self.stats["daily_exit_fallback_n"] += 1
            elif reason in ("stop", "target"):
                self.stats["minute_exit_n"] += 1
        # trend flip exit (Path-A conflict / opposite, or composite-trend sign flip)
        # Signal uses continuous factors; exit price stays on locked manage bar.
        if reason is None and p.get("reason") == "roll_carry":
            pair = ((self.curves.get(code) or {}).get("carry") or {}).get(d)
            gap = hb.carry_gap_pct(pair)
            if gap is not None:
                if p["direction"] == "多" and gap > 0:
                    reason, px = "signal", mbar["close"]
                elif p["direction"] == "空" and gap < 0:
                    reason, px = "signal", mbar["close"]
        elif reason is None:
            if self.mode == "ctf":
                fac = hb.composite_trend(hist, i1)
                if fac is not None:
                    if p["direction"] == "多" and fac["f"] <= 0:
                        reason, px = "signal", mbar["close"]
                    elif p["direction"] == "空" and fac["f"] >= 0:
                        reason, px = "signal", mbar["close"]
            else:
                r20, r60 = self.ret(code, hist, i1, 20), self.ret(code, hist, i1, 60)
                if r20 is not None and r60 is not None:
                    long_ok = r20 > 0 and r60 > 0
                    short_ok = r20 < 0 and r60 < 0
                    if p["direction"] == "多" and not long_ok:
                        reason, px = "signal", mbar["close"]
                    elif p["direction"] == "空" and not short_ok:
                        reason, px = "signal", mbar["close"]
        if freeze_fix and reason is None:
            fc_ym = hb.contract_delivery_ym(p.get("fill_contract")) if fill_basis == "contract" else None
            if self.delivery_guard and fc_ym and (str(d)[:7] >= fc_ym or (nxt and str(nxt)[:7] >= fc_ym)):
                reason, px = "delivery", mbar["close"]
                self.freeze_stats["delivery_exits"] += 1
            elif self.max_stale_days is not None and int(p.get("stale_days") or 0) > int(self.max_stale_days):
                reason, px = "freeze", mbar["close"]
                self.freeze_stats["freeze_exits"] += 1
        if freeze_fix:
            prev_close = p.pop("mark_from") if "mark_from" in p else p.get("last_mark")
            exit_px = px if reason else mbar["close"]
            if prev_close is not None:
                acc["price_pnl"] += (exit_px - prev_close) * mult * p["lots"] * sign
            p["last_mark"] = mbar["close"]
            if (
                reason is None
                and held_mbar is not None
                and use_main
                and fill_basis != "contract"
                and cur_main is not None
                and p.get("held_contract") is not None
                and cur_main != p.get("held_contract")
            ):
                p["pending_roll"] = cur_main  # roll at d+1 open (main_map[d] known after close)
        elif prev_d is not None:
            i0 = idx[code].get(prev_d)
            if i0 is not None:
                prev_m = hb.manage_ohlc_bar(hist[i0], fill_basis)
                if "mark_from" in p:
                    prev_close = p.pop("mark_from")
                elif prev_m is not None:
                    prev_close = prev_m["close"]
                else:
                    prev_close = None
                if prev_close is not None:
                    exit_px = px if reason else mbar["close"]
                    acc["price_pnl"] += (exit_px - prev_close) * mult * p["lots"] * sign
        if not reason:
            return None
        acc["day_cost"] += hb.fill_cost(
            series[code]["meta"],
            px,
            p["lots"],
            slippage_ticks=self.slippage_ticks,
            fee_mult=self.fee_mult,
        )
        opt_pnl = 0.0
        if self.option_hedge and p.get("opt_strike") is not None:
            opt_pnl = hb.option_payoff(
                p["direction"],
                lots=int(p["lots"]),
                strike=float(p["opt_strike"]),
                exit_px=float(px),
                mult=mult,
            )
            acc["price_pnl"] += opt_pnl
            self.hedge_payoff_total += opt_pnl
        self.trade_exits[reason] = self.trade_exits.get(reason, 0) + 1
        sleeve = str(p.get("reason") or "path_a")
        self.sleeve_counts[sleeve] = self.sleeve_counts.get(sleeve, 0) + 1
        risk = abs(p["entry"] - p["stop"]) or 1e-9
        r_mult = ((px - p["entry"]) * sign) / risk
        # R6b-fix hard rules: never exit before entry, never price off a bar
        # dated before the entry bar (entry day may only use the fill bar on).
        _ed = str(p.get("entry_date") or "")[:10]
        _xd = str(d)[:10]
        _md = str((mbar or {}).get("date") or d)[:10]
        if _ed and (_xd < _ed or _md < _ed):
            raise AssertionError(
                f"exit before entry: {code} entry={_ed} exit={_xd} price_bar={_md} reason={reason}"
            )
        _row_out = {
            "date": d,
            "code": code,
            "direction": p.get("direction"),
            "lots": p.get("lots"),
            "entry_date": p.get("entry_date"),
            "entry": round(float(p["entry"]), 4),
            "exit": round(float(px), 4),
            "stop": round(float(p["stop"]), 4) if p.get("stop") is not None else None,
            "target": round(float(p["target"]), 4) if p.get("target") is not None else None,
            "entry_reason": p.get("reason") or "path_a",
            "reason": reason,
            "sleeve": p.get("reason"),
            "R": round(r_mult, 2),
            "opt_payoff": round(opt_pnl, 2),
            "opt_premium": p.get("opt_premium"),
            "fill_price_basis": fill_basis,
            "fill_contract": p.get("fill_contract"),
        }
        if p.get("held_contract") is not None:
            _row_out["held_contract"] = p.get("held_contract")
        if p.get("roll_events"):
            _row_out["roll_events"] = p["roll_events"]
            _row_out["entry_orig"] = round(float(p.get("entry_orig", p["entry"])), 4)
        self.closed.append(_row_out)
        return _row_out

    # ------------------------------------------------------------------ T+1 entries
    def delivery_window_block(self, c_: dict, fill_bar_: dict) -> bool:
        """fix3-opt: a contract fill whose delivery month starts within
        ``entry_delivery_buffer`` weekdays of the fill date is not taken on that
        contract ("proxy": continuous main; "block": skip entry)."""
        if not (self.freeze_fix and self.delivery_guard and self.entry_delivery_buffer):
            return False
        basis_ = str(c_.get("fill_price_basis") or fill_bar_.get("fill_price_basis") or "").lower()
        if basis_ != "contract":
            return False
        ym_ = _hb().contract_delivery_ym(c_.get("fill_contract") or fill_bar_.get("contract"))
        if not ym_:
            return False
        fd_ = str(fill_bar_.get("date") or "")[:10]
        # Ex-ante calendar (weekdays; CN holidays not removed) — must NOT depend on
        # which future bars are loaded (truncation-safe).
        import numpy as _np

        n_ = int(_np.busday_count(fd_, f"{ym_}-01")) if fd_ else 0
        if n_ < int(self.entry_delivery_buffer):
            self.delivery_entry_blocks[c_["code"]] = self.delivery_entry_blocks.get(c_["code"], 0) + 1
            if str(self.entry_delivery_action) == "proxy":
                # Do not take the expiring contract: fill on the continuous main
                # series (rolls to the next dominant) at the same bar's open/close.
                px_ = fill_bar_.get("open") if self.fill_price == "next_open" else fill_bar_.get("close")
                if px_ is None:
                    return True
                shift_ = float(px_) - float(c_["entry"])
                c_["entry"] = float(px_)
                c_["stop"] = float(c_["stop"]) + shift_
                c_["target"] = float(c_["target"]) + shift_
                if "mark_from" in c_:
                    c_["mark_from"] = float(px_)
                c_["fill_price_basis"] = "continuous_proxy"
                c_.pop("fill_contract", None)
                c_["delivery_window_proxy"] = True
                return False
            return True
        return False

    def fill_selected(
        self,
        selected: list[dict],
        pos: dict,
        d: str,
        *,
        acc: dict,
        on_reject: Callable[[dict, str], None] | None = None,
    ) -> tuple[list[str], dict[str, int]]:
        """Fill the T=``d`` close selections (caps already applied) into ``pos``.

        Returns (codes entered in order, open bucket counts after the fills).  The position row
        is stored in ``pos`` (insertion order = fill order).  ``self.last_fill_cost`` is the sum of
        the entry costs (+ option premiums) of this call, accumulated in the same order."""
        hb = _hb()
        series, idx, main_map = self.series, self.idx, self.main_map
        max_positions, max_per_bucket = self.max_positions, self.max_per_bucket
        fill_cost_sum = 0.0
        entered: list[str] = []
        open_buckets: dict[str, int] = {}
        for p in pos.values():
            b = str(p.get("bucket") or "_")
            open_buckets[b] = open_buckets.get(b, 0) + 1
        for c in selected:
            if int(c.get("lots") or 0) <= 0:
                continue
            if len(pos) >= int(max_positions):
                break
            bucket = str(c.get("bucket") or "_")
            if max_per_bucket > 0 and open_buckets.get(bucket, 0) >= int(max_per_bucket):
                if on_reject is not None:
                    on_reject(c, "bucket_full")
                continue
            sig_i = idx[c["code"]][d]
            hist_c = series[c["code"]]["hist"]
            if self.fill_price == "next_open":
                c = hb.next_open_fill(c, hist_c, sig_i)
                if c is None:
                    self.quality_blocks["missing_next_open"] = self.quality_blocks.get("missing_next_open", 0) + 1
                    self.block_counts["quality:missing_next_open"] = (
                        self.block_counts.get("quality:missing_next_open", 0) + 1
                    )
                    continue
                fill_bar = hist_c[sig_i + 1]
                next_px = float(c["entry"])
                need_next = False
            else:
                fill_bar = hist_c[sig_i]
                next_px = None
                need_next = False
            if self.delivery_window_block(c, fill_bar):
                self.block_counts["delivery_window"] = self.block_counts.get("delivery_window", 0) + 1
                if on_reject is not None:
                    on_reject(c, "delivery_window")
                continue
            if self.enforce_tradability:
                ok_q, qrec = hb.entry_fill_allowed(
                    c["code"],
                    fill_bar,
                    series[c["code"]]["meta"],
                    side=c["direction"],
                    atr=c.get("atr"),
                    asof=str(fill_bar.get("date") or d),
                    next_open=next_px,
                    require_next_open=need_next,
                )
                if not ok_q:
                    reason_q = ",".join(qrec.get("reasons") or [qrec.get("status") or "quality"])
                    key = f"quality:{qrec.get('status') or 'BLOCK'}"
                    self.quality_blocks[key] = self.quality_blocks.get(key, 0) + 1
                    self.quality_blocks[reason_q] = self.quality_blocks.get(reason_q, 0) + 1
                    self.block_counts[key] = self.block_counts.get(key, 0) + 1
                    if on_reject is not None:
                        on_reject(c, key)
                    continue
            row = {
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
                "reason": c.get("reason"),
                "fill_price_basis": str(
                    c.get("fill_price_basis")
                    or fill_bar.get("fill_price_basis")
                    or "continuous_proxy"
                ),
            }
            if c.get("fill_contract") or fill_bar.get("contract"):
                row["fill_contract"] = c.get("fill_contract") or fill_bar.get("contract")
            if c.get("mark_from") is not None:
                row["mark_from"] = c["mark_from"]
            if main_map is not None and main_map.usable(c["code"]) and row["fill_price_basis"] != "contract":
                # R6b-fix: continuous_proxy position remembers the actual main contract
                # of its entry day; None → pre-R6 continuous treatment (counted).
                row["held_contract"] = main_map.main(c["code"], row["entry_date"])
                if row["held_contract"] is None:
                    self.stats["held_missing_n"] += 1
            if self.option_hedge:
                atr_v = float(c.get("atr") or 0)
                row = hb.attach_hedge_to_position(
                    row,
                    atr=atr_v,
                    mult=float(series[c["code"]]["meta"]["mult"]),
                    premium_atr_mult=self.premium_atr_mult,
                    strike_atr_mult=self.strike_atr_mult,
                )
                prem = float(row.get("opt_premium") or 0)
                acc["day_cost"] += prem
                fill_cost_sum += prem
                self.premium_total += prem
            pos[c["code"]] = row
            _fc = hb.fill_cost(
                series[c["code"]]["meta"],
                c["entry"],
                c["lots"],
                slippage_ticks=self.slippage_ticks,
                fee_mult=self.fee_mult,
            )
            acc["day_cost"] += _fc
            fill_cost_sum += _fc
            open_buckets[bucket] = open_buckets.get(bucket, 0) + 1
            entered.append(c["code"])
        self.last_fill_cost = fill_cost_sum
        return entered, open_buckets
