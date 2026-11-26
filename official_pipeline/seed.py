# -*- coding: utf-8 -*-
"""Seed the official store from the R8 raw library (day 0). Each stored day is checked first:
sha256(decompressed body) must equal the manifest sha256. Mismatches are NOT copied. The R8 directory is read-only here."""
from __future__ import annotations

import gzip
import json
import shutil
from collections import Counter
from pathlib import Path

from . import config as C
from .store import Store, sha256_bytes


def verify_and_copy(src_root: Path = C.SEED_RAW, store: Store | None = None) -> dict:
    store = store or Store()
    report: dict = {"per_exchange": {}, "mismatch": [], "missing_file": []}
    for ex in C.EXCHANGES:
        mpath = src_root / f"MANIFEST_{ex}.json"
        if not mpath.exists():
            report["per_exchange"][ex] = {"error": "no manifest"}
            continue
        m = json.loads(mpath.read_text(encoding="utf-8"))
        cnt = Counter()
        out: dict = {}
        for day, rec in sorted(m.items()):
            status = rec.get("status")
            if status != "ok":
                out[day] = dict(rec)  # keep the non-stored outcome (404 / empty / http...) as-is
                cnt[f"status:{status}"] += 1
                continue
            src = src_root / ex / f"{day.replace('-', '')}.gz"
            if not src.exists():
                report["missing_file"].append(f"{ex} {day}")
                cnt["missing_file"] += 1
                continue
            body = gzip.decompress(src.read_bytes())
            if sha256_bytes(body) != rec.get("sha256"):
                report["mismatch"].append(f"{ex} {day}")
                cnt["hash_mismatch"] += 1
                continue
            dst = store.raw_path(ex, day)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copyfile(src, dst)
            out[day] = {**rec, "seeded_from": "archive/R8/raw_contract", "seed_verified": True}
            cnt["ok_verified"] += 1
        store._save_manifest(ex, out)
        report["per_exchange"][ex] = dict(cnt)
    return report


if __name__ == "__main__":
    import sys

    print(json.dumps(verify_and_copy(), ensure_ascii=False, indent=1, default=str))
    sys.exit(0)
