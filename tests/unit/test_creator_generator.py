from __future__ import annotations

from collections.abc import Mapping

from autonomous_futures.research.creator_generator import (
    CreatorGenerationRequest,
    CreatorGenerationResult,
    CreatorGenerator,
)


def _proposal(run_id: str = "run-generator-001") -> dict[str, object]:
    return {
        "proposal_id": "proposal-generator-001",
        "research_run_id": run_id,
        "hypothesis": "Range reversion after RSI extremes",
        "expected_regime": "range",
        "novelty_reason": "Generated for a new evidence scope",
        "strategy": {
            "dsl_version": 1,
            "strategy_id": "cand-generator-001",
            "family": "range_mean_reversion",
            "universe": {
                "symbols": ["DOGEUSDT"],
                "timeframe": "5m",
                "regime_context_timeframe": "15m",
            },
            "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
            "entry": {"long": "rsi <= 30", "short": "rsi >= 70"},
            "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
            "vetoes": ["funding_adverse"],
        },
    }


def _request() -> CreatorGenerationRequest:
    return CreatorGenerationRequest(
        research_run_id="run-generator-001",
        input_evidence_refs=("bundle/hash", "trial/summary"),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )


def test_generator_accepts_valid_fake_transport_and_never_returns_raw_output() -> None:
    received: list[CreatorGenerationRequest] = []

    def transport(request: CreatorGenerationRequest) -> Mapping[str, object]:
        received.append(request)
        return _proposal()

    result = CreatorGenerator(transport=transport).generate(_request())

    assert isinstance(result, CreatorGenerationResult)
    assert result.decision == "accepted"
    assert result.proposal is not None
    assert result.proposal.research_run_id == "run-generator-001"
    assert result.raw_output is None
    assert received == [_request()]
    assert result.exchange_access is False
    assert result.execution_authority is False


def test_generator_rejects_schema_invalid_fake_output_without_candidate() -> None:
    def transport(_: CreatorGenerationRequest) -> Mapping[str, object]:
        return {**_proposal(), "strategy": {"unsafe": True}}

    result = CreatorGenerator(transport=transport).generate(_request())

    assert result.decision == "rejected"
    assert result.proposal is None
    assert result.reason_codes == ("schema_rejected",)


def test_generator_rejects_proposal_from_different_research_run() -> None:
    def transport(_: CreatorGenerationRequest) -> Mapping[str, object]:
        return _proposal("run-other")

    result = CreatorGenerator(transport=transport).generate(_request())

    assert result.decision == "rejected"
    assert result.reason_codes == ("research_run_mismatch",)


def test_generator_converts_transport_failure_to_stable_provider_error() -> None:
    def transport(_: CreatorGenerationRequest) -> Mapping[str, object]:
        raise TimeoutError("do not expose this")

    result = CreatorGenerator(transport=transport).generate(_request())

    assert result.decision == "rejected"
    assert result.reason_codes == ("provider_error",)
    assert result.raw_output is None
