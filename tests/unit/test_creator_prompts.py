from autonomous_futures.research.creator_generator import CreatorGenerationRequest
from autonomous_futures.research.creator_prompts import build_creator_proposal_messages


def test_creator_prompt_contains_exact_schema_and_evidence_scope() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-001",
        input_evidence_refs=("bundle/hash", "registry/hash"),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )

    messages = build_creator_proposal_messages(
        request,
        bundle_hash="a" * 64,
        symbol="DOGEUSDT",
    )

    assert messages[0]["role"] == "system"
    assert "proposal_id" in messages[0]["content"]
    assert "strategy_id" in messages[0]["content"]
    assert "Return exactly one JSON object" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "run-prompt-001" in messages[1]["content"]
    assert "DOGEUSDT" in messages[1]["content"]
    assert "bundle/hash" in messages[1]["content"]
    assert "registry/hash" in messages[1]["content"]


def test_creator_prompt_rejects_unsafe_scope_values() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )

    try:
        build_creator_proposal_messages(request, bundle_hash="not-a-hash", symbol="dogeusdt")
    except ValueError as exc:
        assert "bundle_hash" in str(exc) or "symbol" in str(exc)
    else:
        raise AssertionError("unsafe prompt scope must fail closed")
