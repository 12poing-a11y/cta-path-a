# -*- coding: utf-8 -*-
"""VP Phase 1A engine: accounts, manual fills, read-only load, explicit rebuild."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_a_filters import fill_cost

from virtual_portfolio.guard import assert_vp_write_path, vp_data_root
from virtual_portfolio.instruments import (
    commission_meta,
    get_instrument,
    resolve_margin,
    slippage_ticks_default,
)
from virtual_portfolio.ledger import append_event, load_events
from virtual_portfolio.paths import (
    account_dir,
    account_json_path,
    equity_json_path,
    positions_json_path,
    validate_account_id,
)
from virtual_portfolio.permissions import (
    VpPermissionError,
    assert_auto_close_allowed,
    assert_auto_open_allowed,
    assert_manual_ops_allowed,
    assert_signal_ingest_allowed,
    default_runtime_flags,
    derive_margin_status,
    resolve_runtime,
)

ACCOUNT_SCHEMA = "cta-vp-account-v1"
ALLOWED_SOURCES = frozenset({"MANUAL", "SYSTEM_TEST"})
ALLOWED_SIDES = frozenset({"long", "short"})


class VpError(ValueError):
    """Business-rule rejection for VP operations."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, root: Path, payload: dict[str, Any]) -> None:
    assert_vp_write_path(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert_vp_write_path(path, root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    assert_vp_write_path(tmp, root)
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _assert_price_on_tick(price: float, tick: float) -> None:
    if tick <= 0:
        raise VpError("REJECTED:MISSING_CONTRACT_SPEC")
    n = round(float(price) / float(tick))
    aligned = n * float(tick)
    if abs(aligned - float(price)) > max(1e-9, abs(float(price)) * 1e-12):
        raise VpError("REJECTED:PRICE_NOT_ON_TICK")


def _runtime_for_account(root: Path, account_id: str) -> dict[str, Any]:
    meta = _read_json(account_json_path(root, account_id)) or {}
    return resolve_runtime(meta)


def _check_source(source: str, runtime: dict[str, Any]) -> None:
    if source in ALLOWED_SOURCES:
        assert_manual_ops_allowed(runtime)
        return
    if source == "CTA_SIGNAL":
        # Backend fail-closed even if someone bypasses Phase-1A source set later.
        assert_signal_ingest_allowed(runtime)
        assert_auto_open_allowed(runtime)
        raise VpError(
            "source 'CTA_SIGNAL' not allowed in Phase 1A; use MANUAL|SYSTEM_TEST"
        )
    raise VpError(
        f"source {source!r} not allowed in Phase 1A; use MANUAL|SYSTEM_TEST "
        "(CTA_SIGNAL reserved for Phase 1B)"
    )


def list_accounts(root: Path) -> list[str]:
    base = vp_data_root(root)
    if not base.is_dir():
        return []
    out: list[str] = []
    for p in sorted(base.iterdir()):
        if p.is_dir() and (p / "account.json").is_file():
            out.append(p.name)
    return out


def create_account(
    root: Path,
    account_id: str,
    *,
    name: str | None = None,
    initial_cash: float = 0.0,
    currency: str = "CNY",
) -> dict[str, Any]:
    aid = validate_account_id(account_id)
    if aid in list_accounts(root):
        raise VpError(f"account already exists: {aid}")
    account_dir(root, aid, create=True)
    cash = float(initial_cash or 0.0)
    if cash < 0:
        raise VpError("initial_cash must be >= 0")
    meta = {
        "schema": ACCOUNT_SCHEMA,
        "account_id": aid,
        "name": name or aid,
        "currency": currency,
        "status": "active",
        "initial_cash": cash,
        "created_event_id": None,
        **default_runtime_flags(),
    }
    _write_json(account_json_path(root, aid), root, meta)
    if cash > 0:
        ev = append_event(
            root,
            aid,
            {
                "kind": "deposit",
                "asof": None,
                "amount": cash,
                "source": "MANUAL",
                "client_event_id": f"bootstrap:{aid}",
                "note": "initial_cash",
            },
        )
        meta["created_event_id"] = ev.get("event_id")
        _write_json(account_json_path(root, aid), root, meta)
    return rebuild_account(root, aid, note="create_account")


def deposit(
    root: Path,
    account_id: str,
    amount: float,
    *,
    asof: str | None = None,
    source: str = "MANUAL",
    note: str = "",
    client_event_id: str | None = None,
) -> dict[str, Any]:
    _check_source(source, _runtime_for_account(root, account_id))
    if float(amount) <= 0:
        raise VpError("deposit amount must be > 0")
    append_event(
        root,
        account_id,
        {
            "kind": "deposit",
            "asof": asof,
            "amount": float(amount),
            "source": source,
            "note": note,
            "client_event_id": client_event_id or str(uuid.uuid4()),
        },
    )
    return rebuild_account(root, account_id)


def withdraw(
    root: Path,
    account_id: str,
    amount: float,
    *,
    asof: str | None = None,
    source: str = "MANUAL",
    note: str = "",
    client_event_id: str | None = None,
) -> dict[str, Any]:
    _check_source(source, _runtime_for_account(root, account_id))
    if float(amount) <= 0:
        raise VpError("withdraw amount must be > 0")
    state = compute_account_state(root, account_id)
    if float(amount) > float(state["equity"]["cash"]) + 1e-9:
        raise VpError("insufficient cash for withdraw")
    append_event(
        root,
        account_id,
        {
            "kind": "withdraw",
            "asof": asof,
            "amount": float(amount),
            "source": source,
            "note": note,
            "client_event_id": client_event_id or str(uuid.uuid4()),
        },
    )
    return rebuild_account(root, account_id)


def open_position(
    root: Path,
    account_id: str,
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    asof: str,
    source: str = "MANUAL",
    note: str = "",
    client_event_id: str | None = None,
    fill_policy: str = "next_open",
    slippage_ticks: float | None = None,
    close_today: bool = False,
) -> dict[str, Any]:
    runtime = _runtime_for_account(root, account_id)
    _check_source(source, runtime)
    side = str(side).lower()
    if side not in ALLOWED_SIDES:
        raise VpError("side must be long|short")
    qty_i = int(qty)
    if qty_i <= 0:
        raise VpError("qty must be positive integer lots")
    if float(price) <= 0:
        raise VpError("price must be > 0")
    if not asof:
        raise VpError("asof required")

    inst = get_instrument(root, symbol, asof=asof)
    if inst is None:
        raise VpError(f"unknown instrument: {symbol}")
    mult = float(inst.get("contract_multiplier") or 0)
    tick = float(inst.get("tick_size") or 0)
    if mult <= 0 or tick <= 0:
        raise VpError("REJECTED:MISSING_CONTRACT_SPEC")
    _assert_price_on_tick(float(price), tick)

    rate, tier, mflags = resolve_margin(inst, side=side, preferred_tier="broker")
    meta = commission_meta(inst, kind="open")
    flags = list(mflags) + list(meta.pop("_flags", []))
    slip = float(slippage_ticks) if slippage_ticks is not None else slippage_ticks_default(root)
    cost = float(fill_cost(meta, price, qty_i, slippage_ticks=slip))

    margin_used = None
    if rate is not None:
        margin_used = abs(qty_i) * mult * float(price) * rate
    else:
        flags.append("MARGIN_DATA_MISSING")

    ev = {
        "kind": "open",
        "symbol": str(symbol).upper(),
        "side": side,
        "qty": qty_i,
        "price": float(price),
        "asof": asof,
        "fee": cost,
        "slippage_ticks": slip,
        "margin_rate": rate,
        "margin_tier": tier or None,
        "margin_used": margin_used,
        "fill_policy": fill_policy,
        "source": source,
        "note": note,
        "flags": flags,
        "margin_complete": "MARGIN_DATA_MISSING" not in flags,
        "client_event_id": client_event_id or str(uuid.uuid4()),
        "fee_kind": "open",
        "close_today": bool(close_today),
        "instruments_schema": "cta-vp-instruments-v1",
    }
    # Pre-check against in-memory compute — no projection write.
    state = compute_account_state(root, account_id)
    cash = float(state["equity"]["cash"])
    if cost > cash + 1e-9:
        raise VpError("REJECTED:INSUFFICIENT_CASH_FOR_FEE")
    if margin_used is not None:
        available = float(state["equity"]["available"])
        if margin_used + cost > available + 1e-9:
            raise VpError("REJECTED:INSUFFICIENT_AVAILABLE")

    out = append_event(root, account_id, ev)
    rebuilt = rebuild_account(root, account_id)
    rebuilt["last_event"] = out
    return rebuilt


def close_position(
    root: Path,
    account_id: str,
    *,
    symbol: str,
    qty: float,
    price: float,
    asof: str,
    source: str = "MANUAL",
    note: str = "",
    client_event_id: str | None = None,
    fill_policy: str = "next_open",
    slippage_ticks: float | None = None,
    close_today: bool = False,
) -> dict[str, Any]:
    runtime = _runtime_for_account(root, account_id)
    _check_source(source, runtime)
    qty_i = int(qty)
    if qty_i <= 0:
        raise VpError("qty must be positive integer lots")
    if float(price) <= 0:
        raise VpError("price must be > 0")
    sym = str(symbol).upper()
    state = compute_account_state(root, account_id)
    pos = next((p for p in state["positions"] if p["symbol"] == sym), None)
    if not pos or int(pos["qty"]) <= 0:
        raise VpError("REJECTED:NO_POSITION")
    if qty_i > int(pos["qty"]):
        raise VpError("REJECTED:QTY_EXCEEDS_POSITION")

    inst = get_instrument(root, sym, asof=asof)
    if inst is None:
        raise VpError(f"unknown instrument: {sym}")
    tick = float(inst.get("tick_size") or 0)
    _assert_price_on_tick(float(price), tick)
    side = pos["side"]
    mult = float(inst.get("contract_multiplier") or 0)
    meta = commission_meta(inst, kind="close_today" if close_today else "close")
    flags = list(meta.pop("_flags", []))
    slip = float(slippage_ticks) if slippage_ticks is not None else slippage_ticks_default(root)
    cost = float(fill_cost(meta, price, qty_i, slippage_ticks=slip))
    avg = float(pos["avg_price"])
    raw = (float(price) - avg) * mult * qty_i
    if side == "short":
        raw = -raw
    realized = raw - cost

    ev = {
        "kind": "close",
        "symbol": sym,
        "side": side,
        "qty": qty_i,
        "price": float(price),
        "asof": asof,
        "fee": cost,
        "slippage_ticks": slip,
        "realized_pnl": realized,
        "fill_policy": fill_policy,
        "source": source,
        "note": note,
        "flags": flags,
        "client_event_id": client_event_id or str(uuid.uuid4()),
        "close_today": bool(close_today),
        "fee_kind": "close_today" if close_today else "close",
        "instruments_schema": "cta-vp-instruments-v1",
    }
    out = append_event(root, account_id, ev)
    rebuilt = rebuild_account(root, account_id)
    rebuilt["last_event"] = out
    return rebuilt


def mark_positions(
    root: Path,
    account_id: str,
    marks: dict[str, float],
    *,
    asof: str,
    source: str = "MANUAL",
    note: str = "",
    client_event_id: str | None = None,
) -> dict[str, Any]:
    _check_source(source, _runtime_for_account(root, account_id))
    clean = {str(k).upper(): float(v) for k, v in (marks or {}).items() if float(v) > 0}
    if not clean:
        raise VpError("marks required")
    append_event(
        root,
        account_id,
        {
            "kind": "mark",
            "asof": asof,
            "marks": clean,
            "source": source,
            "note": note,
            "client_event_id": client_event_id or str(uuid.uuid4()),
        },
    )
    return rebuild_account(root, account_id)


def compute_account_state(root: Path, account_id: str) -> dict[str, Any]:
    """Replay ledger → state in memory. **Never writes**."""
    aid = validate_account_id(account_id)
    path_acct = account_json_path(root, aid)
    if not path_acct.is_file():
        raise VpError(f"account not found: {aid}")
    meta = json.loads(path_acct.read_text(encoding="utf-8"))
    runtime = resolve_runtime(meta)

    cash = 0.0
    realized = 0.0
    positions: dict[str, dict[str, Any]] = {}
    marks: dict[str, float] = {}
    flags_acc: set[str] = set()
    last_asof: str | None = None
    events = load_events(root, aid)
    verified_margin = False

    for ev in events:
        kind = ev.get("kind")
        last_asof = ev.get("asof") or last_asof
        for f in ev.get("flags") or []:
            flags_acc.add(str(f))
        if kind == "deposit":
            cash += float(ev.get("amount") or 0)
        elif kind == "withdraw":
            cash -= float(ev.get("amount") or 0)
        elif kind == "open":
            sym = str(ev.get("symbol") or "").upper()
            side = str(ev.get("side") or "")
            qty = int(ev.get("qty") or 0)
            px = float(ev.get("price") or 0)
            fee = float(ev.get("fee") or 0)
            cash -= fee
            pos = positions.get(sym)
            if pos is None:
                positions[sym] = {
                    "symbol": sym,
                    "side": side,
                    "qty": qty,
                    "avg_price": px,
                    "opened_asof": ev.get("asof"),
                    "lots": [
                        {
                            "qty": qty,
                            "price": px,
                            "asof": ev.get("asof"),
                            "event_id": ev.get("event_id"),
                        }
                    ],
                    "margin_rate": ev.get("margin_rate"),
                    "margin_tier": ev.get("margin_tier"),
                }
            else:
                if pos["side"] != side:
                    raise VpError(f"ledger corrupt: side flip on {sym} without close")
                old_q = int(pos["qty"])
                new_q = old_q + qty
                pos["avg_price"] = (float(pos["avg_price"]) * old_q + px * qty) / new_q
                pos["qty"] = new_q
                pos.setdefault("lots", []).append(
                    {
                        "qty": qty,
                        "price": px,
                        "asof": ev.get("asof"),
                        "event_id": ev.get("event_id"),
                    }
                )
            if ev.get("margin_rate") is not None:
                marks.setdefault(sym, px)
        elif kind == "close":
            sym = str(ev.get("symbol") or "").upper()
            qty = int(ev.get("qty") or 0)
            rp = float(ev.get("realized_pnl") or 0)
            cash += rp
            realized += rp
            pos = positions.get(sym)
            if not pos:
                continue
            pos["qty"] = int(pos["qty"]) - qty
            left = qty
            lots = list(pos.get("lots") or [])
            new_lots = []
            for lot in lots:
                if left <= 0:
                    new_lots.append(lot)
                    continue
                lq = int(lot["qty"])
                take = min(lq, left)
                rem = lq - take
                left -= take
                if rem > 0:
                    new_lots.append({**lot, "qty": rem})
            pos["lots"] = new_lots
            if pos["qty"] <= 0:
                positions.pop(sym, None)
                marks.pop(sym, None)
        elif kind == "mark":
            for s, px in (ev.get("marks") or {}).items():
                marks[str(s).upper()] = float(px)

    unrealized = 0.0
    margin_used = 0.0
    margin_complete = "MARGIN_DATA_MISSING" not in flags_acc
    pos_list = []
    for sym, pos in positions.items():
        qty = int(pos["qty"])
        if qty <= 0:
            continue
        mark = marks.get(sym, float(pos["avg_price"]))
        inst = get_instrument(root, sym, asof=last_asof)
        mult = float((inst or {}).get("contract_multiplier") or 0)
        avg = float(pos["avg_price"])
        upnl = (mark - avg) * mult * qty
        if pos["side"] == "short":
            upnl = -upnl
        unrealized += upnl
        rate = pos.get("margin_rate")
        if rate is None and inst is not None:
            rate, _, mflags = resolve_margin(inst, side=pos["side"])
            flags_acc.update(mflags)
            if inst.get("verified_at"):
                verified_margin = True
        if rate is not None and mult > 0:
            margin_used += abs(qty) * mult * mark * float(rate)
        else:
            margin_complete = False
            flags_acc.add("MARGIN_DATA_MISSING")
        pos_list.append({**pos, "mark": mark, "unrealized_pnl": upnl})

    derived_margin = derive_margin_status(flags_acc, verified_any=verified_margin)
    # Account meta may already set MARGIN_STATUS; keep UNVERIFIED unless MISSING.
    margin_status = runtime.get("MARGIN_STATUS") or "UNVERIFIED"
    if derived_margin == "MISSING":
        margin_status = "MISSING"
    elif margin_status == "VERIFIED" and derived_margin == "UNVERIFIED":
        # Do not silently keep VERIFIED if instruments unverified.
        margin_status = "UNVERIFIED"

    equity = cash + unrealized
    available = equity - margin_used
    equity_doc = {
        "schema": "cta-vp-equity-v1",
        "account_id": aid,
        "asof": last_asof,
        "cash": round(cash, 6),
        "unrealized_pnl": round(unrealized, 6),
        "realized_pnl": round(realized, 6),
        "equity": round(equity, 6),
        "margin_used": round(margin_used, 6),
        "available": round(available, 6),
        "margin_complete": margin_complete,
        "flags": sorted(flags_acc),
        "MARGIN_STATUS": margin_status,
    }
    meta_out = {
        **meta,
        "schema": ACCOUNT_SCHEMA,
        "account_id": aid,
        "margin_complete": margin_complete,
        "flags": sorted(flags_acc),
        "n_events": len(events),
        "ACCOUNT_MODE": runtime.get("ACCOUNT_MODE"),
        "MARGIN_STATUS": margin_status,
        "AUTO_OPEN_ALLOWED": bool(runtime.get("AUTO_OPEN_ALLOWED")),
        "AUTO_CLOSE_ALLOWED": bool(runtime.get("AUTO_CLOSE_ALLOWED")),
        "SIGNAL_INGEST_ALLOWED": bool(runtime.get("SIGNAL_INGEST_ALLOWED")),
    }
    return {
        "account": meta_out,
        "positions": pos_list,
        "equity": equity_doc,
        "n_events": len(events),
        "projections_written": False,
    }


def load_account_state(root: Path, account_id: str) -> dict[str, Any]:
    """Read-only load. Never rebuilds/writes projections.

    If projection files exist, return them (plus runtime flags from account.json).
    If missing, return ``compute_account_state`` in memory with
    ``projections_missing=True`` — still no write.
    """
    aid = validate_account_id(account_id)
    acct = _read_json(account_json_path(root, aid))
    if acct is None:
        raise VpError(f"account not found: {aid}")
    pos = _read_json(positions_json_path(root, aid))
    eq = _read_json(equity_json_path(root, aid))
    if pos is not None and eq is not None:
        runtime = resolve_runtime(acct)
        acct_out = {**acct, **{k: runtime[k] for k in runtime}}
        return {
            "account": acct_out,
            "positions": list(pos.get("positions") or []),
            "equity": eq,
            "n_events": int(acct.get("n_events") or 0),
            "projections_written": False,
            "projections_missing": False,
            "read_only": True,
        }
    computed = compute_account_state(root, aid)
    computed["projections_missing"] = True
    computed["read_only"] = True
    return computed


def rebuild_account(
    root: Path,
    account_id: str,
    *,
    note: str = "",
) -> dict[str, Any]:
    """Explicit projection rebuild: compute + write + audit log. Idempotent content."""
    aid = validate_account_id(account_id)
    state = compute_account_state(root, aid)
    meta_out = dict(state["account"])
    pos_list = state["positions"]
    equity_doc = dict(state["equity"])
    pos_doc = {
        "schema": "cta-vp-positions-v1",
        "account_id": aid,
        "asof": equity_doc.get("asof"),
        "positions": pos_list,
    }
    _write_json(account_json_path(root, aid), root, meta_out)
    _write_json(positions_json_path(root, aid), root, pos_doc)
    _write_json(equity_json_path(root, aid), root, equity_doc)

    # Audit trail separate from cash ledger (does not affect balances).
    audit_path = account_dir(root, aid) / "rebuild_audit.jsonl"
    assert_vp_write_path(audit_path, root)
    audit_row = {
        "ts": _iso_now(),
        "account_id": aid,
        "n_events": state["n_events"],
        "equity": equity_doc.get("equity"),
        "note": note or "rebuild_account",
    }
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(audit_row, ensure_ascii=False) + "\n")

    return {
        "account": meta_out,
        "positions": pos_list,
        "equity": equity_doc,
        "n_events": state["n_events"],
        "projections_written": True,
        "projections_missing": False,
        "read_only": False,
    }


def check_auto_permissions(root: Path, account_id: str, *, action: str) -> None:
    """Backend gate for future 1B — fail closed. ``action``: open|close|ingest."""
    runtime = _runtime_for_account(root, account_id)
    if action == "open":
        assert_auto_open_allowed(runtime)
    elif action == "close":
        assert_auto_close_allowed(runtime)
    elif action == "ingest":
        assert_signal_ingest_allowed(runtime)
    else:
        raise VpPermissionError(f"unknown action: {action}")
