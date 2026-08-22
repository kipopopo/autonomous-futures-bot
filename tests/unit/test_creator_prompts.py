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


def test_creator_prompt_spells_out_strategy_value_constraints() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )

    system_prompt = build_creator_proposal_messages(
        request, bundle_hash="a" * 64, symbol="DOGEUSDT"
    )[0]["content"]

    assert "family must be one of" in system_prompt
    assert "regime_gated_breakout" in system_prompt
    assert "range_mean_reversion" in system_prompt
    assert "experimental" in system_prompt
    assert "features must use only" in system_prompt
    assert "rsi" in system_prompt
    assert "shift >= 1" in system_prompt
    assert 'timeframe="5m"' in system_prompt
    assert 'regime_context_timeframe="15m"' in system_prompt


def test_creator_prompt_spells_out_json_field_shapes() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )

    system_prompt = build_creator_proposal_messages(
        request, bundle_hash="a" * 64, symbol="DOGEUSDT"
    )[0]["content"]

    assert "proposal_id must start with proposal-" in system_prompt
    assert "dsl_version must be the integer 1" in system_prompt
    assert "universe must contain a symbols array" in system_prompt
    assert (
        'entry and exit must each be objects with string keys "long" and "short"' in system_prompt
    )


def test_creator_prompt_spells_out_condition_and_veto_types() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )

    system_prompt = build_creator_proposal_messages(
        request, bundle_hash="a" * 64, symbol="DOGEUSDT"
    )[0]["content"]

    assert "entry.long and entry.short must be strings" in system_prompt
    assert "exit.long and exit.short must be strings" in system_prompt
    assert "vetoes must be a non-empty array of strings" in system_prompt


def test_creator_prompt_uses_cached_evaluator_feature_capability() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )

    system_prompt = build_creator_proposal_messages(
        request, bundle_hash="a" * 64, symbol="DOGEUSDT"
    )[0]["content"]

    assert "features must use only" in system_prompt
    assert "relative_volume" not in system_prompt
    assert "rsi" in system_prompt


def test_creator_prompt_spells_out_signal_expression_grammar() -> None:
    request = CreatorGenerationRequest(
        research_run_id="run-prompt-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )

    system_prompt = build_creator_proposal_messages(
        request, bundle_hash="a" * 64, symbol="DOGEUSDT"
    )[0]["content"]

    assert "each condition must be feature_name operator numeric_threshold" in system_prompt
    assert "join conditions only with and or" in system_prompt
    assert "feature-to-feature comparisons are not allowed" in system_prompt
