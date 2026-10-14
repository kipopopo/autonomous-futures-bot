from decimal import Decimal as D

import pytest

from autonomous_futures.feed.runtime_microstructure import MicrostructureEvidence


@pytest.mark.parametrize("age,accepted", [(-16, True), (-101, False), (400, True), (401, False)])
def test_freshness_uses_observed_uncertainty_and_worst_case_age(age, accepted):
    evidence = MicrostructureEvidence(
        "SOLUSDT",
        1000 - age,
        1000 - age,
        900,
        D(".5"),
        D("99"),
        D("101"),
        1,
        "c" * 64,
        D("1.0"),
        "d" * 64,
    )
    if accepted:
        evidence.validate(1000, uncertainty_ms=100)
    else:
        with pytest.raises(ValueError, match="stale"):
            evidence.validate(1000, uncertainty_ms=100)


def test_clock_uncertainty_never_bypasses_supercriticality():
    evidence = MicrostructureEvidence(
        "SOLUSDT",
        1016,
        1016,
        900,
        D("1.00564"),
        D("99"),
        D("101"),
        1,
        "c" * 64,
        D("1.0"),
        "d" * 64,
    )
    with pytest.raises(ValueError, match="supercritical"):
        evidence.validate(1000, uncertainty_ms=100)
