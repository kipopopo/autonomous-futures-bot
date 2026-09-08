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
| 12 | E2E Testing Suite (Tiers 1-4) | Systematic unit and integration test suite covering feature, boundary, pairwise, and application scenarios | M3 | Dual Track E2E |
| 13 | Full Quality Gate Verification & Audit | Passing ruff, mypy, pytest 246+ tests, reproduce_exit_cost_audit.py, and forensic integrity audit | M4 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Paper Ledger Feedback Extractor | Implement `src/autonomous_futures/paper/feedback_extractor.py` and unit tests in `tests/unit/test_paper_ledger_feedback_extractor.py` | none | DONE (23 unit tests pass, 31 stress tests pass, 16 adversarial tests pass, ruff/mypy clean, CLEAN audit) |
| M2 | Autonomous Cycle CLI Runner & Immutability | Implement `scripts/run_autonomous_cycle.py`, verify/harden `LivePaperEngine` active trade immutability | M1 | DONE (CLI runner complete, cryptographic content hash verification across 4 paper modules, 14 immutability unit tests, 81 CLI stress assertions, 22 adversarial tamper assertions, CLEAN audit) |
| M3 | Dual Track E2E Testing Suite | Build end-to-end integration tests in `tests/integration/test_run_autonomous_cycle_cli.py` across Tiers 1-4 | M1, M2 | PLANNED |
| M4 | Final Quality Gate Verification & Audit | Run ruff, mypy, pytest (full suite), reproduce_exit_cost_audit.py, and adversarial integrity audit | M3 | PLANNED |

## Interface Contracts
### Feedback Extractor ↔ Autonomous Cycle Runner
- Extractor API:
  `extract_paper_feedback(*, ledger_path: Path, lifecycle_path: Path | None = None, symbol: str | None = None, candidate_id: str | None = None, candidate_artifact: CreatorCandidateArtifact | None = None, candidate_artifact_path: Path | None = None, policy: PaperQualificationPolicy | None = None, bundle_hash: str | None = None, dataset_registry_hash: str | None = None) -> CreatorQualificationFailureFeedback | None`
- Output: `CreatorQualificationFailureFeedback` or `None` if candidate is performing adequately without breach.
- Serialization: `model_dump_json(indent=2)` producing valid JSON conforming to version 1 schema.

### CLI Runner ↔ Autonomous Cycle Pipeline
- CLI entrypoint: `scripts/run_autonomous_cycle.py` (executable with `__main__` and `main(argv=None) -> int`).
- Ingestion: loads Parquet from `research/immutable-data/5m/canonical/{symbol}-5m.parquet` via `read_canonical_parquet`.
- Pipeline invocation: `execute_autonomous_cycle(config=..., windows=..., prior_feedback=..., critic_transport=..., creator_transport=..., paper_engine=..., simulator=...)`.
- Artifact output: writes `autonomous-cycle-result.json` and `cycle-audit.json` to `--output-dir`.

## Code Layout
- `src/autonomous_futures/paper/feedback_extractor.py`: Extractor implementation.
- `scripts/run_autonomous_cycle.py`: Autonomous cycle CLI runner.
- `tests/unit/test_paper_ledger_feedback_extractor.py`: Unit tests for feedback extractor.
- `tests/integration/test_run_autonomous_cycle_cli.py`: Integration tests for CLI runner, idempotency, and active trade immutability.
