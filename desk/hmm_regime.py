# -*- coding: utf-8 -*-
"""3-state Gaussian HMM on daily returns.

States are labeled after the fit by the emission mean: highest mean is 偏多,
lowest is 偏空, the middle mean is 震荡. The day's state is the forward-filter
mode, so it does not use later returns. Emission and transition parameters are
estimated on the whole sample.

Uses hmmlearn when that import works. Otherwise a small numpy EM.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

LABELS = ("偏空", "震荡", "偏多")
SIGNS = (-1, 0, 1)
MIN_RETURNS = 79  # 80 closes produce 79 returns


def _clean(returns) -> np.ndarray | None:
    arr = np.asarray(list(returns), dtype=float).reshape(-1)
    arr = arr[np.isfinite(arr)]
    if arr.size < MIN_RETURNS:
        return None
    if float(np.std(arr)) < 1e-12:
        return None
    return arr


def _logsumexp(a: np.ndarray, axis: int) -> np.ndarray:
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    total = np.exp(a - m).sum(axis=axis, keepdims=True)
    out = np.log(np.clip(total, 1e-300, None)) + m
    return np.squeeze(out, axis=axis)


def _log_emit(x: np.ndarray, means: np.ndarray, var: np.ndarray) -> np.ndarray:
    var = np.maximum(var, 1e-8)
    return -0.5 * (
        math.log(2.0 * math.pi) + np.log(var) + (x[:, None] - means) ** 2 / var
    )


def _forward(x, means, var, trans, start) -> np.ndarray:
    """Filtered probabilities, shape (T, K), same state order as ``means``."""
    log_b = _log_emit(x, means, var)
    log_a = np.log(np.clip(trans, 1e-12, None))
    log_pi = np.log(np.clip(start, 1e-12, None))
    t_len, k_len = log_b.shape
    alpha = np.empty((t_len, k_len))
    alpha[0] = log_pi + log_b[0]
    for t in range(1, t_len):
        alpha[t] = log_b[t] + _logsumexp(alpha[t - 1][:, None] + log_a, axis=0)
    return np.exp(alpha - _logsumexp(alpha, axis=1)[:, None])


def _pack(means, filtered, backend: str, note: str) -> dict[str, Any]:
    means = np.asarray(means, dtype=float).reshape(-1)
    filtered = np.asarray(filtered, dtype=float)
    if means.shape[0] != 3 or filtered.ndim != 2 or filtered.shape[1] != 3:
        return {"ok": False, "reason": "状态数异常", "backend": backend, "backend_note": note}
    if not np.isfinite(means).all() or not np.isfinite(filtered).all():
        return {"ok": False, "reason": "拟合无效", "backend": backend, "backend_note": note}
    order = np.argsort(means, kind="mergesort")
    means = means[order]
    filtered = np.clip(filtered[:, order], 0.0, None)
    denom = filtered.sum(axis=1, keepdims=True)
    denom[denom <= 0] = 1.0
    filtered = filtered / denom
    latest_i = int(np.argmax(filtered[-1]))
    labels = [LABELS[int(np.argmax(filtered[t]))] for t in range(len(filtered))]
    signs = [SIGNS[int(np.argmax(filtered[t]))] for t in range(len(filtered))]
    return {
        "ok": True,
        "backend": backend,
        "backend_note": note,
        "latest": LABELS[latest_i],
        "proba": {LABELS[i]: round(float(filtered[-1, i]), 4) for i in range(3)},
        "means": {LABELS[i]: float(means[i]) for i in range(3)},
        "labels": labels,
        "signs": signs,
        "n": int(len(filtered)),
    }


def _fit_numpy(x: np.ndarray) -> dict[str, Any]:
    q1, q2 = np.quantile(x, [1.0 / 3.0, 2.0 / 3.0])
    masks = (x < q1, (x >= q1) & (x < q2), x >= q2)
    means = np.zeros(3)
    var = np.zeros(3)
    floor = max(1e-8, float(np.var(x)) * 1e-4)
    for k, mask in enumerate(masks):
        chunk = x[mask] if int(mask.sum()) >= 2 else x
        means[k] = float(chunk.mean())
        var[k] = max(float(chunk.var()), floor)
    trans = np.full((3, 3), 0.1)
    np.fill_diagonal(trans, 0.8)
    start = np.full(3, 1.0 / 3.0)
    prev_ll = -np.inf
    for _ in range(30):
        log_b = _log_emit(x, means, var)
        log_a = np.log(np.clip(trans, 1e-12, None))
        log_pi = np.log(np.clip(start, 1e-12, None))
        t_len, k_len = log_b.shape
        alpha = np.empty((t_len, k_len))
        alpha[0] = log_pi + log_b[0]
        for t in range(1, t_len):
            alpha[t] = log_b[t] + _logsumexp(alpha[t - 1][:, None] + log_a, axis=0)
        ll = float(_logsumexp(alpha[-1][None, :], axis=1)[0])
        if not math.isfinite(ll):
            return {"ok": False, "reason": "拟合无效", "backend": "numpy", "backend_note": ""}
        beta = np.zeros((t_len, k_len))
        for t in range(t_len - 2, -1, -1):
            beta[t] = _logsumexp(log_a + log_b[t + 1][None, :] + beta[t + 1][None, :], axis=1)
        log_gamma = alpha + beta
        log_gamma = log_gamma - _logsumexp(log_gamma, axis=1)[:, None]
        gamma = np.exp(log_gamma)
        log_xi = (
            alpha[:-1, :, None]
            + log_a[None, :, :]
            + log_b[1:, None, :]
            + beta[1:, None, :]
            - ll
        )
        log_xi = log_xi - _logsumexp(log_xi.reshape(t_len - 1, -1), axis=1)[:, None, None]
        xi = np.exp(log_xi)
        start = gamma[0]
        trans = xi.sum(axis=0)
        trans = np.clip(trans, 1e-6, None)
        trans = trans / trans.sum(axis=1, keepdims=True)
        weight = gamma.sum(axis=0) + 1e-8
        means = (gamma * x[:, None]).sum(axis=0) / weight
        var = (gamma * (x[:, None] - means) ** 2).sum(axis=0) / weight
        var = np.maximum(var, floor)
        if abs(ll - prev_ll) < 1e-4:
            break
        prev_ll = ll
    filtered = _forward(x, means, var, trans, start)
    return _pack(means, filtered, "numpy", "")


def _fit_hmmlearn(x: np.ndarray) -> dict[str, Any]:
    from hmmlearn.hmm import GaussianHMM

    model = GaussianHMM(
        n_components=3,
        covariance_type="diag",
        n_iter=40,
        random_state=0,
        tol=1e-3,
        min_covar=1e-6,
    )
    model.fit(x.reshape(-1, 1))
    means = np.asarray(model.means_, dtype=float).reshape(-1)
    cov = getattr(model, "covars_", None)
    if cov is None:
        cov = model.covariances_
    var = np.asarray(cov, dtype=float).reshape(3, -1)[:, 0]
    var = np.maximum(var, 1e-8)
    trans = np.asarray(model.transmat_, dtype=float)
    start = np.asarray(model.startprob_, dtype=float)
    filtered = _forward(x, means, var, trans, start)
    return _pack(means, filtered, "hmmlearn", "hmmlearn")


def fit_hmm(returns) -> dict[str, Any]:
    """Fit a 3-state Gaussian HMM. ``returns`` are decimal daily returns."""
    x = _clean(returns)
    if x is None:
        return {
            "ok": False,
            "reason": "无足够日线",
            "backend": "",
            "backend_note": "",
            "latest": "无足够日线",
            "proba": {},
            "means": {},
            "labels": [],
            "signs": [],
            "n": 0,
        }
    note = ""
    try:
        import hmmlearn.hmm  # noqa: F401

        packed = _fit_hmmlearn(x)
        if packed.get("ok"):
            return packed
        note = str(packed.get("reason") or "hmmlearn 未得到有效状态")
    except ImportError:
        note = "未安装 hmmlearn"
    except Exception:
        note = "hmmlearn 拟合失败"
    packed = _fit_numpy(x)
    if packed.get("ok"):
        packed["backend_note"] = note
        return packed
    packed["backend_note"] = note
    return packed
