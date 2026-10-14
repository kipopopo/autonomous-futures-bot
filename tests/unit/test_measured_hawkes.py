import numpy as np
import pytest

from autonomous_futures.feed.measured_hawkes import Arrival, fit_arrivals, likelihood


def test_likelihood_derivatives_match_finite_differences():
    features = np.array([[1.0, 0.0, 1.0], [1.0, 2.0, 0.1], [1.0, 0.5, 0.9]])
    integrals = np.array([5.0, 3.0, 4.0])
    theta = np.array([0.6, 0.2, 0.3])
    _, gradient, hessian = likelihood(theta, features, integrals)
    for i in range(3):
        offset = np.zeros(3)
        offset[i] = 1e-6
        plus, plus_gradient, _ = likelihood(theta + offset, features, integrals)
        minus, minus_gradient, _ = likelihood(theta - offset, features, integrals)
        assert gradient[i] == pytest.approx((plus - minus) / 2e-6, rel=1e-6)
        np.testing.assert_allclose(
            hessian[:, i], (plus_gradient - minus_gradient) / 2e-6, rtol=1e-6
        )


def clustered_arrivals():
    # Explicit statistical unit fixture; never used by production ingress.
    return [
        Arrival("SOLUSDT", 1000000 + burst * 2000 + event * 50, burst * 4 + event)
        for burst in range(90)
        for event in range(4)
    ]


def test_fit_measures_excitation_and_binds_observed_trace():
    fit = fit_arrivals(clustered_arrivals(), ("SOLUSDT",))
    assert fit.spectral_radius > 0
    assert fit.baseline[0] > 0
    assert fit.branching[0][0] == fit.spectral_radius
    assert len(fit.arrivals_sha256) == 64
    assert fit.counts[0] >= 30
    assert fit.baseline_boundary_symbols == ()


def test_warmup_and_duplicate_arrivals_fail_closed():
    events = clustered_arrivals()
    with pytest.raises(ValueError, match="warmup"):
        fit_arrivals(events[:10], ("SOLUSDT",))
    with pytest.raises(ValueError, match="Duplicate"):
        fit_arrivals(events + [events[0]], ("SOLUSDT",))
    with pytest.raises(ValueError, match="Every model dimension"):
        fit_arrivals(events, ("SOLUSDT", "ETHUSDT"))


def test_multivariate_fit_requires_observations_per_fitted_coefficient():
    symbols = tuple(f"S{index}USDT" for index in range(12))
    events = [
        Arrival(symbol, 1_000_000 + event * 1_000, event)
        for symbol in symbols
        for event in range(100)
    ]
    with pytest.raises(
        ValueError,
        match=r"at least 390 observed arrivals.*observed counts:.*S0USDT=70",
    ):
        fit_arrivals(events, symbols)
