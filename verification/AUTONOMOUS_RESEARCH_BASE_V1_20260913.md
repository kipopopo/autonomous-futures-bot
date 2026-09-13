# Autonomous Research Base v1 — Verification

**Date:** 2026-09-13
**Scope:** offline autonomous research/learning orchestration only
**Safety state:** cached-only, unpromoted, paper-disabled, execution-disabled

## Delivered

Base v1 composes the existing bounded deterministic research cycle with two typed embedded-AI seams:

```text
complete rejected-history memory
→ failure learner
→ falsifiable research planner
→ bounded Creator/Critic/OOS/WF cycle
→ immutable cycle checkpoint
→ next failure-memory entry
→ next materially-different experiment
```

Implemented contracts and behavior:

- `FailureMemoryEntry` — hash-bound rejected-gate history with candidate, qualification, scope, and failed-gate lineage.
- `FailureLearningRequest` / `FailureLearningArtifact` — complete-history failure analysis with explicit constraints and novelty dimensions.
- `ResearchPlanRequest` / `ResearchPlan` — one falsifiable plan tied to the full failure memory, learner output, fixed dataset scope, and complete forbidden candidate set.
- Stable `thesis_hash` — rejects the same thesis even when the cycle ID or full plan hash changes.
- `AutonomousResearchBase` — finite `max_cycles` loop with immutable seed, learning, plan, cycle, failure-memory, and final-result artifacts.
- Existing-cycle adapter — invokes the existing deterministic cycle with `paper_engine=None` and forwards the approved plan to Creator.
- Creator prompt binding — includes plan hypothesis, expected regime, family, novelty dimensions, falsification criteria, and plan hash.
- Canonical learner/planner prompts — authority-denying, evidence-only prompts; raw provider output is not retained.
- Direct Google AI Studio learner/planner transports — compose the canonical prompts with the existing JSON client and preserve only allowlisted metadata; no retry/fallback policy is added.
- Write-once, hash-verified persistence and final-result idempotency/resume behavior.

## Safety invariants

The Base v1 boundary rejects or preserves:

- `data_source="cached_only"`
- `promotion_state="unpromoted"`
- `paper_activation=false`
- `execution_authority=false`
- `exchange_access=false`
- admitted cycle output
- duplicate historical candidate IDs
- replayed thesis fingerprints
- incomplete failure-memory scope
- rejected qualification without typed next feedback
- non-UTC timestamps and tampered hashes

The Base API has no paper engine, order router, breaker control, risk mutation, leverage authority, testnet path, or live path.

## Changed files

- `src/autonomous_futures/research/autonomy_contracts.py`
- `src/autonomous_futures/research/autonomy_prompts.py`
- `src/autonomous_futures/research/creator_generator.py`
- `src/autonomous_futures/research/creator_prompts.py`
- `src/autonomous_futures/research/__init__.py`
- `src/autonomous_futures/pipeline/autonomous_base.py`
- `src/autonomous_futures/pipeline/autonomous_cycle.py`
- `src/autonomous_futures/pipeline/__init__.py`
- `tests/unit/test_autonomous_research_base.py`

## Verification

- Base/Creator/Critic/cycle/provider focused suite after the final adapter correction: **38 passed in 2.40s**.
- Targeted Ruff: **pass**.
- Targeted Ruff format: **pass**.
- Targeted mypy: **pass**.
- Full locked pytest after the final orphan-resume correction: **2,247 passed in 886.62s**.
- No provider call, exchange/network access, paper activation, candidate admission, restart, order, testnet action, or live action was performed.

## Honest limitations / next boundary

- The failure learner is an explicit typed failure-analysis seam; this slice does not silently invent a new ML trainer or claim model-quality improvement.
- Real provider smoke was not executed by this offline boundary. The adapters use the canonical prompts, existing client, safe metadata, and caller-owned model configuration; credential resolution and authenticated network verification remain a separate gate.
- Existing learner model training/evaluation artifacts remain separate and require an explicit objective, causal inputs, trainer, and their own evidence boundary.
- Current paper runtime remains `HALTED`; this work does not create resume authority or change the deployed runtime.
- Qualification, paper admission, testnet, and live promotion remain separate decisions.
