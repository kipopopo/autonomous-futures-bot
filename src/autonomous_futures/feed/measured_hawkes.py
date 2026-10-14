"""Fit a nonnegative exponential Hawkes branching matrix from recorded trade arrivals.

Likelihood follows the point-process compensator formulation. Beta is an explicit
model parameter; baseline and excitation are fitted rather than simulated regimes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from itertools import groupby
from typing import Any

import numpy as np

Array = np.ndarray[Any, Any]
BASELINE_LOWER_BOUND = 1e-9


@dataclasses.dataclass(frozen=True)
class Arrival:
    symbol: str
    timestamp_ms: int
    aggregate_id: int


@dataclasses.dataclass(frozen=True)
class HawkesFit:
    symbols: tuple[str, ...]
    first_ms: int
    last_ms: int
    counts: tuple[int, ...]
    beta: float
    baseline: tuple[float, ...]
    branching: tuple[tuple[float, ...], ...]
    spectral_radius: float
    log_likelihood: float
    arrivals_sha256: str
    baseline_boundary_symbols: tuple[str, ...]


def likelihood(theta: Array, features: Array, integrals: Array) -> tuple[float, Array, Array]:
    intensity = features @ theta
    if np.any(intensity <= 0) or not np.all(np.isfinite(intensity)):
        raise ValueError("Invalid fitted intensity")
    objective = float(theta @ integrals - np.log(intensity).sum())
    gradient = integrals - features.T @ (1 / intensity)
    hessian = (features.T / intensity**2) @ features
    return objective, gradient, hessian


def solve_row(features: Array, integrals: Array, duration: float) -> tuple[Array, float]:
    theta = np.zeros(features.shape[1], dtype=float)
    theta[0] = len(features) / duration
    lower = np.zeros_like(theta)
    lower[0] = BASELINE_LOWER_BOUND
    for _ in range(250):
        objective, gradient, hessian = likelihood(theta, features, integrals)
        free = (theta > lower + 1e-10) | (gradient < 0)
        projected_gradient = np.where(free, gradient, 0)
        if float(np.max(np.abs(projected_gradient))) < 1e-5:
            return theta, -objective
        direction = np.zeros_like(theta)
        curvature = hessian[np.ix_(free, free)] + np.eye(int(free.sum())) * 1e-9
        direction[free] = -np.linalg.solve(curvature, gradient[free])
        if gradient @ direction >= 0:
            direction = -projected_gradient
        accepted = False
        scale = 1.0
        for _ in range(60):
            proposed = np.maximum(lower, theta + scale * direction)
            delta = proposed - theta
            candidate, _, _ = likelihood(proposed, features, integrals)
            if candidate <= objective + 1e-4 * float(gradient @ delta):
                theta = proposed
                accepted = True
                break
            scale *= 0.5
        if not accepted:
            raise ValueError("Hawkes likelihood line search failed")
    raise ValueError("Hawkes fit did not converge; no risk measurement available")


def fit_arrivals(
    arrivals: list[Arrival],
    symbols: tuple[str, ...],
    *,
    beta: float = 1.0,
    burn_in_ms: int = 30_000,
    minimum_fit_ms: int = 60_000,
    minimum_events: int = 30,
) -> HawkesFit:
    if not symbols or len(set(symbols)) != len(symbols) or not np.isfinite(beta) or beta <= 0:
        raise ValueError("Invalid Hawkes model configuration")
    if not arrivals or minimum_events < 1 or burn_in_ms < 0 or minimum_fit_ms <= 0:
        raise ValueError("Insufficient trade-arrival warmup")
    ordered = sorted(arrivals, key=lambda a: (a.timestamp_ms, a.symbol, a.aggregate_id))
    if len({(a.symbol, a.aggregate_id) for a in ordered}) != len(ordered):
        raise ValueError("Duplicate arrivals cannot qualify the model")
    indices = {symbol: i for i, symbol in enumerate(symbols)}
    if any(a.symbol not in indices or a.timestamp_ms <= 0 or a.aggregate_id < 0 for a in ordered):
        raise ValueError("Invalid trade arrival")
    origin = ordered[0].timestamp_ms
    start_ms, end_ms = origin + burn_in_ms, ordered[-1].timestamp_ms
    if end_ms - start_ms < minimum_fit_ms:
        raise ValueError("Insufficient trade-arrival warmup")
    duration = (end_ms - start_ms) / 1000
    rows: list[list[Array]] = [[] for _ in symbols]
    state = np.zeros(len(symbols))
    integrals = np.zeros(len(symbols) + 1)
    integrals[0] = duration
    prior_ms = origin
    for timestamp, group in groupby(ordered, key=lambda a: a.timestamp_ms):
        simultaneous = list(group)
        state *= np.exp(-beta * ((timestamp - prior_ms) / 1000))
        if timestamp >= start_ms:
            feature = np.concatenate(([1.0], state))
            for arrival in simultaneous:
                rows[indices[arrival.symbol]].append(feature.copy())
        for arrival in simultaneous:
            # Same-millisecond arrivals use pre-group history, avoiding artificial causality.
            dimension = indices[arrival.symbol]
            lower_seconds = max(0, (start_ms - timestamp) / 1000)
            upper_seconds = (end_ms - timestamp) / 1000
            integrals[dimension + 1] += (
                np.exp(-beta * lower_seconds) - np.exp(-beta * upper_seconds)
            ) / beta
            state[dimension] += 1
        prior_ms = timestamp
    counts = tuple(len(row) for row in rows)
    required_events = minimum_events * (len(symbols) + 1)
    if min(counts) < required_events:
        observed_counts = ", ".join(
            f"{symbol}={count}" for symbol, count in zip(symbols, counts, strict=True)
        )
        raise ValueError(
            f"Every model dimension needs at least {required_events} observed arrivals "
            f"for {len(symbols) + 1} fitted coefficients; observed counts: {observed_counts}"
        )
    parameters, total_likelihood = [], 0.0
    for row in rows:
        theta, log_likelihood = solve_row(np.asarray(row), integrals, duration)
        parameters.append(theta)
        total_likelihood += log_likelihood
    fitted = np.asarray(parameters)
    gamma = fitted[:, 1:] / beta
    radius = float(np.max(np.abs(np.linalg.eigvals(gamma))))
    if not np.isfinite(radius):
        raise ValueError("Non-finite Hawkes branching measurement")
    boundary_symbols = tuple(
        symbol
        for symbol, row in zip(symbols, fitted, strict=True)
        if row[0] <= BASELINE_LOWER_BOUND * 1.001
    )
    trace = json.dumps([dataclasses.asdict(a) for a in ordered], sort_keys=True).encode()
    return HawkesFit(
        symbols,
        start_ms,
        end_ms,
        counts,
        beta,
        tuple(float(x) for x in fitted[:, 0]),
        tuple(tuple(float(x) for x in row) for row in gamma),
        radius,
        total_likelihood,
        hashlib.sha256(trace).hexdigest(),
        boundary_symbols,
    )
