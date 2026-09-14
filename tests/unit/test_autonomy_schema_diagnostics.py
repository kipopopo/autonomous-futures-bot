"""Safe schema-diagnostic regressions for autonomous provider intake."""

from __future__ import annotations

from test_autonomy_provider import _requests

from autonomous_futures.research.autonomy_contracts import FailureLearner, ResearchPlanner


def test_failure_learning_schema_diagnostic_exposes_path_and_type_only() -> None:
    learning_request, _ = _requests()

    result = FailureLearner(
        lambda _request: {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": [],
            "recommended_novelty_dimensions": ["entry_logic"],
            "untrusted_secret_value": "must-not-appear",
        }
    ).learn(learning_request)

    assert result.decision == "rejected"
    assert result.schema_diagnostics == ("learned_constraints:too_short",)
    assert "must-not-appear" not in str(result)
    assert result.provider_metadata == {}


def test_research_plan_schema_diagnostic_exposes_path_and_type_only() -> None:
    _, plan_request = _requests()

    result = ResearchPlanner(
        lambda _request: {
            "hypothesis": "A bounded falsifiable hypothesis.",
            "expected_regime": "volatile_trend",
            "strategy_family": "volume_confirmed_momentum",
            "novelty_dimensions": ["entry_logic"],
            "falsification_criteria": [],
            "untrusted_secret_value": "must-not-appear",
        }
    ).plan(plan_request)

    assert result.decision == "rejected"
    assert result.schema_diagnostics == ("falsification_criteria:too_short",)
    assert "must-not-appear" not in str(result)
    assert result.provider_metadata == {}
