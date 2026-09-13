"""Direct provider adapters for the autonomous learner and planner roles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .autonomy_contracts import (
    FailureLearningRequest,
    FailureLearningTransport,
    ResearchPlanRequest,
    ResearchPlanTransport,
)
from .autonomy_prompts import build_failure_learning_messages, build_research_plan_messages
from .google_ai_studio_provider import GoogleAIStudioJsonClient


@dataclass(frozen=True, slots=True)
class GoogleAIStudioFailureLearningTransport:
    """Call Google AI Studio for one bounded failure-learning request."""

    client: GoogleAIStudioJsonClient
    temperature: float = 0.2
    max_output_tokens: int = 2048

    def __call__(self, request: FailureLearningRequest) -> Mapping[str, object]:
        system, user = build_failure_learning_messages(request)
        return self.client.complete_json(
            messages=(system, user),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


@dataclass(frozen=True, slots=True)
class GoogleAIStudioResearchPlanTransport:
    """Call Google AI Studio for one bounded next-experiment plan."""

    client: GoogleAIStudioJsonClient
    temperature: float = 0.2
    max_output_tokens: int = 2048

    def __call__(self, request: ResearchPlanRequest) -> Mapping[str, object]:
        system, user = build_research_plan_messages(request)
        return self.client.complete_json(
            messages=(system, user),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


__all__ = [
    "FailureLearningTransport",
    "GoogleAIStudioFailureLearningTransport",
    "GoogleAIStudioResearchPlanTransport",
    "ResearchPlanTransport",
]
