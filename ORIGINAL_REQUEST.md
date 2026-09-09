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

## 2026-09-09T01:08:18Z

Requested team: Full multi-agent team (parallel researchers, architects, builders, and auditors)

Implement dynamic, zero-downtime candidate hot-reloading for the 24/7 Live Paper Trading Daemon so newly admitted autonomous strategies published to the candidate registry manifest are seamlessly adopted without service restarts, WebSocket interruptions, or open-trade mutations.

Working directory: B:\
Integrity mode: development

## Requirements

### R1. Candidate Registry Manifest Specification & Publisher
Define and implement a versioned, atomic candidate registry manifest (`candidate_registry.json`) in the paper trading storage directory (`artifacts/paper_live/`):
- Contract includes: `registry_version`, `updated_at`, `symbols: {<symbol>: {candidate_id, candidate_artifact_hash, artifact_path, qualification_hash, admitted_at}}`, and a top-level deterministic `registry_hash`.
- `scripts/run_autonomous_cycle.py` atomically updates this manifest (write to temporary file + atomic rename) whenever a candidate achieves `admitted` status.
- Support reading and publishing with strict schema validation and cryptographic content hash verification.

### R2. Zero-Downtime Hot-Reloading in Live Paper Daemon
Enhance `scripts/run_phase_259_live_paper_daemon.py` and `LivePaperEngine` to periodically monitor `candidate_registry.json`:
- Check for manifest updates in `run_heartbeat_loop` (and/or on 5m candle close) using file modification time (`mtime`) and SHA-256 hash checks without blocking the event loop.
- Upon detecting an update, safely load and validate the new candidate artifacts using `_artifact_content_hash`.
- Call `engine.admit_candidate(...)` to update `engine.candidates[symbol]` for subsequent entries without interrupting WebSocket feeds or resetting shared account margin.
- **Open-Trade Immutability Invariant**: Any currently open trade (`ActivePaperTrade`) MUST retain its original strategy binding (`trade.candidate`); its exit rules, signal evaluations, and protective ATR levels must not be mutated by the newly hot-reloaded candidate.

### R3. Observability & Health Telemetry
Expose candidate registry state in runtime telemetry and diagnostics:
- Update `paper-daemon-health.json` emitted by `run_heartbeat_loop` to include `active_candidates: {<symbol>: <candidate_id>}` and `last_registry_reload: {reloaded_at, registry_hash, reload_status}`.
- Emit structured log messages on reload events and handle malformed or corrupted registry manifests fail-closed (log warning and retain current candidates without crashing the daemon).

### R4. Comprehensive Verification & Adversarial Stress Tests
Implement programmatic test suites:
- Unit tests validating manifest schema serialization, atomic publishing, and hash verification.
- Concurrency and lifecycle tests in `tests/integration/test_paper_candidate_hot_reload.py`:
  1. Hot-reload during active position: verify active trade retains Candidate A exit behavior while subsequent trade adopts Candidate B.
  2. Malformed/tampered manifest resistance: verify daemon rejects corrupt JSON or hash mismatches and preserves existing candidates safely.
  3. Continuous daemon stability: verify zero disruption to WebSocket message processing and margin accounting during reload.
- Ensure 100% pass across all pre-existing unit and integration test suites.

## Acceptance Criteria

### Registry Manifest & Publishing
- [ ] `candidate_registry.json` schema is formally specified as a Pydantic model with deterministic SHA-256 `registry_hash`.
- [ ] `scripts/run_autonomous_cycle.py` atomically updates `candidate_registry.json` upon candidate admission.

### Daemon Hot-Reload & Immutability
- [ ] `run_phase_259_live_paper_daemon.py` automatically detects and reloads updated candidates within the heartbeat interval without process restarts.
- [ ] Any existing active position continues evaluating exits against its original candidate binding; zero strategy mutation on open trades.
- [ ] Subsequent new entries opened after hot-reload execute using the newly admitted candidate.
- [ ] Corrupted, partially written, or tampered manifest files are rejected fail-closed without crashing the daemon or altering running candidates.

### Health Telemetry & Quality Gates
- [ ] `paper-daemon-health.json` reflects the current active candidate ID per symbol and last reload timestamp.
- [ ] `tests/integration/test_paper_candidate_hot_reload.py` passes 100%.
- [ ] `uv run --locked ruff check src tests scripts` reports 0 errors.
- [ ] `uv run --locked ruff format --check src tests scripts` passes cleanly.
- [ ] `uv run --locked mypy src scripts` reports 0 type issues.
- [ ] All 93+ existing unit and integration tests continue to pass.

## 2026-09-09T03:03:22Z

Requested team: Full multi-agent team (parallel researchers, architects, builders, and auditors)

Build an autonomous scheduling and trigger daemon (`scripts/run_autonomous_scheduler.py`) that periodically evaluates paper trading ledger feedback, orchestrates the bounded autonomous cycle (`scripts/run_autonomous_cycle.py`), and hot-publishes qualified candidate strategies with non-overlapping process locks, failure backoff, and durable health observability.

Working directory: B:\
Integrity mode: development

## Requirements

### R1. Autonomous Scheduler CLI & Lifecycle Runner
Implement an executable daemon/scheduler (`scripts/run_autonomous_scheduler.py`):
- Run continuously or as a single-shot execution with options: `--interval-seconds` (default 3600), `--symbol`, `--ledger-db`, `--parquet-path`, `--provider {demo,google_ai_studio}`, `--model`, `--once` (run single evaluation pass and exit).
- Support non-overlapping execution lock (PID lockfile / filesystem mutex) to prevent concurrent cycle executions from corrupting artifacts or SQLite ledgers.
- Graceful shutdown on SIGINT / SIGTERM: wait for running cycle to complete or cleanly abort child execution without leaving orphaned processes or corrupt lockfiles.

### R2. Dual Trigger Mechanism: Periodic Interval & Ledger Performance Breach
Implement intelligent triggering logic to optimize compute and LLM calls:
- **Interval Trigger**: Trigger an autonomous cycle when the scheduled interval elapses, provided fresh 5m market data is available.
- **Feedback / Breach Trigger**: Monitor `paper-ledger.sqlite3` closed trades; trigger an evaluation cycle early when performance breaches the qualification policy or when a minimum number of new trades close under an underperforming candidate.
- **Throttle / Cooldown Guard**: Enforce a minimum cooldown between consecutive cycles (e.g. `--min-cooldown-seconds 300`) to prevent rapid-fire loop executions during market volatility.

### R3. Resilient Error Handling & Exponential Backoff
Guarantee robust continuous unattended operation:
- Handle child process failures (exit code 2 or 3), network timeouts, or missing market data gracefully without crashing the scheduler daemon.
- Implement exponential backoff on consecutive cycle failures (e.g. 1m -> 2m -> 4m up to a maximum cap), resetting to standard interval on success.
- Record failure diagnostics and error lineage in structured logs.

### R4. Observability & Daemon Health Telemetry
Expose scheduler health and execution telemetry:
- Emit `scheduler-health.json` on each loop iteration and status change:
  - `status`: `IDLE`, `RUNNING_CYCLE`, `BACKOFF`, `STOPPED`.
  - `last_run_at`, `next_run_at`, `consecutive_failures`, `total_cycles_executed`, `admitted_candidates_count`.
  - `last_cycle_result`: {`cycle_id`, `status`, `exit_code`, `candidate_id`, `admitted`}.
- Provide diagnostic inspectability for operators and systemd service integration.

### R5. Comprehensive Verification & Adversarial Testing
Implement exhaustive programmatic tests:
- Unit tests validating lock acquisition/release, PID file cleanup, trigger decision logic, and exponential backoff calculations.
- Concurrency tests verifying that two scheduler instances refuse to execute simultaneously.
- Integration tests in `tests/integration/test_autonomous_scheduler.py` simulating end-to-end scheduler execution:
  1. Periodic timer trigger firing cycle and updating `candidate_registry.json`.
  2. Ledger breach trigger firing ahead of schedule upon performance degradation.
  3. Graceful termination on SIGINT/SIGTERM without state corruption.
  4. Failure recovery and backoff behavior under simulated cycle errors.

## Acceptance Criteria

### Daemon CLI & Lock Invariants
- [ ] `python scripts/run_autonomous_scheduler.py --help` exposes interval, symbol, provider, cooldown, and `--once` options.
- [ ] Single-instance lock mechanism prevents multiple concurrent scheduler processes; second process exits cleanly with descriptive error.
- [ ] SIGINT / SIGTERM triggers clean shutdown and unlinks the lockfile.

### Trigger Logic & Backoff
- [ ] Scheduler triggers cycles accurately upon interval expiration when new data is present.
- [ ] Underperforming closed trades in SQLite ledger trigger early cycle execution when cooldown permits.
- [ ] Consecutive failures back off exponentially without crashing the daemon process.

### Telemetry & Health Invariants
- [ ] `scheduler-health.json` is emitted and updated deterministically on every iteration.
- [ ] Successfully admitted strategies update both `candidate_registry.json` and scheduler telemetry.

### Verification & Quality Gates
- [ ] `tests/integration/test_autonomous_scheduler.py` passes 100%.
- [ ] `uv run --locked ruff check src tests scripts` reports 0 errors.
- [ ] `uv run --locked ruff format --check src tests scripts` passes cleanly.
- [ ] `uv run --locked mypy src scripts` reports 0 type issues.
- [ ] All pre-existing unit and integration tests continue to pass.
