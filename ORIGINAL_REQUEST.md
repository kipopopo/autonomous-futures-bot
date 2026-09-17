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

## 2026-09-09T04:57:45Z

Requested team: Full multi-agent team (parallel researchers, architects, builders, and auditors)

Deliver Phase 4 of the Autonomous Futures Bot: End-to-End Autonomous Closed-Loop Verification, Health Diagnostics CLI, and Production Systemd Service Specification.

Working directory: B:\
Integrity mode: development

## Requirements

### R1. End-to-End Autonomous Closed-Loop Integration Test Suite
Implement an exhaustive integration test suite (`tests/integration/test_autonomous_pipeline_e2e.py`) validating the entire closed loop across running daemon components in an isolated temporary environment:
- **Baseline Ingestion**: Bootstrap `LivePaperEngine` with baseline candidate strategies and mock market feeds.
- **Trading & Feedback Accumulation**: Execute simulated trades recording entries and exits into `paper-ledger.sqlite3` and `paper-lifecycle.sqlite3`.
- **Trigger Activation**: Trigger `run_autonomous_scheduler.py` via performance breach (stop-loss hits / negative expectancy) or interval timer.
- **Cycle Execution**: Verify scheduler spawns `run_autonomous_cycle.py`, executes feedback review, trains revision parameters, qualifies candidate walk-forward OOS, and hot-publishes to `candidate_registry.json`.
- **Zero-Downtime Hot-Reload**: Verify `CandidateRegistryHotReloader` in the running paper engine detects the updated registry, verifies cryptographic hashes, and updates `active_candidates`.
- **Open-Trade Immutability Invariant**: Verify an existing open position continues evaluating exits against its original candidate binding without mutation, while new entries immediately adopt the newly admitted strategy.
- **Telemetry Parity**: Verify `scheduler-health.json`, `paper-daemon-health.json`, and `cycle-audit.json` reflect consistent state.

### R2. Unified Autonomous Pipeline Health Diagnostics CLI
Build an executable diagnostic utility (`scripts/check_autonomous_pipeline_health.py`) for operators and monitoring probes:
- Inspect runtime health files: `paper-daemon-health.json`, `scheduler-health.json`, and `candidate_registry.json`.
- Verify heartbeat freshness (alert if heartbeats are older than `--stale-threshold-seconds`, default 120s).
- Verify SQLite ledger integrity (`PRAGMA integrity_check`, query-only mode) and ensure no dirty recovery intents exist.
- Support options: `--storage-dir`, `--json` (emit structured JSON output), `--quiet` (minimal summary), `--stale-threshold-seconds`.
- Return clean exit codes: `0` (HEALTHY), `1` (DEGRADED / STALE), `2` (CRITICAL / UNHEALTHY).

### R3. Hardened Production Systemd Service Template
Create a hardened production-grade systemd service definition template (`systemd/autonomous-futures-scheduler.service.template`) for orchestrating the scheduler daemon on the Linux VPS alongside `autonomous-futures-paper-live.service`:
- Configured with `WorkingDirectory=/opt/autonomous-futures-bot`, standard user/group, locked `uv run --locked` invocation, `Restart=always`, `RestartSec=30`, and standard environment variables.
- Hardened systemd sandboxing: `NoNewPrivileges=true`, `ProtectSystem=strict`, `ProtectHome=read-only`, `ReadWritePaths=/opt/autonomous-futures-bot/artifacts`.
- Include documentation in docstrings or comments detailing deployment steps without restarting existing live services.

### R4. Fast Quality Gates & Zero Disruption Constraints
- Local automated tests must execute rapidly (<60s) using isolated temporary directories and mock/cached transports.
- DO NOT execute full repository 7-minute regression locally (full regression is verified automatically in GitHub Actions CI).
- Strict safety invariants: ZERO live exchange connections, ZERO paid LLM API calls, ZERO mutations to production VPS processes.

## Acceptance Criteria

### E2E Integration Suite
- [ ] `tests/integration/test_autonomous_pipeline_e2e.py` executes and passes 100% within 45s.
- [ ] Validates seamless progression from ledger feedback breach → autonomous cycle → registry publish → daemon hot-reload → position execution.
- [ ] Verifies open positions retain original candidate binding while subsequent positions execute the revised candidate.

### Health Diagnostics CLI
- [ ] `python scripts/check_autonomous_pipeline_health.py --help` displays all flags cleanly.
- [ ] Correctly identifies HEALTHY, DEGRADED (stale heartbeat), and CRITICAL (missing files, corrupt db) states with corresponding exit codes (0, 1, 2).
- [ ] Supports both formatted console summary and `--json` machine-readable output.

### Systemd Service Specification
- [ ] `systemd/autonomous-futures-scheduler.service.template` adheres to systemd best practices and Linux sandboxing.
- [ ] Safe to install alongside existing `autonomous-futures-paper-live.service`.

### Quality & Static Checks
- [ ] `uv run --locked ruff check src tests scripts` reports 0 errors.
- [ ] `uv run --locked ruff format --check src tests scripts` passes cleanly.
- [ ] `uv run --locked mypy src scripts` reports 0 type issues.
- [ ] Changes committed and pushed directly to `origin/main`.

## 2026-09-09T05:50:02Z

Requested team: Full multi-agent team (parallel researchers, architects, builders, and auditors)

Execute Phase 5 of the Autonomous Futures Bot: Production Staging, Code Parity Synchronization, and Zero-Disruption Operational Verification on Kainode Linux VPS.

Working directory: B:\
Integrity mode: development

## Requirements

### R1. VPS Codebase Staging & Compilation Parity
Synchronize the verified Phase 1–4 release source (commit `f80b5d4` on `origin/main`) to `/opt/autonomous-futures-bot` on Kainode VPS (`147.79.18.15`) via unprivileged SSH operator `afbot` using `C:/Users/thaqi/.ssh/kainode_ed25519_openssh`:
- Deploy updated `src/autonomous_futures/` (Gemma 4 provider, candidate registry hot-reloader, admission decider).
- Deploy updated `scripts/`: `run_autonomous_scheduler.py`, `run_autonomous_cycle.py`, `check_autonomous_pipeline_health.py`.
- Deploy updated `deploy/` and `systemd/` service templates.
- Compile Python sources remotely using `/opt/autonomous-futures-bot/.venv/bin/python -m compileall src scripts` to prove byte-compilation without syntax errors.

### R2. Pre-Flight Ledger & Live Service Invariant Verification
Verify production runtime safety before any execution:
- Audit live paper service: `autonomous-futures-paper-live.service` must remain undisturbed (`active/running`, restart count unchanged).
- Run read-only SQLite ledger checks (`mode=ro`, `PRAGMA query_only=ON`): confirm `PRAGMA integrity_check` is `ok`, verify open/close event count parity, and assert 0 dirty intents.
- Run the new health diagnostic CLI on the VPS:
  `/opt/autonomous-futures-bot/.venv/bin/python scripts/check_autonomous_pipeline_health.py --storage-dir /opt/autonomous-futures-bot/artifacts/paper_live --allow-missing-scheduler`
  and confirm it reports HEALTHY for the paper daemon.

### R3. Non-Disruptive Autonomous Cycle & Scheduler Dry-Run Smoke Test
Execute an offline, isolated single-shot smoke test of the autonomous scheduler under unprivileged user `afbot`:
- Create scheduler directory if not present: `/opt/autonomous-futures-bot/artifacts/paper_live/scheduler` (owned by `afbot:afbot`).
- Execute a single evaluation pass:
  `/opt/autonomous-futures-bot/.venv/bin/python scripts/run_autonomous_scheduler.py --symbol BTCUSDT --once --provider demo --ledger-db /opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3 --parquet-path /opt/autonomous-futures-bot/research/immutable-data/5m/canonical/BTCUSDT-5m.parquet --candidate-registry-path /opt/autonomous-futures-bot/artifacts/paper_live/candidate_registry.json --output-dir /opt/autonomous-futures-bot/artifacts/paper_live/scheduler`
- Assert `scheduler-health.json` is generated with valid schema and `scheduler.lock` is cleanly unlinked.
- Re-run `check_autonomous_pipeline_health.py` and assert unified HEALTHY status across both paper daemon and scheduler.

### R4. Formal Deployment Verification Artifact & Operational Runbook
Generate a reproducible verification report (`verification/PHASE_277_AUTONOMOUS_PIPELINE_DEPLOYMENT.md`):
- Record remote Git commit SHA, byte parity manifest hash, timestamps, and service PIDs.
- Document exact systemd unit file installation instructions for operator handover.
- Enforce strict safety invariants: ZERO restarts of `autonomous-futures-paper-live.service`, ZERO paid LLM API calls, ZERO live exchange orders, ZERO destructive database operations.

## Acceptance Criteria

### Remote Staging & Parity
- [ ] Remote `/opt/autonomous-futures-bot` compiles cleanly with zero syntax/type errors under Python 3.14.7.
- [ ] `check_autonomous_pipeline_health.py` and `run_autonomous_scheduler.py` are executable on the VPS.

### Live Safety & Invariant Protection
- [ ] `autonomous-futures-paper-live.service` PID remains unchanged throughout the operation (zero restarts).
- [ ] SQLite ledger `PRAGMA integrity_check` returns `ok` and unmatched events remain 0.

### Smoke Test Execution
- [ ] Single evaluation pass (`--once --provider demo`) completes with exit code 0.
- [ ] `scheduler-health.json` reflects successful cycle execution and lockfile is released.
- [ ] `check_autonomous_pipeline_health.py` returns exit code 0 (HEALTHY).

### Quality & Verification Evidence
- [ ] `verification/PHASE_277_AUTONOMOUS_PIPELINE_DEPLOYMENT.md` committed and pushed to `origin/main`.
- [ ] Local tests and static checks (`ruff`, `mypy`) pass cleanly.

## 2026-09-15T03:18:22Z

Autonomous futures execution, evidence-driven learning, strategy creation/revision (Creator/Critic), deterministic evaluation, paper feedback closure, and operational tooling for the Autonomous Futures Bot, executed under the strict safety mandate of ANTIGRAVITY_HANDOFF.md.

Working directory: C:\Users\thaqi\Projects\Autonomous Futures Bot
Integrity mode: development

## Team Specification
This is a single self-contained project mandate with strict repository ownership: keep it small and focused with one implementer (sole coding writer). Do not run competing coding agents against this checkout.

## Requirements

### R1. Durable Provider-to-Research Integration
Implement and integrate a supported finite CLI/orchestration entrypoint replacing disposable smoke scripts:
- Preflight credentials safely without printing, logging, or exposing secret values.
- Bind run ID, input evidence hashes, full failure history, policy, role/model, and request budget.
- Enforce zero retries and no provider fallback by default.
- Write durable typed accepted artifacts and sanitized audit records to approved evidence storage; verify integrity on readback.
- Reject partial, orphan, tampered, or replayed checkpoints prior to any network call.
- Preserve rejected outcomes honestly without schema relaxation.
- Full offline test coverage for accepted, rejected, schema diagnostic errors, provider failure, storage failure, restart/reuse, budget exhaustion, and zero-network preflight rejection.

### R2. Complete Autonomous Learning and Strategy-Creation Loop
Connect actual failure and paper feedback producers to learning, planning, Creator/Critic, deterministic evaluation, and immutable lineage:
- Distinguish LLM failure analysis from model training; enforce explicit objectives, causal inputs, dataset cutoffs, and adoption gates.
- Track complete historical forbidden candidate IDs and thesis fingerprints across cycles.
- Feed real rejected outcomes into materially different hypotheses without recycling selection data.
- Demonstrate restart-safe bounded cycles, call/cost/time limits, deterministic stop reasons, failure recovery, and auditable next-cycle inputs with zero unbounded spending loops.

### R3. Deterministic Evaluation and Admission
Enforce strict evaluation guardrails outside of AI control:
- Causal features, contiguous historical windows, and strict OOS / walk-forward / stress separation.
- Realistic fees, slippage, funding rates, conservative leverage/liquidation accounting, and Decimal ledger arithmetic. Missing data must remain UNAVAILABLE (never fabricated zero).
- Fixed qualification and admission thresholds established prior to outcomes.
- Demonstrate both qualified-fixture admission and real rejection paths, labeled separately.

### R4. Paper Execution and Feedback Closure
Connect qualified candidate loading to the paper trading runtime behind explicit admission/resume gates:
- Verify at most one position per pair, cash/margin/equity reconciliation, durable close synchronization, protective exits, fee/P&L attribution, restart recovery, and prevention of duplicate orders/positions.
- Route durable paper trade outcomes back into research/learning feedback loops.
- Test via isolated deterministic replay and fault injection showing daemon-driven entry, protection, exit, and reconciliation.
- Strictly respect the paper HALTED boundary: do not clear HALTED by restart or bypass breakers without explicit authorization.

### R5. Operational Tooling, Release Quality, and Exact-SHA Verification
Solidify operational infrastructure and verification:
- Bounded scheduling, idempotency, process locking, health/freshness checks, audit/budget visibility, alerts, and runbooks.
- Evidence-backed dashboard, API, and Telegram interfaces (dark accessible UI, MYT/GMT+8 display, UTC event storage).
- Enforce canonical checks (`pytest`, `ruff check`, `ruff format --check`, `mypy src scripts`, `uv lock --check`, `git diff --check`).
- Commit verified changes with outcome-sized commits, push to `origin/main`, and confirm GitHub Actions passes on the exact commit SHA.

### R6. Fail-Closed Boundaries & Safety Gate Isolation
Strictly isolate unapproved runtime boundaries:
- Default execution, live trading, VPS restart, paper resume, and paid provider network calls remain disabled until specific explicit approval is obtained.
- Implement and test fail-closed readiness interfaces and isolated simulation.
- Maintain a completion matrix tracking each component as IMPLEMENTED, OFFLINE-VERIFIED, PROVIDER-VERIFIED, DEPLOYED, RUNTIME-PROVEN, or BLOCKED.
- Never claim project completion while runtime acceptance gates remain BLOCKED.

## Acceptance Criteria

### Integration & Persistence
- [ ] Supported CLI entrypoint preflights credentials safely and executes provider-to-research orchestration with zero-retry and no-fallback enforcement.
- [ ] Durable typed learner/planner artifacts and sanitized audit envelopes are persisted, read back, and hash-verified from durable storage.
- [ ] Offline unit and integration tests verify accepted responses, schema rejections, provider failure, storage failure, checkpoint tampering, and budget limits.

### Research & Learning Loop
- [ ] End-to-end autonomous research loop connects failure memory -> learner -> planner -> Creator/Critic -> deterministic evaluation -> next failure memory.
- [ ] Thesis deduplication rejects identical hypotheses; forbidden candidate IDs prevent re-evaluating rejected candidates.
- [ ] Bounded cycle execution terminates cleanly on budget, cycle limit, or qualification with complete auditable lineage.

### Evaluation & Paper Execution
- [ ] Walk-forward and stress evaluation strictly enforce causal data, contiguous windows, and Decimal arithmetic without AI parameter overrides.
- [ ] Paper execution engine enforces single-position invariants, protective stops, position reconciliation, and feeds outcomes back to the research lab.
- [ ] Paper engine remains HALTED in production until explicit resume authorization is provided.

### Verification & Quality Gates
- [ ] All code passes `ruff check`, `ruff format --check`, `mypy src scripts`, and test regressions.
- [ ] Verified commits pushed to `origin/main` pass GitHub Actions on the exact commit SHA.
- [ ] Completion matrix clearly identifies tested offline components as OFFLINE-VERIFIED and unapproved runtime actions as BLOCKED.

## 2026-09-15T22:33:26Z

Execute multi-vector stress testing and adverse conditions simulation (Phase 264) across the 3 active candidates (`BTCUSDT` cand-btcusdt-dcb-002, `ETHUSDT` cand-ethusdt-dcb-003, `SOLUSDT` cand-solusdt-rgb-001) under Candidate Registry Manifest Version 2 to verify capital survival, margin cap compliance, and accounting reconciliation under extreme market stress.

Working directory: C:\Users\thaqi\Projects\Autonomous Futures Bot
Integrity mode: development

## Team Specification
This is a single self-contained run; keep it small and focused with one implementer (sole coding writer). Do not run competing coding agents against this checkout.

## Requirements

### R1. Multi-Vector Stress Scenario Execution under Manifest Version 2
Implement and execute the deterministic Phase 264 stress test runner (`scripts/run_phase_264_stress_simulation.py`) against Candidate Registry Manifest Version 2 across 6 comparative shock tracks over the 7-day canonical window (672 15m bars):
1. **Track 0: Baseline** (nominal Phase 263 conditions: 2.0 bps slippage, 0.04% taker fee).
2. **Track 1: Flash Crash Shock** (severe intra-bar adverse gap down -15% to -25% on long positions).
3. **Track 2: Slippage Surge Shock** (elevated adverse slippage 50.0 to 100.0 bps).
4. **Track 3: Fee & Spread Blowout Shock** (doubled taker fee 0.08% / 8 bps and spread expansion).
5. **Track 4: Volatility Spikes & Rapid Whipsaw Shock** (high volatility triggers and stop runs).
6. **Track 5: Composite Crisis Shock** (simultaneous combination of adverse shocks).

### R2. Portfolio Solvency & Risk Invariants
Enforce portfolio survival and margin safety rules across all shock tracks:
- Starting equity: 100.00 USDT shared margin account.
- **Capital Survival**: Terminal equity > 0.00 USDT across all tracks (no bankruptcy / negative cash).
- **Margin Utilization Ceiling**: Active margin allocation <= 80.00% of equity; preserve at least 20.00% unencumbered cash reserve buffer.
- **Double-Entry Accounting Reconciliation**: Exact mathematical balance verification across all tracks: drift = |final_cash - (starting_equity + realized_pnl)| < 1e-15.

### R3. Persistent Audit Telemetry & Artifact Packaging
Persist isolated audit databases and scenario reports to `artifacts/research/phase264/`:
- Isolated SQLite databases per track or composite (`paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`).
- Scenario audit reports (`stress-track-summary.json`, `paper-summary.json`) recording terminal equity, worst peak-to-trough drawdown, total fees, slippage absorbed, and cryptographic SHA-256 artifact hashes.

### R4. Fail-Closed Safety, Quality Gates & Remote CI Polling
Enforce strict autonomous operations safety:
- Maintain fail-closed state: `paper_activation: false`, `execution_authority: false`, `exchange_access: false`, `orders: 0`.
- Implement targeted unit tests in `tests/unit/test_phase_264_stress_simulation.py`.
- **DO NOT run the full test suite locally** (`uv run pytest`); leave the full 2,350+ regression suite to GitHub Actions CI.
- Execute local static quality gates: `ruff check`, `ruff format --check`, `mypy src scripts`, `uv lock --check`, `git diff --check`, and preflight secret scan.
- Commit, push to `origin/main`, and poll GitHub Actions CI until `status=completed, conclusion=success`.

## Acceptance Criteria

### Solvency & Risk Guardrails
- [ ] Terminal equity remains > 0.00 USDT in every stress track.
- [ ] Maximum margin utilization never exceeds the 80.00% ceiling.
- [ ] Zero balance drift (drift < 1e-15) verified across all simulation tracks.
- [ ] Circuit breaker / de-escalation logic successfully contains drawdown during flash crash scenarios.

### Artifacts & Reproducibility
- [ ] All required artifacts generated in `artifacts/research/phase264/`.
- [ ] Complete scenario comparison table generated comparing Track 0 through Track 5.
- [ ] Cryptographic SHA-256 checksums documented for all generated database and JSON artifacts.

### Quality & Remote CI Verification
- [ ] Targeted unit tests pass locally in < 30 seconds.
- [ ] Static quality checks (`ruff`, `mypy`, `uv lock`, `git diff`) pass with 0 errors.
- [ ] Zero secrets or API keys detected.
- [ ] Pushed commit SHA achieves `status=completed, conclusion=success` on GitHub Actions CI.

## 2026-09-16T12:57:37Z

Integrate candidate manifest v2 discovery, lifecycle telemetry monitoring, and automated cohort readiness evaluation into the autonomous paper trading runtime (Phase 265) to prepare fail-closed daemon operations without external order routing.

Working directory: C:\Users\thaqi\Projects\Autonomous Futures Bot
Integrity mode: development

## Team Specification
This is a single self-contained run; keep it small and focused with one implementer (sole coding writer). Do not run competing coding agents against this checkout.

## Requirements

### R1. Manifest-Driven Candidate Discovery & Dynamic Admission in Live Engine
Enhance `LivePaperTradingEngine` to support candidate loading and validation directly from `CandidateRegistryManifest`:
- Dynamically resolve active candidates from `CandidateRegistryManifest` (version >= 2, e.g. `artifacts/paper_live/candidate_registry.json`) instead of static hardcoded candidate tuples.
- Validate candidate artifact hashes, qualification hashes, and admission decisions using `StrategyAdmissionDecider` before trade execution or signal processing.
- Maintain single-position invariants per admitted symbol across shared portfolio margin.

### R2. Periodic Cohort Readiness & Health Telemetry Integration
Wire automated cohort readiness reporting into the paper runtime:
- Implement periodic or snapshot cohort evaluation combining `aggregate_paper_health` and `summarize_paper_cohort`.
- Expose a clean programmatic interface / CLI command (`autonomous_futures.paper.cohort_cli` or `scripts/run_paper_readiness_snapshot.py`) to generate `paper-cohort-readiness-report.json` and per-symbol health reports from SQLite stores (`paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`).
- Track readiness status codes: `unavailable`, `not_ready`, `blocked`, and `ready_for_human_review` based on mature trade count, accounting completeness, and lifecycle health.

### R3. Strict Fail-Closed Invariants & Zero Secret Leakage
Ensure absolute containment of live/external dependencies:
- Strict fail-closed defaults: `paper_activation: false`, `execution_authority: false`, `exchange_access: false`, `orders: 0`.
- Offline safety invariants: verify zero external API order execution and zero secrets/credentials in serialized reports or logs.

### R4. Targeted Testing, Static Quality Gates & Remote CI Polling
Enforce rigorous engineering hygiene:
- Add comprehensive targeted unit tests in `tests/unit/test_paper_cohort_runtime_readiness.py` covering manifest-driven admission, snapshot report generation, and status code transitions.
- **DO NOT run the full test suite locally** (`uv run pytest`); leave the full 2,350+ regression suite to GitHub Actions CI.
- Execute local static quality gates: `ruff check`, `ruff format --check`, `mypy src scripts`, `uv lock --check`, `git diff --check`, and preflight secret scan.
- Commit, push to `origin/main`, and poll GitHub Actions CI until `status=completed, conclusion=success`.

## Acceptance Criteria

### Candidate Discovery & Admission
- [ ] `LivePaperTradingEngine` can initialize and admit candidates dynamically from `CandidateRegistryManifest` (v2).
- [ ] Invalid or tampered candidates are rejected with explicit domain error codes.

### Cohort Readiness & Telemetry
- [ ] Cohort readiness evaluation executes cleanly against isolated SQLite stores and outputs valid `PaperCohortReadinessReport`.
- [ ] Per-symbol health reports and reason codes accurately reflect open positions, stale telemetry, or maturity status.

### Safety & Verification
- [ ] All safety invariants verified: fail-closed runtime, no exchange access, no API secret leakage.
- [ ] Targeted unit tests pass locally in < 30 seconds.
- [ ] Static quality checks (`ruff`, `mypy`, `uv lock`, `git diff`) pass with 0 errors.
- [ ] Pushed commit SHA achieves `status=completed, conclusion=success` on GitHub Actions CI.
## 2026-09-16T15:48:50Z

Verify the full lifecycle of the autonomous paper trading daemon under Candidate Registry Manifest Version 2 (Phase 266), coupling `LivePaperTradingEngine` with public market feeds, isolated SQLite persistence, dynamic candidate admission, automated cohort readiness telemetry, and strict fail-closed shutdown handling.

Working directory: C:\Users\thaqi\Projects\Autonomous Futures Bot
Integrity mode: development

## Team Specification
This is a single self-contained run; keep it small and focused with one implementer (sole coding writer). Do not run competing coding agents against this checkout.

## Requirements

### R1. Bounded Daemon Lifecycle Runner under Manifest Version 2
Implement and execute the deterministic Phase 266 dry-run daemon runner (`scripts/run_phase_266_daemon_verification.py`):
- Couple `LivePaperTradingEngine` with active Candidate Registry Manifest Version 2 (`BTCUSDT` cand-btcusdt-dcb-002, `ETHUSDT` cand-ethusdt-dcb-003, `SOLUSDT` cand-solusdt-rgb-001).
- Support a bounded execution mode (time-bounded seconds/minutes or batch bar ticks) with graceful shutdown handling (signal trap and timeout-driven termination).
- Validate candidate artifact hashes, qualification hashes, and admission decisions using `StrategyAdmissionDecider` on daemon startup.
- Maintain single-position invariants per symbol across shared portfolio margin (100.00 USDT initial equity).

### R2. Isolated Telemetry, Cohort Reporting & Artifact Packaging
Persist execution telemetry and audit reports to `artifacts/research/phase266/`:
- Record transactions and lifecycle marks into isolated SQLite databases: `paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, and `paper-observations.sqlite3`.
- Generate automated snapshot cohort readiness report (`paper-cohort-readiness-report.json`) using `evaluate_paper_cohort_snapshot`.
- Produce per-symbol health reports (`paper-health-report-{sym}.json`) and a comprehensive daemon verification summary (`daemon-summary.json` / `paper-summary.json`) with deterministic cryptographic SHA-256 artifact hashes.

### R3. Exact Accounting Reconciliation & Risk Invariants
Enforce mathematical precision and fail-closed safety:
- Verify exact double-entry accounting reconciliation: drift = |final_cash - (starting_equity + realized_pnl)| < 1e-15.
- Enforce margin utilization ceiling <= 80.00% and preserve >= 20.00% unencumbered reserve buffer.
- Ensure clean resource cleanup: no dangling WebSocket connections, no background thread leaks, and no unclosed SQLite file handles.

### R4. Fail-Closed Boundaries, Targeted Testing & Remote CI Polling
Enforce autonomous operations safety:
- Maintain strict fail-closed state: `paper_activation: false`, `execution_authority: false`, `exchange_access: false`, `orders: 0`.
- Verify zero secret or API key leakage across code, logs, and generated JSON reports.
- Implement comprehensive targeted unit tests in `tests/unit/test_phase_266_daemon_verification.py`.
- **DO NOT run the full test suite locally** (`uv run pytest`); leave the full 2,350+ regression suite to GitHub Actions CI.
- Execute local static quality gates: `ruff check`, `ruff format --check`, `mypy src scripts`, `uv lock --check`, `git diff --check`, and preflight secret scan.
- Commit, push to `origin/main`, and poll GitHub Actions CI until `status=completed, conclusion=success`.

## Acceptance Criteria

### Daemon Execution & Admission
- [ ] Daemon runner initializes and admits candidates dynamically from Manifest Version 2.
- [ ] Bounded dry-run execution completes without unhandled exceptions and terminates gracefully.

### Telemetry & Reporting
- [ ] Isolated SQLite databases (`paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`) persisted in `artifacts/research/phase266/`.
- [ ] `paper-cohort-readiness-report.json` and per-symbol health reports generated and cryptographically hashed.
- [ ] Balance reconciliation confirms zero drift (< 1e-15) between cash, equity, and realized PnL.

### Safety & Remote CI Verification
- [ ] Fail-closed safety invariants verified (zero exchange orders, no secret leakage).
- [ ] Targeted unit tests pass locally in < 30 seconds.
- [ ] Static quality checks (`ruff`, `mypy`, `uv lock`, `git diff`) pass with 0 errors.
- [ ] Pushed commit SHA achieves `status=completed, conclusion=success` on GitHub Actions CI.

## Request — 2026-09-17T02:43:31Z

Execute multi-day paper trading cohort observation, telemetry accumulation, and maturation evaluation under Candidate Registry Manifest Version 2 (Phase 267) to assess strategy progression towards human review readiness while maintaining strict fail-closed invariants and exact double-entry accounting.

Working directory: C:\Users\thaqi\Projects\Autonomous Futures Bot
Integrity mode: development

## Team Specification
This is a single self-contained run; keep it small and focused with one implementer (sole coding writer). Do not run competing coding agents against this checkout.

## Requirements

### R1. Multi-Day Cohort Observation & Telemetry Accumulation Runner
Implement and execute the deterministic Phase 267 cohort maturation runner (`scripts/run_phase_267_cohort_maturation.py`):
- Couple `LivePaperTradingEngine` with active Candidate Registry Manifest Version 2 (`BTCUSDT` cand-btcusdt-dcb-002, `ETHUSDT` cand-ethusdt-dcb-003, `SOLUSDT` cand-solusdt-rgb-001).
- Execute an extended multi-day observation replay (across canonical 14-day historical partitions or streaming windows) to accumulate sufficient trading cycles, mark-to-market observations, and lifecycle telemetry.
- Enforce periodic 6-hour fixed-slot observation marks into `paper-observations.sqlite3` with strict deduplication guards.
- Maintain single-position invariants per symbol across shared 100.00 USDT margin portfolio.

### R2. Cohort Maturation Telemetry & Human Review Readiness Reporting
Wire automated maturation reporting and gate checking into `artifacts/research/phase267/`:
- Record complete lifecycle and transaction marks into isolated SQLite databases: `paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, and `paper-observations.sqlite3`.
- Generate snapshot and cumulative cohort readiness reports (`paper-cohort-maturation-report.json`, `paper-cohort-readiness-report.json`) using `evaluate_paper_cohort_snapshot`.
- Track cohort readiness progression across status codes (`unavailable`, `not_ready`, `blocked`, `ready_for_human_review`) and per-symbol health status (`evaluating`, `maturing`, `mature`, `blocked`).
- Produce comprehensive maturation summary (`maturation-summary.json` / `paper-summary.json`) with deterministic SHA-256 artifact digests.

### R3. Exact Double-Entry Accounting & Margin Guardrails
Enforce exact mathematical balance and risk invariants across extended observation horizons:
- Verify exact double-entry accounting reconciliation: drift = |final_cash - (starting_equity + realized_pnl)| < 1e-15.
- Enforce margin utilization ceiling <= 80.00% and preserve >= 20.00% unencumbered cash reserve buffer throughout all open positions.
- Ensure clean resource cleanup: no connection leaks, thread leaks, or unclosed SQLite file handles.

### R4. Strict Fail-Closed Containment, Targeted Testing & Remote CI Polling
Enforce autonomous operations safety:
- Maintain strict fail-closed state: `paper_activation: false`, `execution_authority: false`, `exchange_access: false`, `orders: 0`, `api_keys_loaded: 0`.
- Verify zero secret or API key leakage across code, logs, and generated JSON reports.
- Implement comprehensive targeted unit tests in `tests/unit/test_phase_267_cohort_maturation.py`.
- **DO NOT run the full test suite locally** (`uv run pytest`); leave the full 2,350+ regression suite to GitHub Actions CI.
- Execute local static quality gates: `ruff check`, `ruff format --check`, `mypy src scripts`, `uv lock --check`, `git diff --check`, and preflight secret scan.
- Commit, push to `origin/main`, and poll GitHub Actions CI until `status=completed, conclusion=success`.

## Acceptance Criteria

### Execution & Telemetry Accumulation
- [ ] Cohort maturation runner loads candidates dynamically from Manifest Version 2 and replays multi-day observation windows cleanly.
- [ ] 6-hour fixed-slot observations accumulated in `paper-observations.sqlite3` without duplicate slot errors.
- [ ] Single-position invariant per symbol maintained across shared margin.

### Cohort Readiness & Artifact Packaging
- [ ] Isolated SQLite stores (`paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`) persisted in `artifacts/research/phase267/`.
- [ ] Maturation readiness report accurately evaluates trade maturity, per-symbol health, and status codes.
- [ ] Balance reconciliation confirms zero balance drift (< 1e-15) between cash, equity, and realized PnL.

### Safety & Remote CI Verification
- [ ] Strict fail-closed defaults verified (zero live exchange orders, zero API credentials).
- [ ] Targeted unit tests pass locally in < 30 seconds.
- [ ] Static quality gates (`ruff`, `mypy`, `uv lock`, `git diff`) pass with 0 errors.
- [ ] Pushed commit SHA achieves `status=completed, conclusion=success` on GitHub Actions CI.

## 2026-09-17T05:24:56Z

Execute multi-week paper trading cohort observation scaling, long-horizon telemetry accumulation, and maturation evaluation under Candidate Registry Manifest Version 2 (Phase 268) to assess strategy progression towards human review readiness while maintaining strict fail-closed invariants and exact double-entry accounting.

Working directory: C:\Users\thaqi\Projects\Autonomous Futures Bot
Integrity mode: development

## Team Specification
This is a single self-contained run; keep it small and focused with one implementer (sole coding writer). Do not run competing coding agents against this checkout.

## Requirements

### R1. Multi-Week Cohort Observation Horizon Scaling Runner
Implement and execute the deterministic Phase 268 long-horizon maturation runner (`scripts/run_phase_268_long_horizon_maturation.py`):
- Couple `LivePaperTradingEngine` with active Candidate Registry Manifest Version 2 (`BTCUSDT` cand-btcusdt-dcb-002, `ETHUSDT` cand-ethusdt-dcb-003, `SOLUSDT` cand-solusdt-rgb-001).
- Scale observation replay horizon from nominal 3-day window to multi-week canonical window (14 canonical days / 1,344 15m bars / 4,032 5m bars) from canonical Parquet data (`research/immutable-data/5m/canonical/`).
- Enforce periodic 6-hour fixed-slot observation marks into `paper-observations.sqlite3` with strict deduplication guards across the multi-week timeline.
- Maintain single-position invariants per symbol across shared 100.00 USDT margin portfolio.

### R2. Long-Horizon Maturation Telemetry & Readiness Transition Reporting
Wire automated long-horizon maturation reporting into `artifacts/research/phase268/`:
- Record complete lifecycle, order, and transaction marks into isolated SQLite databases: `paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, and `paper-observations.sqlite3`.
- Generate snapshot and cumulative cohort readiness reports (`paper-cohort-maturation-report.json`, `paper-cohort-readiness-report.json`) using `evaluate_paper_cohort_snapshot`.
- Track cohort readiness progression across status codes (`unavailable`, `not_ready`, `blocked`, `ready_for_human_review`) and candidate health transitions with accumulated trade counts and sample sizes.
- Produce comprehensive maturation summary (`maturation-summary.json` / `paper-summary.json`) with deterministic SHA-256 artifact digests.

### R3. Exact Double-Entry Accounting & Extended Horizon Margin Guardrails
Enforce exact mathematical balance and risk invariants across extended observation horizons:
- Verify exact double-entry accounting reconciliation: drift = |final_cash - (starting_equity + realized_pnl)| < 1e-15.
- Enforce margin utilization ceiling <= 80.00% and preserve >= 20.00% unencumbered cash reserve buffer throughout all open positions.
- Ensure clean resource cleanup: no dangling SQLite file handles, no thread leaks, and safe sidecar purges.

### R4. Strict Fail-Closed Containment, Targeted Testing & Remote CI Polling
Enforce autonomous operations safety:
- Maintain strict fail-closed state: `paper_activation: false`, `execution_authority: false`, `exchange_access: false`, `orders: 0`, `api_keys_loaded: 0`.
- Verify zero secret or API key leakage across code, logs, and generated JSON reports.
- Implement comprehensive targeted unit tests in `tests/unit/test_phase_268_long_horizon_maturation.py`.
- **DO NOT run the full test suite locally** (`uv run pytest`); leave the full 2,350+ regression suite to GitHub Actions CI.
- Execute local static quality gates: `ruff check`, `ruff format --check`, `mypy src scripts`, `uv lock --check`, `git diff --check`, and preflight secret scan.
- Commit, push to `origin/main`, and poll GitHub Actions CI until `status=completed, conclusion=success`.

## Acceptance Criteria

### Execution & Telemetry Accumulation
- [ ] Long-horizon maturation runner loads candidates dynamically from Manifest Version 2 and replays multi-week observation windows cleanly.
- [ ] 6-hour fixed-slot observations accumulated in `paper-observations.sqlite3` across multi-week timeline without duplicate slot errors.
- [ ] Single-position invariant per symbol maintained across shared margin.

### Cohort Readiness & Artifact Packaging
- [ ] Isolated SQLite stores (`paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`) persisted in `artifacts/research/phase268/`.
- [ ] Maturation readiness report accurately evaluates trade maturity, per-symbol health, and status codes.
- [ ] Balance reconciliation confirms zero balance drift (< 1e-15) between cash, equity, and realized PnL across extended horizon.

### Safety & Remote CI Verification
- [ ] Strict fail-closed defaults verified (zero live exchange orders, zero API credentials).
- [ ] Targeted unit tests pass locally in < 30 seconds.
- [ ] Static quality gates (`ruff`, `mypy`, `uv lock`, `git diff`) pass with 0 errors.
- [ ] Pushed commit SHA achieves `status=completed, conclusion=success` on GitHub Actions CI.
