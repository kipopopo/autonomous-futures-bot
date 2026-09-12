from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .google_ai_studio_provider import GoogleAIStudioJsonClient
from .learner_metric_quality_critic import (
    LearnerMetricQualityCriticRequest,
)

_SYSTEM_PROMPT = (
    "Return exactly one JSON object with keys review_id, critic_run_id, decision_id, "
    "candidate_id, decision, failure_reason_codes, and revision_actions. review_id must "
    "start with review-learner-quality-critic-; decision must be revise or stop; "
    "failure_reason_codes must exactly preserve the supplied failed reasons; "
    "revision_actions must be a non-empty JSON array of unique sorted values selected "
    "only from add_cross_symbol_validation, add_temporal_holdout, change_target_definition, "
    "preserve_causal_features, and stop_baseline. A stop decision must include stop_baseline; "
    "a revise decision must not include stop_baseline. Do not relax quality gates. "
    "Do not suggest promotion, qualification, paper activation, exchange access, live trading, "
    "orders, credentials, or execution authority. Never return markdown, prose, code, URLs, "
    "secrets, tools, or model bytes."
)


def build_learner_metric_quality_critic_messages(
    request: LearnerMetricQualityCriticRequest,
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    failed_gates = [
        {
            "gate_id": gate.gate_id,
            "window_id": gate.window_id,
            "metric_id": gate.metric_id,
            "observed": None if gate.observed is None else str(gate.observed),
            "threshold": str(gate.threshold),
            "comparator": gate.comparator,
            "reason_code": gate.reason_code,
        }
        for gate in request.failed_gates
    ]
    user_prompt = (
        f"critic_run_id={request.critic_run_id}; decision_id={request.decision_id}; "
        f"candidate_id={request.candidate_id}; decision={request.source_decision}; "
        f"input_evidence_refs={','.join(request.input_evidence_refs)}; "
        f"failure_reason_codes={json.dumps(request.failure_reason_codes)}; "
        f"failed_gates={json.dumps(failed_gates, sort_keys=True, separators=(',', ':'))}. "
        "Review the failed learner-quality evidence and return bounded advisory actions only."
    )
    return (
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    )


@dataclass(frozen=True, slots=True)
class GoogleAIStudioLearnerMetricQualityCriticTransport:
    client: GoogleAIStudioJsonClient
    system_prompt: str
    user_prompt_builder: Callable[[LearnerMetricQualityCriticRequest], str]
    temperature: float = 0.0
    max_output_tokens: int = 1024

    def __call__(self, request: LearnerMetricQualityCriticRequest) -> Mapping[str, object]:
        return self.client.complete_json(
            messages=(
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt_builder(request)},
            ),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


__all__ = [
    "GoogleAIStudioLearnerMetricQualityCriticTransport",
    "build_learner_metric_quality_critic_messages",
]
