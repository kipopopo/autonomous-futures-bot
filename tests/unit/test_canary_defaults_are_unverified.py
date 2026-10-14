from autonomous_futures.api.canary import (
    CanaryAutoEvolutionResponse,
    LiveEvolutionProgressItem,
    MacroGatingStateItem,
    OOSQualificationGateItem,
    _build_macro_gating_state,
)


def test_canary_response_defaults_do_not_claim_verified_evidence() -> None:
    response = CanaryAutoEvolutionResponse()

    assert response.verified is False
    assert response.status == "UNVERIFIED"
    assert response.paper_safe is False
    assert response.timestamp_ms is None
    assert response.circuit_state == "UNKNOWN"
    assert response.candidates == []
    assert response.live_progress is None
    assert response.solvency.starting_equity_usdt is None
    assert response.solvency.zero_balance_drift_verified is None
    assert response.ledger.starting_equity is None
    assert response.ledger.zero_balance_drift is None


def test_default_live_progress_contains_no_fabricated_runtime_values() -> None:
    progress = LiveEvolutionProgressItem()

    assert progress.is_live_daemon_active is None
    assert progress.daemon_pid is None
    assert progress.daemon_status == "UNKNOWN"
    assert progress.current_cycle_stage == "UNKNOWN"
    assert progress.cycle_progress_pct is None
    assert progress.heartbeat_latency_ms is None
    assert progress.scanned_symbols == []
    assert progress.oos_gate.samples_required is None
    assert progress.oos_gate.samples_acquired is None
    assert progress.oos_gate.sharpe_hurdle_pct is None


def test_missing_macro_telemetry_fails_closed_without_invented_prices() -> None:
    state = MacroGatingStateItem()
    built = _build_macro_gating_state()

    for candidate in (state, built):
        assert candidate.regime == "UNKNOWN"
        assert candidate.longs_filtered is True
        assert candidate.is_long_allowed is False
        assert candidate.btc_price is None
        assert candidate.ema50_1h is None
        assert candidate.ema200_1h is None


def test_default_oos_gate_does_not_claim_a_qualification_threshold() -> None:
    gate = OOSQualificationGateItem()

    assert gate.status == "UNKNOWN"
    assert gate.samples_required is None
    assert gate.samples_acquired is None
    assert gate.sharpe_hurdle_pct is None
    assert gate.current_sharpe_improvement_pct is None
