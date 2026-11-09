# -*- coding: utf-8 -*-
"""Desk prediction log (P0) — paper research only.

Persists daily 总盘面 conclusions as falsifiable predictions with
1/3/5-session horizons. Does not change Path-A entry or live sizing.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PRED_DIR = ROOT / "lab" / "research" / "predictions"
HORIZONS = (1, 3, 5)
MODEL_TAG = "desk_total_board_v1"


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _ymd(text: Any) -> str:
    s = str(text or "").replace("-", "").replace("/", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _iso_date(ymd: str) -> str:
    y = _ymd(ymd)
    if len(y) != 8:
        return str(ymd or "")
    return f"{y[:4]}-{y[4:6]}-{y[6:8]}"


def conclusion_to_direction(conclusion: str | None) -> str:
    c = str(conclusion or "").strip()
    if "偏多" in c or c in ("多", "做多"):
        return "多"
    if "偏空" in c or c in ("空", "做空"):
        return "空"
    return "观望"


def git_sha_short(root: Path | None = None) -> str | None:
    root = Path(root or ROOT)
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        sha = (out or "").strip()
        return sha or None
    except (OSError, subprocess.SubprocessError):
        return None


def _falsify_hint(*, direction: str, align: str, path_a: str, sent: str) -> str:
    if direction == "观望":
        return "出现同向Path-A+情绪且波动非硬否决时方可改方向"
    parts = [f"预测方向{direction}被证伪："]
    if align == "冲突":
        parts.append("冲突未解除或反向突破")
    if path_a in ("多", "空") and path_a != direction:
        parts.append(f"Path-A维持{path_a}")
    if sent in ("多", "空") and sent != direction:
        parts.append(f"情绪维持{sent}")
    parts.append("或到期收益符号相反")
    return "；".join(parts)


def collect_board_rows(root: Path | None = None) -> dict[str, Any]:
    """Build Path-A × sentiment × vol 总盘面 rows (no Streamlit)."""
    root = Path(root or ROOT)
    from desk.sentiment_panel import (  # local import keeps desk optional for CLI tests
        _path_a_sides,
        load_sentiment_snapshot,
        portfolio_total_verdict,
        sentiment_verdict,
        total_board_conclusion,
    )

    snap = load_sentiment_snapshot(root)
    if not snap:
        return {"ok": False, "error": "no_sentiment_snapshot", "rows": [], "asof": None}

    verdict = sentiment_verdict(snap)
    conv = float(verdict.get("conviction_pct") or 0.0)
    path_a = _path_a_sides(root)
    longs = {str(x).upper() for x in (snap.get("longs") or [])}
    shorts = {str(x).upper() for x in (snap.get("shorts") or [])}

    vol_map: dict[str, dict[str, Any]] = {}
    try:
        from desk.vol_engine_panel import vol_fields_by_code

        vol_map = vol_fields_by_code(root) or {}
    except Exception as exc:  # noqa: BLE001
        vol_map = {}
        vol_err = f"{type(exc).__name__}: {exc}"
    else:
        vol_err = None

    # Fallback: desk_board overlay on vol snapshot
    if not vol_map:
        vol_snap = _read_json(root / "data" / "vol_engine_latest.json") or {}
        overlay = (vol_snap.get("desk_board") or {}) if isinstance(vol_snap, dict) else {}
        if isinstance(overlay, dict):
            for code, row in overlay.items():
                if isinstance(row, dict):
                    vol_map[str(code).upper()] = {
                        "盘面结论": row.get("盘面结论") or row.get("结论") or "观望"
                    }

    codes = sorted(set(longs) | set(shorts) | set(path_a) | set(vol_map))
    rows: list[dict[str, Any]] = []
    for code in codes:
        sent = "多" if code in longs else ("空" if code in shorts else "—")
        pa = path_a.get(code) or "—"
        if sent in ("多", "空") and pa in ("多", "空"):
            align = "同向" if sent == pa else "冲突"
        elif sent in ("多", "空"):
            align = "仅情绪"
        elif pa in ("多", "空"):
            align = "仅Path-A"
        else:
            align = "—"
        vol_c = str((vol_map.get(code) or {}).get("盘面结论") or "观望")
        tot = total_board_conclusion(
            align=align,
            path_a=pa,
            sent=sent,
            vol_conclusion=vol_c,
            sentiment_conviction=conv,
        )
        rows.append(
            {
                "code": code,
                "path_a": pa,
                "sentiment": sent,
                "align": align,
                "vol": vol_c,
                "conclusion": tot.get("结论") or "观望",
                "note": tot.get("note") or "",
            }
        )

    book = portfolio_total_verdict(
        [{"总结论": r["conclusion"]} for r in rows],
        sentiment_direction=str(verdict.get("direction") or "—"),
        sentiment_conviction=conv,
    )
    asof = _ymd(snap.get("asof")) or _ymd(
        (_read_json(root / "l1_report_risk15.json") or {}).get("asof")
    )
    return {
        "ok": True,
        "asof": asof,
        "rows": rows,
        "verdict": verdict,
        "book": book,
        "vol_error": vol_err,
        "conviction_pct": conv,
    }


def _entry_close(root: Path, code: str, asof: str) -> float | None:
    path = root / "lab" / "data" / "bars" / "continuous" / f"{code.upper()}.json"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    want = _iso_date(asof)
    want_compact = _ymd(asof)
    bars = payload.get("bars") or []
    # Prefer exact asof; else last bar on/before asof.
    best = None
    best_d = ""
    for b in bars:
        if not isinstance(b, dict):
            continue
        d = str(b.get("date") or "")
        dc = _ymd(d)
        if not dc:
            continue
        if d == want or dc == want_compact:
            try:
                return float(b["close"])
            except (TypeError, ValueError, KeyError):
                return None
        if dc <= want_compact and dc >= best_d:
            best_d = dc
            try:
                best = float(b["close"])
            except (TypeError, ValueError, KeyError):
                best = None
    return best


def rows_to_predictions(
    board: dict[str, Any],
    *,
    root: Path | None = None,
    horizons: tuple[int, ...] = HORIZONS,
) -> list[dict[str, Any]]:
    root = Path(root or ROOT)
    asof = _ymd(board.get("asof"))
    if not asof:
        return []
    conv = float(board.get("conviction_pct") or 0.0)
    sha = git_sha_short(root)
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for row in board.get("rows") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        if not code:
            continue
        conclusion = str(row.get("conclusion") or "观望")
        direction = conclusion_to_direction(conclusion)
        pred_id = f"PRED-{asof}-{code}"
        scores = {
            str(h): {"status": "pending", "horizon_days": h} for h in horizons
        }
        out.append(
            {
                "id": pred_id,
                "asof": asof,
                "asof_iso": _iso_date(asof),
                "code": code,
                "direction": direction,
                "conclusion": conclusion,
                "conviction_pct": round(conv, 1),
                "note": row.get("note") or "",
                "falsify": _falsify_hint(
                    direction=direction,
                    align=str(row.get("align") or "—"),
                    path_a=str(row.get("path_a") or "—"),
                    sent=str(row.get("sentiment") or "—"),
                ),
                "sources": {
                    "path_a": row.get("path_a"),
                    "sentiment": row.get("sentiment"),
                    "align": row.get("align"),
                    "vol": row.get("vol"),
                },
                "horizons": list(horizons),
                "entry_close": _entry_close(root, code, asof),
                "scores": scores,
                "model_tag": MODEL_TAG,
                "git_sha": sha,
                "live_trading": False,
                "created_at": now,
                "updated_at": now,
            }
        )
    return out


def store_path(root: Path | None = None, asof: str | None = None) -> Path:
    root = Path(root or ROOT)
    day = _ymd(asof)
    if day:
        return root / "lab" / "research" / "predictions" / f"pred_{day}.json"
    return root / "lab" / "research" / "predictions" / "latest.json"


def load_day(root: Path | None = None, asof: str | None = None) -> dict[str, Any] | None:
    root = Path(root or ROOT)
    path = store_path(root, asof) if asof else root / "lab" / "research" / "predictions" / "latest.json"
    data = _read_json(path)
    return data if isinstance(data, dict) else None


def list_prediction_files(root: Path | None = None) -> list[Path]:
    root = Path(root or ROOT)
    d = root / "lab" / "research" / "predictions"
    if not d.is_dir():
        return []
    return sorted(d.glob("pred_*.json"))


def write_desk_predictions(
    root: Path | None = None,
    *,
    board: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect desk 总盘面 and persist prediction log for the day."""
    root = Path(root or ROOT)
    board = board if isinstance(board, dict) else collect_board_rows(root)
    if not board.get("ok"):
        return {
            "ok": False,
            "error": board.get("error") or "board_failed",
            "n": 0,
        }
    preds = rows_to_predictions(board, root=root)
    asof = _ymd(board.get("asof"))
    payload = {
        "ok": True,
        "asof": asof,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_tag": MODEL_TAG,
        "live_trading": False,
        "n": len(preds),
        "portfolio": board.get("book"),
        "sentiment": board.get("verdict"),
        "predictions": preds,
        "note": "纸面预测日志；不改 Path-A 入场。到期由 prediction_score 归因。",
    }
    day_path = store_path(root, asof)
    latest = root / "lab" / "research" / "predictions" / "latest.json"
    _write_json(day_path, payload)
    _write_json(latest, payload)
    return {
        "ok": True,
        "asof": asof,
        "n": len(preds),
        "path": str(day_path).replace("\\", "/"),
        "latest": str(latest).replace("\\", "/"),
    }


def main() -> int:
    out = write_desk_predictions(ROOT)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
