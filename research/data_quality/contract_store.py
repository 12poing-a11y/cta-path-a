# -*- coding: utf-8 -*-
"""Injectable source of exact-contract daily bars (R7a-D).

Everything that prices a month contract (``main_map``, ``adjusted``, ``rolls``, the position
engine's held-contract bars, the daily report) reads through a :class:`ContractStore`:

* :class:`CacheContractStore` — the local cache under ``root`` (``.cache/contracts`` first, then the
  gamma-wall raw dump and Sina day folders), i.e. the pre-R7a behaviour;
* :class:`BundleContractStore` — the contract bundle frozen next to an input snapshot
  (``{contract: [bar, ...]}``), so replays and tests need no local cache.

Both can be cut at a day (``with_cutoff``): bars dated after the cutoff are invisible.  Per-contract
memos live on the store (bundles) or are keyed by ``(root, contract, mtime)`` (cache), so two stores
never share rows.  ``resolve_store(x)`` accepts ``None`` / a root path / a store, which lets every
existing ``root=`` / ``contract_root=`` argument carry a store unchanged.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]

BUNDLE_SCHEMA = "cta-contract-bundle-v1"

_CACHE_MEMO: dict[tuple[str, str, int], dict[str, dict]] = {}


def _cut(by: dict[str, dict], cutoff: str | None) -> dict[str, dict]:
    if cutoff is None:
        return by
    return {d: b for d, b in by.items() if d <= cutoff}


class ContractStore:
    """Read-only exact-contract daily bars, optionally cut at ``cutoff`` (inclusive)."""

    kind = "abstract"

    def __init__(self, cutoff: str | None = None) -> None:
        self.cutoff = str(cutoff)[:10] if cutoff else None
        self._cut_memo: dict[str, dict[str, dict]] = {}

    # -- to implement ---------------------------------------------------------------
    def _full_by_date(self, contract: str) -> dict[str, dict]:
        raise NotImplementedError

    def _clone(self, cutoff: str | None) -> "ContractStore":
        raise NotImplementedError

    def known_contracts(self) -> list[str] | None:
        """Contract ids the store can enumerate (``None`` when it cannot)."""
        return None

    # -- public ---------------------------------------------------------------------
    def by_date(self, contract: str) -> dict[str, dict]:
        contract = str(contract or "").upper()
        if not contract:
            return {}
        full = self._full_by_date(contract)
        if self.cutoff is None:
            return full
        hit = self._cut_memo.get(contract)
        if hit is None or hit.get("__src__") is not full:
            hit = {"__src__": full, "rows": _cut(full, self.cutoff)}
            self._cut_memo[contract] = hit
        return hit["rows"]

    def bars(self, contract: str) -> list[dict]:
        by = self.by_date(contract)
        return [by[k] for k in sorted(by)]

    def with_cutoff(self, cutoff: str | None) -> "ContractStore":
        c = str(cutoff)[:10] if cutoff else None
        if self.cutoff is not None and (c is None or c > self.cutoff):
            c = self.cutoff
        return self._clone(c)

    @property
    def cache_root(self) -> Path | None:
        """Writable cache root (only the cache store can be filled by a fetch)."""
        return None


class CacheContractStore(ContractStore):
    kind = "cache"

    def __init__(self, root: Path | str | None = None, cutoff: str | None = None) -> None:
        super().__init__(cutoff)
        self.root = Path(root or ROOT)

    def _full_by_date(self, contract: str) -> dict[str, dict]:
        stable = self.root / ".cache" / "contracts" / f"{contract}.json"
        try:
            mt = stable.stat().st_mtime_ns if stable.is_file() else 0
        except OSError:
            mt = 0
        key = (str(self.root), contract, mt)
        hit = _CACHE_MEMO.get(key)
        if hit is not None:
            return hit
        try:
            from research.execution.contract_pack import load_exact_contract_daily

            rows = load_exact_contract_daily(contract, root=self.root)
        except Exception:  # noqa: BLE001
            rows = []
        by = {str(b["date"])[:10]: b for b in rows}
        _CACHE_MEMO[key] = by
        return by

    def _clone(self, cutoff: str | None) -> "CacheContractStore":
        return CacheContractStore(self.root, cutoff)

    def known_contracts(self) -> list[str]:
        d = self.root / ".cache" / "contracts"
        return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []

    @property
    def cache_root(self) -> Path:
        return self.root

    def __repr__(self) -> str:
        return f"CacheContractStore({self.root}, cutoff={self.cutoff})"


class BundleContractStore(ContractStore):
    kind = "bundle"

    def __init__(
        self,
        bars: dict[str, Iterable[dict]],
        cutoff: str | None = None,
        *,
        meta: dict[str, Any] | None = None,
        _by: dict[str, dict[str, dict]] | None = None,
    ) -> None:
        super().__init__(cutoff)
        self.meta = dict(meta or {})
        if _by is None:
            _by = {}
            for c, rows in (bars or {}).items():
                by: dict[str, dict] = {}
                for b in rows or []:
                    if isinstance(b, dict) and b.get("date"):
                        d = str(b["date"])[:10]
                        by[d] = dict(b, date=d)
                _by[str(c).upper()] = {k: by[k] for k in sorted(by)}
        self._by = _by

    def _full_by_date(self, contract: str) -> dict[str, dict]:
        return self._by.get(contract) or {}

    def _clone(self, cutoff: str | None) -> "BundleContractStore":
        return BundleContractStore({}, cutoff, meta=self.meta, _by=self._by)

    def known_contracts(self) -> list[str]:
        return sorted(self._by)

    def __repr__(self) -> str:
        return f"BundleContractStore({len(self._by)} contracts, cutoff={self.cutoff})"


def resolve_store(x: Any = None) -> ContractStore:
    if isinstance(x, ContractStore):
        return x
    return CacheContractStore(Path(x) if x else ROOT)


def store_root(x: Any, default: Path | None = None) -> Path:
    """Filesystem root behind ``x`` for NON-contract reads (minute bars, calendars, ...)."""
    if isinstance(x, ContractStore):
        return x.cache_root or Path(default or ROOT)
    return Path(x) if x else Path(default or ROOT)


# ------------------------------------------------------------------ bundle files
def build_bundle(store: ContractStore, contracts: Iterable[str], *, end: str | None = None,
                 meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """``{schema, end, meta, contracts: {id: [bars <= end]}}`` for ``contracts`` (empty ones dropped)."""
    view = store.with_cutoff(end) if end else store
    out: dict[str, list[dict]] = {}
    missing: list[str] = []
    for c in sorted({str(c).upper() for c in contracts}):
        rows = view.bars(c)
        if rows:
            out[c] = [
                {k: b[k] for k in ("date", "open", "high", "low", "close", "volume") if k in b}
                for b in rows
            ]
        else:
            missing.append(c)
    return {
        "schema": BUNDLE_SCHEMA,
        "end": str(end)[:10] if end else None,
        "meta": dict(meta or {}),
        "n_contracts": len(out),
        "n_bars": sum(len(v) for v in out.values()),
        "missing_contracts": missing,
        "contracts": out,
    }


def write_bundle(bundle: dict[str, Any], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(blob, mtime=0))
    else:
        path.write_bytes(blob)
    return path


def load_bundle(path: Path | str, cutoff: str | None = None) -> BundleContractStore:
    path = Path(path)
    blob = path.read_bytes()
    if path.suffix == ".gz":
        blob = gzip.decompress(blob)
    obj = json.loads(blob.decode("utf-8"))
    meta = {k: v for k, v in obj.items() if k != "contracts"}
    meta["path"] = str(path)
    return BundleContractStore(obj.get("contracts") or {}, cutoff, meta=meta)


def snapshot_store(snap: dict | None, snap_path: Path | str | None = None) -> BundleContractStore | None:
    """Frozen contract bars of a snapshot: embedded ``contract_bars`` first, then the companion file."""
    cb = (snap or {}).get("contract_bars")
    if isinstance(cb, dict) and isinstance(cb.get("contracts"), dict):
        meta = {k: v for k, v in cb.items() if k != "contracts"}
        meta["path"] = f"{snap_path}#contract_bars" if snap_path else "embedded"
        return BundleContractStore(cb["contracts"], meta=meta)
    if snap_path is not None:
        q = bundle_path_for(snap_path)
        if q is not None:
            return load_bundle(q)
    return None


def bundle_path_for(snapshot_path: Path | str) -> Path | None:
    """Companion bundle of ``bt_input_*.json``: ``*.contracts.json`` or ``*.contracts.json.gz``."""
    p = Path(snapshot_path)
    stem = p.name[: -len(".json")] if p.name.endswith(".json") else p.name
    for name in (f"{stem}.contracts.json", f"{stem}.contracts.json.gz"):
        q = p.with_name(name)
        if q.is_file():
            return q
    return None
