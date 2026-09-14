"""Prompt-contract regressions for strict learner response types."""

from __future__ import annotations

from test_autonomy_provider import _requests

from autonomous_futures.research.autonomy_prompts import build_failure_learning_messages


def test_failure_learning_prompt_declares_strict_array_and_enum_contract() -> None:
    learning_request, _ = _requests()

    system, _ = build_failure_learning_messages(learning_request)
    content = system["content"]

    assert "JSON arrays of unique strings" in content
    assert "recommended_novelty_dimensions" in content
    assert "entry_logic" in content
    assert "strategy_family" in content
    assert "Do not return objects inside any array" in content
