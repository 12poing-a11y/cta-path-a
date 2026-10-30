# -*- coding: utf-8 -*-
"""Copy Path-A continuous daily bars into lab/data/bars/continuous (JSONL-ish JSON)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
sys.path.insert(0, str(ROOT))

from desk.regime_board import load_local_bars  # noqa: E402


def _codes() -> list[str]:
    uni = json.loads((LAB / "config" / "universe_lab.json").read_text(encoding="utf-8"))
    return [str(c).upper() for c in (uni.get("path_a_codes") or [])]


def main() -> int:
    out_dir = LAB / "data" / "bars" / "continuous"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for code in _codes():
        bars, source = load_local_bars(ROOT, code)
        payload = {
            "code": code,
            "source": source,
            "n": len(bars),
            "start": bars[0]["date"] if bars else None,
            "end": bars[-1]["date"] if bars else None,
            "bars": bars,
        }
        path = out_dir / f"{code}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        rows.append(
            {
                "code": code,
                "n": len(bars),
                "start": payload["start"],
                "end": payload["end"],
                "source": source,
                "bytes": path.stat().st_size,
            }
        )
        print(f"[ingest] {code} n={len(bars)} src={source}")
    manifest = {"ok": True, "codes": rows, "dir": str(out_dir).replace("\\", "/")}
    (LAB / "data" / "bars" / "continuous_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[ingest] wrote {len(rows)} codes → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
