from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_protective_lifecycle import PLAN

from autonomous_futures.execution.ict_reclaim_entry import IctReclaimEntryStore
from autonomous_futures.strategy.ict_mmxm import Candle


def candle(timestamp_ms, *, open_, high, low, close):
    return Candle(timestamp_ms, D(open_), D(high), D(low), D(close), D("10"))


def test_reclaim_candidate_is_persisted_and_dispatched_once(tmp_path):
    plan = replace(PLAN, decision_ms=600_000)
    report = tmp_path / "reports" / "ict.json"
    state_path = tmp_path / "runtime" / "ict-reclaim-entry-state.json"
    first = IctReclaimEntryStore(state_path, tmp_path)
    first.begin(plan, report, "a" * 64, entry_ttl_ms=300_000)

    assert (
        first.advance(
            "SOLUSDT",
            (candle(600_000, open_="101", high="103", low="100.5", close="102"),),
            660_000,
            report_path=report,
            report_hash="a" * 64,
            entry_ttl_ms=300_000,
        )
        is None
    )

    resumed = IctReclaimEntryStore(state_path, tmp_path)
    ready = resumed.advance(
        "SOLUSDT",
        (candle(660_000, open_="101", high="103", low="99", close="101"),),
        720_000,
        report_path=report,
        report_hash="a" * 64,
        entry_ttl_ms=300_000,
    )
    assert ready == 720_000
    candidate = resumed.get("SOLUSDT")
    assert candidate is not None
    assert candidate.stage == "DISPATCHED"
    assert candidate.readiness_ms == ready

    after_restart = IctReclaimEntryStore(state_path, tmp_path)
    assert (
        after_restart.advance(
            "SOLUSDT",
            (candle(660_000, open_="101", high="103", low="99", close="101"),),
            720_000,
            report_path=report,
            report_hash="a" * 64,
            entry_ttl_ms=300_000,
        )
        is None
    )


def test_reclaim_candidate_rejects_gaps_and_report_identity_changes(tmp_path):
    plan = replace(PLAN, decision_ms=600_000)
    report = tmp_path / "reports" / "ict.json"
    state_path = tmp_path / "runtime" / "ict-reclaim-entry-state.json"
    store = IctReclaimEntryStore(state_path, tmp_path)
    store.begin(plan, report, "a" * 64, entry_ttl_ms=300_000)

    with pytest.raises(ValueError, match="another reviewed report"):
        store.advance(
            "SOLUSDT",
            (),
            660_000,
            report_path=report,
            report_hash="b" * 64,
            entry_ttl_ms=300_000,
        )

    with pytest.raises(ValueError, match="missing or reordered"):
        store.advance(
            "SOLUSDT",
            (candle(660_000, open_="101", high="103", low="99", close="101"),),
            720_000,
            report_path=report,
            report_hash="a" * 64,
            entry_ttl_ms=300_000,
        )
    assert store.get("SOLUSDT") is None


def test_reclaim_candidate_expires_at_the_qualified_policy_deadline(tmp_path):
    plan = replace(PLAN, decision_ms=600_000)
    report = tmp_path / "reports" / "ict.json"
    state_path = tmp_path / "runtime" / "ict-reclaim-entry-state.json"
    store = IctReclaimEntryStore(state_path, tmp_path)
    store.begin(plan, report, "a" * 64, entry_ttl_ms=300_000)

    assert (
        store.advance(
            "SOLUSDT",
            (),
            900_000,
            report_path=report,
            report_hash="a" * 64,
            entry_ttl_ms=300_000,
        )
        is None
    )
    assert store.get("SOLUSDT") is None
