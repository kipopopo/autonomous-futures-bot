from decimal import Decimal

import pytest


def test_live_endpoint_allow_list_accepts_production_only() -> None:
    from autonomous_futures.live_boundary import validate_live_rest_url

    assert (
        validate_live_rest_url("https://fapi.binance.com/fapi/v1/account")
        == "https://fapi.binance.com/fapi/v1/account"
    )
    with pytest.raises(ValueError, match="production endpoint"):
        validate_live_rest_url("https://demo-fapi.binance.com/fapi/v1/account")
    with pytest.raises(ValueError, match="production endpoint"):
        validate_live_rest_url("http://fapi.binance.com/fapi/v1/account")


def test_live_gate_blocks_missing_requirements() -> None:
    from autonomous_futures.live_boundary import LiveBoundaryInputs, evaluate_live_boundary

    decision = evaluate_live_boundary(
        LiveBoundaryInputs(
            testnet_evidence_complete=False,
            legal_review_confirmed=False,
            venue_account_confirmed=False,
            secret_manager_ready=False,
            kill_switch_verified=False,
            reconciliation_clean=False,
            symbol_approved=False,
            explicit_live_activation=False,
            live_enabled=False,
            max_quote_notional=Decimal("100"),
        )
    )

    assert decision.status == "blocked"
    assert decision.live_enabled is False
    assert decision.network_allowed is False
    assert "testnet_evidence_incomplete" in decision.reason_codes
    assert "live_activation_not_explicit" in decision.reason_codes


def test_live_gate_is_only_design_eligible_not_activated() -> None:
    from autonomous_futures.live_boundary import LiveBoundaryInputs, evaluate_live_boundary

    decision = evaluate_live_boundary(
        LiveBoundaryInputs(
            testnet_evidence_complete=True,
            legal_review_confirmed=True,
            venue_account_confirmed=True,
            secret_manager_ready=True,
            kill_switch_verified=True,
            reconciliation_clean=True,
            symbol_approved=True,
            explicit_live_activation=True,
            live_enabled=True,
            max_quote_notional=Decimal("100"),
        )
    )

    assert decision.status == "design_eligible"
    assert decision.reason_codes == ("live_design_eligible_not_activated",)
    assert decision.live_enabled is False
    assert decision.network_allowed is False
