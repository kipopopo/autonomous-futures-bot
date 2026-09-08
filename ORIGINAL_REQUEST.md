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
