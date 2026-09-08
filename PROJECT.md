# Project: Autonomous Futures Bot — Autonomous Integration Pipeline

## Architecture
The Autonomous Integration Pipeline closes the feedback loop between live/paper execution outcomes and autonomous strategy revision in a strictly bounded, deterministic, cached environment:
1. **Paper Ledger & Lifecycle SQLite Databases**: Records paper trades (`paper_ledger_events` in `paper-ledger.sqlite3`) and mark-to-market telemetry (`paper_lifecycle_marks` in `paper-lifecycle.sqlite3`).
2. **Paper Ledger Feedback Extractor (`src/autonomous_futures/paper/feedback_extractor.py`)**: Reads closed trades via non-blocking `ReadOnlyLedgerReader`, computes performance metrics (`calculate_performance_metrics`), identifies gate breaches against paper qualification thresholds, and generates validated `CreatorQualificationFailureFeedback` artifacts.
3. **Autonomous Cycle CLI Runner (`scripts/run_autonomous_cycle.py`)**: Deterministic CLI entry point orchestrating `execute_autonomous_cycle()`:
   - Ingests prior feedback (extracted from ledger or provided via path).
   - Ingests cached 5m Parquet market data windows (`CachedEvaluationWindow`).
   - Executes deterministic learner critic review and creator proposal generation.
   - Evaluates proposals via deterministic out-of-sample walk-forward simulation (`evaluate_cached_oos_walk_forward`).
   - Gates qualification via `WalkForwardQualificationPolicy`.
   - Safely admits qualified candidates into `LivePaperEngine` using `StrategyAdmissionDecider`.
   - Persists sanitized audit logs (`cycle-audit.json`) and structured results (`autonomous-cycle-result.json`).
4. **Active Trade Immutability**: Ensures in-flight trades retain their original candidate artifact (`trade.candidate`) throughout their entire lifecycle (signals, marks, exits, approvals), even after a newly revised candidate is admitted for the symbol.
5. **Controlled Infrastructure**: Strictly `cached_only` mode, zero external network calls, zero unapproved LLM calls, zero VPS restarts.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Closed Trade Query & Model Extraction | Query closed trades from SQLite `paper-ledger.sqlite3` and `paper-lifecycle.sqlite3` using non-blocking connection | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Paper Metric Calculation | Compute exact Decimal metrics: net PnL, profit factor, win rate %, drawdown %, trade count | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Paper Qualification Breach Evaluation | Compare candidate metrics against paper breach policy thresholds to identify failed gates | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Failure Feedback Artifact Generation | Construct fully validated, sorted `CreatorQualificationFailureFeedback` artifact | M1 | ORIGINAL_REQUEST §R1 |
| 5 | CLI Argument Parsing & Validation | Parse `--symbol`, `--ledger-db`, `--parquet-path`, `--windows-count`, `--bars-per-window`, `--feedback-path`, thresholds, `--output-dir`, `--require-flat` | M2 | ORIGINAL_REQUEST §R2 |
| 6 | Deterministic Autonomous Cycle Orchestration | Orchestrate `execute_autonomous_cycle()` with cached 5m Parquet data and deterministic transports in demo mode | M2 | ORIGINAL_REQUEST §R2 |
| 7 | Audit Logging & Result Persistence | Persist `autonomous-cycle-result.json` and sanitized `cycle-audit.json` with SHA-256 cycle hash | M2 | ORIGINAL_REQUEST §R2 |
| 8 | Idempotent CLI Execution | Re-running with identical inputs produces consistent hashes without corrupting state | M2 | ORIGINAL_REQUEST §R2, Acceptance Criteria |
| 9 | Safe Strategy Adoption & Candidate Admission | Admit newly qualified candidates to `LivePaperEngine.candidates[symbol]` via `StrategyAdmissionDecider` | M2 | ORIGINAL_REQUEST §R3 |
| 10 | Open Trade Immutability Protection | Active trades remain bound to original candidate artifact across marks, exit evaluation, and close execution | M2 | ORIGINAL_REQUEST §R3 |
| 11 | Controlled Infrastructure Enforcement | Operate strictly in `cached_only` mode with zero live exchange calls and zero unapproved LLM calls | M2 | ORIGINAL_REQUEST §R4 |
| 12 | E2E Testing Suite (Tiers 1-4) | Systematic unit and integration test suite covering feature, boundary, pairwise, and application scenarios | M2 | Dual Track E2E |
| 13 | Full Quality Gate Verification & Audit | Passing ruff, mypy, pytest 246+ tests, reproduce_exit_cost_audit.py, and forensic integrity audit | M2 | Acceptance Criteria |
| 14 | Google AI Studio Gemma Provider Transports | Real LLM transports `GoogleAIStudioProposalTransport` and `GoogleAIStudioLearnerCriticTransport` strictly restricted to `gemma-4-31b-it` and `gemma-4-26b-a4b-it` | M3 | ORIGINAL_REQUEST 2026-09-08 §R1 |
| 15 | CLI Provider, Model & Temperature Options | Add `--provider {google_ai_studio,demo}` (default `demo`), `--model {gemma-4-31b-it,gemma-4-26b-a4b-it}` (default `gemma-4-31b-it`), and `--temperature`; reject API keys via CLI flags | M3 | ORIGINAL_REQUEST 2026-09-08 §R1, §R3 |
| 16 | Zero Secret Leakage Credential Resolution | Safe `resolve_credential(env, repo_env_path)` from `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_AI_STUDIO_API_KEY` or repo `.env`; zero key logging/saving | M3 | ORIGINAL_REQUEST 2026-09-08 §R3 |
| 17 | Hard Budget & Call Governance Invariants | Strict bounded execution: max 1 proposal and max 1 critic call (`max_attempts=1`, `max_retries=0`); fail-fast exit code 3 on API/schema failure | M3 | ORIGINAL_REQUEST 2026-09-08 §R2 |
| 18 | Execution Telemetry & Determinism Preservation | Capture model, provider, call status, latency in ms in `cycle-audit.json` and `autonomous-cycle-result.json`; set `latency_ms=0.0` in demo mode with `--now` | M3 | ORIGINAL_REQUEST 2026-09-08 §R2 |
| 19 | Programmatic Unit & Integration Test Suite | Rigorous tests in `tests/unit/test_google_ai_studio_cycle_integration.py` and `tests/integration/test_run_autonomous_cycle_cli.py` covering all provider paths and security invariants | M4 | ORIGINAL_REQUEST 2026-09-08 §R4 |
| 20 | Full Quality Gate Verification & Regression Safety | 100% pass on ruff check (0 errors), ruff format (0 changes), mypy (0 issues), all 48+ existing and new tests passing | M5 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Paper Ledger Feedback Extractor | Implement `src/autonomous_futures/paper/feedback_extractor.py` and unit tests in `tests/unit/test_paper_ledger_feedback_extractor.py` | none | DONE |
| M2 | Autonomous Cycle CLI Runner & Immutability | Implement `scripts/run_autonomous_cycle.py`, verify/harden `LivePaperEngine` active trade immutability | M1 | DONE |
| M3 | Google AI Studio Gemma Provider Integration & Budget Governance | Implement `GoogleAIStudioLearnerCriticTransport` alias, safe `resolve_credential`, CLI options (`--provider`, `--model`, `--temperature`), budget ceilings (`max_attempts=1`, `max_retries=0`), exit code 3 on errors, and telemetry capture | M2 | DONE (12/12 stress tests pass, 13/13 security challenges pass, 5/5 CLI integration tests pass, ruff/mypy clean, CLEAN audit) |
| M4 | Comprehensive Unit & Integration Test Suite | Implement `tests/unit/test_google_ai_studio_cycle_integration.py` and new integration tests in `tests/integration/test_run_autonomous_cycle_cli.py` covering flags, mocks, budget, and secret safety | M3 | DONE (34 unit passed in 3.1s, 16 integration passed in 15.3s, stream regex leak-interception verified, host .env isolated, CLEAN audit) |
| M5 | Final Quality Gate Verification & Regression Safety | Run ruff check, ruff format check, mypy, pytest full suite (48+ existing tests + new tests), and forensic integrity audit | M4 | DONE (2,041 tests passed, 0 failures, ruff/mypy clean, reproduce_exit_cost_audit exact match, CLEAN audit) |

## Interface Contracts
### Feedback Extractor ↔ Autonomous Cycle Runner
- Extractor API:
  `extract_paper_feedback(*, ledger_path: Path, lifecycle_path: Path | None = None, symbol: str | None = None, candidate_id: str | None = None, candidate_artifact: CreatorCandidateArtifact | None = None, candidate_artifact_path: Path | None = None, policy: PaperQualificationPolicy | None = None, bundle_hash: str | None = None, dataset_registry_hash: str | None = None) -> CreatorQualificationFailureFeedback | None`
- Output: `CreatorQualificationFailureFeedback` or `None` if candidate is performing adequately without breach.

### CLI Runner ↔ Google AI Studio Gemma Provider
- Provider Transports:
  - `GoogleAIStudioProposalTransport(client=..., model=..., temperature=...)` -> Callable[[CreatorGenerationRequest], Mapping[str, object]]
  - `GoogleAIStudioLearnerCriticTransport = GoogleAIStudioCriticTransport(client=..., model=..., temperature=...)` -> Callable[[LearnerCriticRequest], Mapping[str, object]]
- Permitted Models: strictly `Literal["gemma-4-31b-it", "gemma-4-26b-a4b-it"]`
- Credential Resolution:
  - `resolve_credential(env: Mapping[str, str] | None = None, repo_env_path: Path | None = None) -> str`
  - Searches `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_AI_STUDIO_API_KEY`, then repo `.env`. Raises `RuntimeError` if missing.
  - Exits with clean JSON `{"error_code": "missing_credentials", "message": "..."}` and exit code `3` without tracebacks or path leakage.
- Budget & Governance:
  - `max_attempts=1`, `max_retries=0`. Maximum 1 proposal call, maximum 1 critic call.
  - Failures (HTTP 4xx/5xx, invalid JSON schema) exit with code `3` and structured error message.
- Telemetry:
  - `AutonomousCycleResult` and `cycle-audit.json` include `provider`, `model`, `call_status`, `latency_ms`.
  - In demo mode with `--now`, `latency_ms = 0.0` for hash determinism.

## Code Layout
- `src/autonomous_futures/research/google_ai_studio_provider.py`: Google AI Studio proposal transport & `resolve_credential`.
- `src/autonomous_futures/research/learner_critic_provider.py`: Google AI Studio learner critic transport & alias.
- `src/autonomous_futures/pipeline/autonomous_cycle.py`: Pipeline execution & telemetry fields.
- `scripts/run_autonomous_cycle.py`: CLI options, transport wiring, governance, telemetry, and exit code handling.
- `tests/unit/test_google_ai_studio_cycle_integration.py`: Unit tests for provider cycle integration.
- `tests/integration/test_run_autonomous_cycle_cli.py`: Integration tests for CLI runner with provider flags.
