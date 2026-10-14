import asyncio
from decimal import Decimal

import pytest

from autonomous_futures.feed import runtime_microstructure as runtime_module
from autonomous_futures.feed.measured_hawkes import Arrival, HawkesFit
from autonomous_futures.feed.runtime_hawkes_calibration import RuntimeHawkesCalibration
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure

CALIBRATION = RuntimeHawkesCalibration(1.0, "a" * 64, ("b" * 64,), ("SOLUSDT",))


def trade(identity, now=1000000):
    return {"e": "aggTrade", "s": "SOLUSDT", "a": identity, "E": now, "T": now}


def depth(update, previous=None, now=1000000, bid="99", ask="101"):
    data = {
        "e": "depthUpdate",
        "s": "SOLUSDT",
        "u": update,
        "E": now,
        "b": [[bid, "1"]],
        "a": [[ask, "1"]],
    }
    if previous is not None:
        data["pu"] = previous
    return data


def test_uncalibrated_feed_never_supplies_preset_radius():
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    assert monitor.calibration_window_ms == 1_800_000
    monitor.ingest(trade(1), 1000000)
    monitor.ingest(depth(1), 1000000)
    with pytest.raises(ValueError, match="genuine warmup"):
        monitor.evidence("SOLUSDT", 1000000)


def test_runtime_fit_uses_hash_bound_empirical_beta(monkeypatch):
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    monitor.arrivals.append(Arrival("SOLUSDT", 1_000_000, 1))
    observed = {}

    def fit(sample, symbols, *, beta):
        observed["beta"] = beta
        return HawkesFit(
            symbols=symbols,
            first_ms=940_000,
            last_ms=1_000_000,
            counts=(1,),
            beta=beta,
            baseline=(1.0,),
            branching=((0.2,),),
            spectral_radius=0.2,
            log_likelihood=-1.0,
            arrivals_sha256="c" * 64,
            baseline_boundary_symbols=(),
        )

    monkeypatch.setattr(runtime_module, "fit_arrivals", fit)
    asyncio.run(monitor.calibrate())
    assert observed["beta"] == CALIBRATION.beta_per_second
    assert monitor.fit is not None and monitor.fit.beta == CALIBRATION.beta_per_second


def test_entry_evidence_attests_the_fit_parameter_and_calibration():
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    monitor.trade_times["SOLUSDT"] = 1_000_000
    monitor.quotes["SOLUSDT"] = (1_000_000, Decimal("99"), Decimal("101"))
    monitor.fit = HawkesFit(
        symbols=("SOLUSDT",),
        first_ms=940_000,
        last_ms=1_000_000,
        counts=(100,),
        beta=CALIBRATION.beta_per_second,
        baseline=(1.0,),
        branching=((0.2,),),
        spectral_radius=0.2,
        log_likelihood=-1.0,
        arrivals_sha256="c" * 64,
        baseline_boundary_symbols=(),
    )
    evidence = monitor.evidence("SOLUSDT", 1_000_000)
    evidence.validate(1_000_000)
    assert evidence.beta_per_second == Decimal("1.0")
    assert evidence.calibration_sha256 == CALIBRATION.artifact_sha256


def test_calibration_window_retains_configured_market_history_and_trims_expired_events():
    monitor = RuntimeMicrostructure(
        ("SOLUSDT",), calibration=CALIBRATION, calibration_window_ms=900_000
    )
    monitor.ingest(trade(1, 1_000_000), 1_000_000)
    monitor.ingest(trade(2, 1_600_000), 1_600_000)
    assert [arrival.aggregate_id for arrival in monitor.arrivals] == [1, 2]

    short = RuntimeMicrostructure(
        ("SOLUSDT",), calibration=CALIBRATION, calibration_window_ms=120_000
    )
    short.ingest(trade(1, 1_000_000), 1_000_000)
    short.ingest(trade(2, 1_120_001), 1_120_001)
    assert [arrival.aggregate_id for arrival in short.arrivals] == [2]


@pytest.mark.parametrize("window_ms", [True, 90_000, 3_600_001, "900000"])
def test_calibration_window_rejects_invalid_fit_horizons(window_ms):
    with pytest.raises(ValueError, match="Calibration window"):
        RuntimeMicrostructure(
            ("SOLUSDT",), calibration=CALIBRATION, calibration_window_ms=window_ms
        )


def test_boundary_pinned_hawkes_baseline_cannot_grant_entry_evidence():
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    monitor.trade_times["SOLUSDT"] = 1000000
    monitor.quotes["SOLUSDT"] = (1000000, Decimal("99"), Decimal("101"))
    monitor.fit = HawkesFit(
        symbols=("SOLUSDT",),
        first_ms=940000,
        last_ms=1000000,
        counts=(100,),
        beta=1.0,
        baseline=(1e-9,),
        branching=((0.8,),),
        spectral_radius=0.8,
        log_likelihood=-1.0,
        arrivals_sha256="a" * 64,
        baseline_boundary_symbols=("SOLUSDT",),
    )
    with pytest.raises(ValueError, match="pinned to the optimizer lower bound"):
        monitor.evidence("SOLUSDT", 1000000)


def test_frames_within_observed_clock_uncertainty_preserve_real_sequence():
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    monitor.ingest(trade(1, 1000012), 1000000, uncertainty_ms=20)
    monitor.ingest(trade(2, 1000015), 1000001, uncertainty_ms=20)
    assert monitor.last_ids["SOLUSDT"] == 2
    assert monitor.gaps == 0
    monitor.ingest(trade(3, 1000100), 1000002, uncertainty_ms=20)
    assert monitor.last_ids["SOLUSDT"] == 2
    with pytest.raises(ValueError):
        monitor.ingest(trade(3), 1000000, uncertainty_ms=251)


def test_trade_gap_invalidates_all_model_and_quote_evidence():
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    monitor.ingest(trade(1), 1000000)
    monitor.ingest(depth(1), 1000000)
    monitor.ingest(trade(3), 1000000)
    assert monitor.gaps == 1
    assert monitor.generation == 1
    assert not monitor.quotes
    assert len(monitor.arrivals) == 1


def test_duplicate_does_not_inflate_sample_and_delayed_history_is_retained():
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    monitor.ingest(trade(1), 1000000)
    monitor.ingest(trade(1), 1000000)
    monitor.ingest(trade(2), 1000501)
    assert len(monitor.arrivals) == 2
    assert monitor.trade_times["SOLUSDT"] == 1000000
    assert monitor.duplicates == 1
    assert monitor.stale == 1


def test_crossed_depth_and_depth_gap_restart_warmup():
    monitor = RuntimeMicrostructure(("SOLUSDT",), calibration=CALIBRATION)
    monitor.ingest(depth(1), 1000000)
    monitor.ingest(depth(3, previous=2), 1000000)
    assert monitor.gaps == 1
    with pytest.raises(ValueError, match="Crossed"):
        monitor.ingest(depth(4, previous=3, bid="101", ask="99"), 1000000)
    assert not monitor.quotes
