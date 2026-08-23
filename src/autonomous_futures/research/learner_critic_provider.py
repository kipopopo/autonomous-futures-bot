"""OpenCode transport and prompt contract for the injected Learner/Critic boundary."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .learner_critic import LearnerCriticRequest
from .opencode_provider import OpenCodeJsonClient

_SYSTEM_PROMPT = (
    "Return exactly one JSON object with keys review_id, research_run_id, candidate_id, "
    "decision, failure_reason_codes, and revision_actions. review_id must start with "
    "review-; decision must be revise or stop; failure_reason_codes must exactly preserve "
    "the supplied failed reasons; revision_actions must be a non-empty JSON array of "
    "strings. Example valid shape: "
    '{"review_id": "review-example-001", "research_run_id": "run-example-001", '
    '"candidate_id": "cand-example-001", "decision": "revise", '
    '"failure_reason_codes": ["oos_profit_factor_below_threshold"], '
    '"revision_actions": ["change_entry_threshold"]}. '
    "Do not relax qualification gates. Never return markdown, prose, code, "
    "URLs, secrets, tools, model bytes, or orders."
)


def build_learner_critic_messages(
    request: LearnerCriticRequest,
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    feedback = {
        "candidate_id": request.feedback.candidate_id,
        "qualification_hash": request.feedback.qualification_hash,
        "failure_reason_codes": request.feedback.failure_reason_codes,
        "failed_gates": [
            {
                "gate_id": gate.gate_id,
                "reason_code": gate.reason_code,
                "observed": str(gate.observed) if gate.observed is not None else None,
                "threshold": str(gate.threshold) if gate.threshold is not None else None,
                "comparator": gate.comparator,
            }
            for gate in request.feedback.failed_gates
        ],
    }
    user_prompt = (
        f"research_run_id={request.research_run_id}; candidate_id={request.candidate_id}; "
        f"input_evidence_refs={','.join(request.input_evidence_refs)}; "
        f"failure_feedback={json.dumps(feedback, sort_keys=True, separators=(',', ':'))}. "
        "Produce bounded revision actions for a future Creator attempt."
    )
    return (
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    )


@dataclass(frozen=True, slots=True)
class OpenCodeCriticTransport:
    client: OpenCodeJsonClient
    system_prompt: str
    user_prompt_builder: Callable[[LearnerCriticRequest], str]
    temperature: float = 0.2
    max_output_tokens: int = 4096

    def __call__(self, request: LearnerCriticRequest) -> Mapping[str, object]:
        return self.client.complete_json(
            messages=(
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt_builder(request)},
            ),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


__all__ = ["OpenCodeCriticTransport", "build_learner_critic_messages"]
