# -*- coding: utf-8 -*-
"""Day-to-day call/put wall migration labels."""
from __future__ import annotations

from typing import Any

from gamma_wall import load_history, migration_rows


def classify_wall_migration(contract: str, *, window: int = 20, root=None) -> dict[str, Any]:
    rows = migration_rows(contract, window=window, root=root)
    if len(rows) < 2:
        return {
            "ok": False,
            "error": "need_ge_2_snapshots",
            "contract": contract,
            "n": len(rows),
            "rows": rows,
        }
    events = []
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        for side, key in (("call", "call_wall"), ("put", "put_wall")):
            prev, cur = float(a[key]), float(b[key])
            move = cur - prev
            gex_key = f"{side}_wall_gex"
            g0, g1 = a.get(gex_key), b.get(gex_key)
            strength = None
            if g0 not in (None, 0) and g1 is not None:
                try:
                    strength = float(g1) / float(g0) - 1.0
                except (TypeError, ValueError, ZeroDivisionError):
                    strength = None
            if abs(move) < 1e-9:
                label = "unchanged"
            elif strength is not None and strength <= -0.25 and abs(move) < abs(prev) * 0.01:
                label = "weakened"
            elif abs(move) >= max(50.0, abs(prev) * 0.005):
                label = "migrated"
            else:
                label = "micro_move"
            # disappeared: gex collapsed
            if g1 is not None and g0 not in (None, 0):
                try:
                    if abs(float(g1)) < abs(float(g0)) * 0.15:
                        label = "weakened_or_fading"
                except (TypeError, ValueError):
                    pass
            events.append(
                {
                    "date": b["date"],
                    "side": side,
                    "from": prev,
                    "to": cur,
                    "move": move,
                    "label": label,
                    "gex_change_pct": None if strength is None else round(strength, 4),
                    "futures_price": b.get("futures_price"),
                    "dist_pct": b.get(f"{side}_dist_pct"),
                }
            )
    # New wall: large jump vs prior
    for e in events:
        if e["label"] == "migrated" and abs(e["move"]) >= 200:
            e["label"] = "new_or_shifted_wall"
    counts: dict[str, int] = {}
    for e in events:
        counts[e["label"]] = counts.get(e["label"], 0) + 1
    return {
        "ok": True,
        "schema": "cta-gamma-migration-v1",
        "contract": contract.upper(),
        "n_snapshots": len(rows),
        "n_events": len(events),
        "label_counts": counts,
        "events": events,
        "series": rows,
        "live_trading": False,
        "note": "Display GEX convention; OI does not identify dealer side.",
    }
