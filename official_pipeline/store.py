# -*- coding: utf-8 -*-
"""Raw-response store: write-once per (exchange, day); changed content goes to revisions/ and never overwrites."""
from __future__ import annotations

import difflib
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config as C


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Store:
    def __init__(self, raw_root: Path | None = None, revisions_root: Path | None = None):
        self.raw = Path(raw_root or C.RAW)
        self.revisions = Path(revisions_root or C.REVISIONS)

    # ---- paths -------------------------------------------------------------------------------------------------------
    @staticmethod
    def ymd(day: str) -> str:
        return day.replace("-", "")

    def manifest_path(self, ex: str) -> Path:
        return self.raw / f"MANIFEST_{ex}.json"

    def raw_path(self, ex: str, day: str) -> Path:
        return self.raw / ex / f"{self.ymd(day)}.gz"

    # ---- manifest ----------------------------------------------------------------------------------------------------
    def load_manifest(self, ex: str) -> dict:
        p = self.manifest_path(ex)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _save_manifest(self, ex: str, m: dict) -> None:
        _atomic_write(self.manifest_path(ex), json.dumps(m, ensure_ascii=False, sort_keys=True, indent=0).encode("utf-8"))

    def status(self, ex: str, day: str) -> str | None:
        return (self.load_manifest(ex).get(day) or {}).get("status")

    def is_stored(self, ex: str, day: str) -> bool:
        return self.status(ex, day) == "ok"

    # ---- writes ------------------------------------------------------------------------------------------------------
    def record_failure(self, ex: str, day: str, status: str, url: str = "", error: str = "") -> None:
        """Failed or not-yet-available attempt. Never downgrades a stored day."""
        m = self.load_manifest(ex)
        prev = m.get(day) or {}
        if prev.get("status") == "ok":
            prev["last_attempt_utc"] = utc_now()
            prev["attempts"] = int(prev.get("attempts", 1)) + 1
            m[day] = prev
        else:
            m[day] = {**prev, "status": status, "url": url or prev.get("url", ""), "error": error[:200],
                      "last_attempt_utc": utc_now(), "attempts": int(prev.get("attempts", 0)) + 1,
                      "first_attempt_utc": prev.get("first_attempt_utc") or utc_now()}
        self._save_manifest(ex, m)

    def put(self, ex: str, day: str, body: bytes, url: str = "", meta: dict | None = None) -> str:
        """Store a successfully fetched body. Returns 'new' | 'unchanged' | 'revision'."""
        m = self.load_manifest(ex)
        sha = sha256_bytes(body)
        prev = m.get(day) or {}
        now = utc_now()
        if prev.get("status") == "ok":
            if prev.get("sha256") == sha:
                prev["last_attempt_utc"] = now
                prev["attempts"] = int(prev.get("attempts", 1)) + 1
                m[day] = prev
                self._save_manifest(ex, m)
                return "unchanged"
            self._write_revision(ex, day, body, sha, prev, now)
            prev["revision_pending"] = True
            prev["revision_sha256"] = sha
            prev["last_attempt_utc"] = now
            m[day] = prev
            self._save_manifest(ex, m)
            return "revision"
        _atomic_write(self.raw_path(ex, day), gzip.compress(body, 6))
        m[day] = {"status": "ok", "bytes": len(body), "sha256": sha, "url": url, "fetched_utc": now,
                  "first_attempt_utc": prev.get("first_attempt_utc") or now, "last_attempt_utc": now,
                  "attempts": int(prev.get("attempts", 0)) + 1, **(meta or {})}
        self._save_manifest(ex, m)
        return "new"

    def _write_revision(self, ex: str, day: str, body: bytes, sha: str, prev: dict, now: str) -> None:
        old = gzip.decompress(self.raw_path(ex, day).read_bytes()) if self.raw_path(ex, day).exists() else b""
        d = self.revisions / ex / self.ymd(day)
        stamp = now.replace(":", "").replace("-", "")
        _atomic_write(d / f"{stamp}_{sha[:12]}.gz", gzip.compress(body, 6))
        diff = "\n".join(difflib.unified_diff(old.decode("utf-8", "replace").splitlines(), body.decode("utf-8", "replace").splitlines(),
                                              "stored", "revision", lineterm="", n=0))
        _atomic_write(d / f"{stamp}_{sha[:12]}.diff.txt", diff.encode("utf-8")[:2_000_000])

    # ---- reads -------------------------------------------------------------------------------------------------------
    def read_body(self, ex: str, day: str) -> bytes:
        return gzip.decompress(self.raw_path(ex, day).read_bytes())

    def stored_days(self, ex: str) -> list[str]:
        return sorted(d for d, r in self.load_manifest(ex).items() if r.get("status") == "ok")

    def revision_days(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for ex in C.EXCHANGES:
            for d, r in self.load_manifest(ex).items():
                if r.get("revision_pending"):
                    out.setdefault(ex, []).append(d)
        return out
