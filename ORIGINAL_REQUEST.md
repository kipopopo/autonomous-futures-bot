# Original User Request

## 2026-09-08T09:09:37Z

Requested team: Full multi-agent team (parallel researchers, architects, builders, and auditors)

Build an end-to-end autonomous cycle CLI runner (`scripts/run_autonomous_cycle.py`) and paper ledger feedback extractor that connects real SQLite paper trade performance outcomes to the bounded autonomous cycle pipeline, generating revised qualified strategies and safely updating the paper candidate registry.

Working directory: B:\
Integrity mode: demo

## Requirements

### R1. Paper Ledger Feedback Extractor
Implement a component to query closed trades from the paper trading SQLite database (`paper-ledger.sqlite3` / `paper-lifecycle.sqlite3`), aggregate trade performance metrics (net PnL, profit factor, win rate) per candidate, and produce a structured `CreatorQualificationFailureFeedback` artifact whenever an active candidate underperforms or breaches defined criteria.

### R2. Autonomous Cycle CLI Runner (`scripts/run_autonomous_cycle.py`)
Build an executable CLI runner that:
- Accepts arguments for target symbol, ledger DB path, cached market data windows, qualification policy thresholds, and output artifact paths.
- Automatically extracts prior feedback or loads supplied failure evidence.
- Orchestrates the full bounded autonomous cycle via `execute_autonomous_cycle` (feedback → critic review → creator proposal → deterministic OOS walk-forward simulation → qualification gates → candidate admission).
- Persists audit logs and structured `AutonomousCycleResult` artifacts.

### R3. Safe Strategy Adoption & Open Trade Immutability
Ensure newly qualified strategies are cleanly admitted into the paper engine candidate pool, while guaranteeing that any active position currently open for that symbol remains strictly bound to its original strategy rules without mutation.

### R4. Controlled Infrastructure & Zero Unapproved Network Calls
Operate strictly in `cached_only` mode with deterministic local simulation. Zero live exchange network calls, zero unapproved paid LLM API calls, and zero unauthorized VPS service restarts.

## Acceptance Criteria

### Automated Programmatic Verification
- [ ] Unit tests in `tests/unit/` verify the feedback extractor correctly analyzes closed trades and generates compliant `CreatorQualificationFailureFeedback`.
- [ ] Integration tests in `tests/integration/` verify `scripts/run_autonomous_cycle.py` end-to-end against real 5m Parquet data and temporary SQLite databases.
- [ ] Idempotent execution: running the CLI runner multiple times with identical inputs produces consistent hashes without corrupting state or duplicating entries.
- [ ] Active trade protection: verified that an active trade on the target symbol retains its original candidate artifact after admission of a new strategy.
- [ ] All code passes strict quality gates:
  - `uv run --locked ruff check src tests scripts` (0 errors)
  - `uv run --locked ruff format --check src tests scripts` (0 changes needed)
  - `uv run --locked mypy src scripts` (0 issues)
  - `uv run --locked pytest` (all new and existing 246 regression tests pass)
  - `uv run python verification/reproduce_exit_cost_audit.py` (exact match)

## 2026-09-08T13:55:46Z

Requested team: Full multi-agent team (parallel researchers, architects, builders, and auditors)

Integrate real Google AI Studio LLM provider transports restricted strictly to Gemma 4 (31B and 26B) for strategy creation and learner critique into the bounded autonomous cycle, with non-bypassable call/cost ceilings and zero secret leakage.

Working directory: B:\
Integrity mode: development

## Requirements

### R1. Google AI Studio Gemma Provider Integration
Integrate genuine LLM provider transports for Creator strategy generation (`GoogleAIStudioProposalTransport`) and Learner Critic review (`GoogleAIStudioLearnerCriticTransport`) into `scripts/run_autonomous_cycle.py` and the pipeline execution boundary.
- Permitted models are strictly restricted to: `gemma-4-31b-it` and `gemma-4-26b-a4b-it`.
- Add CLI options: `--provider {google_ai_studio,demo}` (default `demo`), `--model {gemma-4-31b-it,gemma-4-26b-a4b-it}` (default `gemma-4-31b-it`), and `--temperature`.
- Preserve `--demo` as the default to guarantee that zero paid or external API calls are made unless explicitly enabled by the operator.

### R2. Hard Budget and Call Governance
Enforce non-bypassable ceiling limits on provider interactions:
- Strictly bounded execution: maximum 1 Creator proposal call and 1 Critic review call per cycle attempt (`max_attempts=1`, `max_retries=0`).
- No infinite retry loops and no silent fallback between providers; any HTTP/API failure or invalid JSON generation must immediately trigger a structured failure exit code (`3`) and record the failure reason.
- Capture execution metrics (model ID, provider name, call status, latency in milliseconds) in `cycle-audit.json` and `autonomous-cycle-result.json`.

### R3. Zero Secret Leakage & Credential Staging
Enforce strict credential resolution from environment variables (`GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_AI_STUDIO_API_KEY`) or repo `.env` using existing safe resolution logic (`resolve_credential`).
- Reject passing API keys via CLI flags.
- Guarantee that API keys, Authorization headers, and raw credential data are never logged, never printed to console, and never saved in audit JSON artifacts.
- When credentials are missing and `--provider google_ai_studio` is requested, exit with a clean descriptive error code (`3`) without raising unhandled tracebacks.

### R4. Comprehensive Verification & Regression Safety
Implement rigorous programmatic tests covering all new provider paths:
- Unit tests validating parameter parsing, prompt formulation, response parsing, and budget enforcement using offline mocks.
- Unit tests verifying that secret leakage does not occur in logs, audit records, or exception messages.
- Integration tests verifying CLI execution in both `--demo` and `--provider google_ai_studio` (mocked transport) modes.
- Full regression verification: ensure 100% pass across all pre-existing unit and integration test suites.

## Acceptance Criteria

### Provider CLI & Wiring
- [ ] Running `python scripts/run_autonomous_cycle.py --help` shows `--provider`, `--model`, and `--temperature` options with strict choices.
- [ ] `--provider google_ai_studio` connects `GoogleAIStudioProposalTransport` and `GoogleAIStudioLearnerCriticTransport` with the selected Gemma 4 model.
- [ ] `--demo` (or default without `--provider google_ai_studio`) executes 100% offline using deterministic heuristics without attempting network calls or credential lookups.

### Budget & Safety Invariants
- [ ] Number of provider requests per cycle cannot exceed 1 for Creator and 1 for Critic under any condition (`max_retries=0`).
- [ ] Missing API keys with `--provider google_ai_studio` exit cleanly with exit code 3 and JSON error indicating missing credentials without leaking environment paths.
- [ ] `cycle-audit.json` and `autonomous-cycle-result.json` record `provider: "google_ai_studio"`, `model: "<selected-gemma-model>"`, and execution latency, with zero credential attributes.

### Verification & Quality Gates
- [ ] New unit tests in `tests/unit/test_google_ai_studio_cycle_integration.py` pass 100%.
- [ ] New integration tests in `tests/integration/test_run_autonomous_cycle_cli.py` covering provider flags pass 100%.
- [ ] `uv run --locked ruff check src tests scripts` reports 0 errors.
- [ ] `uv run --locked ruff format --check src tests scripts` passes cleanly.
- [ ] `uv run --locked mypy src scripts` reports 0 type issues.
- [ ] All 48+ existing unit and integration tests continue to pass.
