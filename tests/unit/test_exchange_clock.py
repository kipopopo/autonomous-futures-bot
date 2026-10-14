import pytest

from autonomous_futures.feed.exchange_clock import ExchangeClock


def test_observed_offset_corrects_age_with_conservative_uncertainty():
    clock = ExchangeClock(1000, 1200, 1700)
    assert clock.offset_ms == 600
    assert clock.aligned_ms(1300) == 1900
    assert clock.event_fresh(1700, 1300)
    assert not clock.event_fresh(1400, 1300)
    assert not clock.event_fresh(2101, 1300)


def test_stable_1350ms_local_skew_is_corrected_without_relaxing_freshness():
    clock = ExchangeClock(1000, 1100, 2400)
    assert clock.offset_ms == 1350
    assert clock.uncertainty_ms == 50
    assert clock.aligned_ms(1200) == 2550
    assert clock.event_fresh(2150, 1200)
    assert not clock.event_fresh(2050, 1200)

    negative = ExchangeClock(10_000, 10_100, 8700)
    assert negative.offset_ms == -1350
    assert negative.aligned_ms(10_200) == 8850
    assert negative.event_fresh(8450, 10_200)
    assert not negative.event_fresh(8350, 10_200)


def test_clock_does_not_silently_accept_excessive_latency_skew_or_age():
    with pytest.raises(ValueError):
        ExchangeClock(1000, 1600, 1300)
    with pytest.raises(ValueError):
        ExchangeClock(1000, 1100, 3300)
    with pytest.raises(ValueError):
        ExchangeClock(1000, 1100, 1050).aligned_ms(181101)


def test_uncertain_minute_boundary_cannot_expose_a_forming_candle():
    clock = ExchangeClock(59800, 60000, 59900)
    # Midpoint time is past close, but earliest exchange time still precedes it.
    assert clock.completed_boundary(60100, 60000) == 60000
    assert clock.completed_boundary(60099, 60000) == 0
    assert clock.completed_boundary(60101, 60000) == 60000
    with pytest.raises(ValueError, match="interval"):
        clock.completed_boundary(60100, 0)
