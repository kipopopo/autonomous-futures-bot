# Project: Phase 298 — Dynamic Strategy Mining, Auto-Evolution & Microstructure Mutation Engine

## Architecture
Phase 298 establishes an autonomous real-time strategy mining, auto-evolution, and microstructure mutation pipeline for the Autonomous Futures Bot. It ingests live market features (Hawkes jump intensity $\lambda$, branching ratio, spectral radius $\rho$, Order Flow Imbalance OFI, volume profile, Donchian channels, rolling volatility), formulates deterministic quantitative hypotheses across candidate families (`DCB`, `RGB`, `MSM`), mutates parameters systematically while recording lineage, evaluates variants across multi-tier walk-forward out-of-sample (OOS) windows against 5 strict qualification gates, atomically promotes qualifying candidates to version 3 of the candidate registry manifest, hot-reloads them seamlessly into the running paper engine while guaranteeing open-trade immutability, governs balance solvency with mathematical zero-drift ($|\Delta| < 10^{-15}$ USDT), and exposes live telemetry via FastAPI and DaisyUI 5.7.42 dashboard.

```
Incoming Market Feeds (Phases 292-297)
  [Depth5, AggTrades, Hawkes ρ/λ, OFI, Volatility]
                  │
                  ▼
   [MicrostructureMutationEngine]
  ├── Families: DCB, RGB, MSM (New)
  ├── Systematic Parameter Perturbations
  └── Auditable Mutation Genealogy & Lineage
                  │
                  ▼
   [ContinuousOOSGateEvaluator]
  ├── Gate 1: Walk-Forward OOS Return >= 0.0%
  ├── Gate 2: Walk-Forward OOS Worst Drawdown <= 15.0%
  ├── Gate 3: Walk-Forward OOS Profit Factor >= 1.05
  ├── Gate 4: Min OOS Trade Count >= 5 in >= 1 Window
  └── Gate 5: Microstructure Resilience (-20% Flash Crash & 10% Spread Shock)
                  │
         ┌────────┴────────┐
     (Pass All 5)       (Fail Any)
         ▼                 ▼
   [Autonomous Promotion] [Pruning]
  ├── CreatorCandidateArtifact & Evidence
  ├── Atomic Manifest Update (v2 -> v3)
  └── CandidateRegistryHotReloader
       ├── LivePaperTradingEngine
       └── AutonomousLifecycleDaemon
            (Open Trade Immutability Guaranteed)
                  │
                  ▼
   [Continuous Zero-Drift Ledger & Merkle DAG]
  ├── |drift| < 10^-15 USDT
  └── Chained to Phase 297 (257f83f794465f3b89bfd9dbc25a2bf949d9fe315ecd97e2108c027ca3475668)
                  │
                  ▼
   [Observational API & DaisyUI Dashboard]
  ├── GET /api/v1/canary/strategy-mining & summary
  └── DaisyUI 5.7.42 Dashboard (#/mining)
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Feature Ingestion & MSM Family | Ingest Hawkes $\lambda, \rho$, OFI, volume profile; support DCB, RGB, and MSM | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Systematic Parameter Mutation | Mutate lookbacks, z-scores, ATR stops, regime context, margin multipliers | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Mutation Genealogy Tracking | Record parent ID, mutation lineage, generation counter, and parameter diffs | M1 | ORIGINAL_REQUEST §R1 |
| 4 | 5-Gate Walk-Forward OOS Evaluation | Gates: Return >= 0%, DD <= 15%, PF >= 1.05, Trades >= 5, Microstructure Resilience | M2 | ORIGINAL_REQUEST §R2 |
| 5 | Microstructure Resilience Gate | Simulate survival under Phase 297 flash crash (-20%) and spread shock (10.0%) | M2 | ORIGINAL_REQUEST §R2 |
| 6 | Unviable Candidate Pruning | Filter out sub-threshold hypotheses; retain top-performing candidates | M2 | ORIGINAL_REQUEST §R2 |
| 7 | Autonomous Candidate Promotion | Generate `CreatorCandidateArtifact` and qualification artifact for top candidates | M3 | ORIGINAL_REQUEST §R3 |
| 8 | Atomic Manifest v3 Update | Atomically advance `candidate_registry.json` from v2 to v3 with SHA-256 hash | M3 | ORIGINAL_REQUEST §R3 |
| 9 | Zero-Downtime Hot-Reload | Stat-first polling hot-reload in `LivePaperEngine` and `AutonomousLifecycleDaemon` | M3 | ORIGINAL_REQUEST §R3 |
| 10 | Open-Trade Immutability | Active trades retain original candidate exit rules; new trades adopt reloaded candidate | M3 | ORIGINAL_REQUEST §R3 |
| 11 | Zero-Drift Balance Conservation | Double-entry ledger reconciliation strictly enforcing $|\Delta| < 10^{-15}$ USDT | M4 | ORIGINAL_REQUEST §R4 |
| 12 | Merkle DAG Hash Lineage | Cryptographically link Phase 297 summary hash `257f83f7...` in `artifacts/research/phase298/` | M4 | ORIGINAL_REQUEST §R4 |
| 13 | FastAPI Canary Mining Endpoint | Read-only `GET /api/v1/canary/strategy-mining` and updated `summary` endpoint | M4 | ORIGINAL_REQUEST §R5 |
| 14 | DaisyUI Dashboard Mining View | `strategy-mining-page.tsx` rendering 5 required panels under route `#/mining` | M5 | ORIGINAL_REQUEST §R5 |
| 15 | Paper-Safe Confinement | Enforce `EXECUTION AUTHORITY: OFF`, 0 exchange calls, 0 credentials loaded | M1-M6 | ORIGINAL_REQUEST §R6 |
| 16 | Deterministic 4-Track Runner | `scripts/run_phase_298_strategy_mining.py` executing 4 deterministic tracks | M6 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Strategy Mining & Mutation Engine | `strategy_mining.py`, `contracts.py`, 5-gate evaluator, unit tests | none | DONE |
| 2 | Candidate Promotion & Atomic Hot-Reload | `DynamicStrategyMiner`, manifest v3 update, daemon hot-reloader, open-trade immutability | M1 | DONE |
| 3 | Zero-Drift Ledger, Merkle DAG & API | Double-entry balance reconciliation ($|\Delta| < 10^{-15}$ USDT), Merkle DAG link, `canary.py`, `app.py` | M2 | DONE |
| 4 | DaisyUI Frontend Dashboard & Routing | `strategy-mining-page.tsx`, `App.tsx`, `navigation.ts`, `api.ts`, Vitest test suite | M3 | DONE |
| 5 | 4-Track Verification Runner & Quality Gates | `scripts/run_phase_298_strategy_mining.py`, artifacts packaging, quality gates verification | M1-M4 | DONE |

## Interface Contracts

### 1. `MicrostructureMutationEngine`
```python
class MicrostructureMutationEngine:
    def __init__(self, seed: int = 42) -> None: ...
    def mutate(self, parent: CreatorCandidateArtifact, generation: int) -> CreatorCandidateArtifact: ...
    def create_msm_candidate(self, symbol: str, lookback: int, entry_z: float, stop_atr: float) -> CreatorCandidateArtifact: ...
```

### 2. `ContinuousOOSGateEvaluator`
```python
class ContinuousOOSGateEvaluator:
    def evaluate(self, candidate: CreatorCandidateArtifact, windows: list[WalkForwardWindow]) -> OOSGateResult: ...
    def evaluate_microstructure_resilience(self, candidate: CreatorCandidateArtifact) -> ResilienceGateResult: ...
```

### 3. `DynamicStrategyMiner`
```python
class DynamicStrategyMiner:
    def __init__(self, registry_path: Path, research_dir: Path) -> None: ...
    def run_mining_cycle(self, symbol: str, n_candidates: int = 5) -> MiningCycleSummary: ...
    def promote_candidate(self, result: QualifiedCandidateResult) -> CandidateRegistryManifest: ...
```

### 4. API & Merkle DAG Contract
- Endpoint: `GET /api/v1/canary/strategy-mining`
- Response Model: `CanaryStrategyMiningResponse`
- Merkle Parent: `phase297_summary_hash = "257f83f794465f3b89bfd9dbc25a2bf949d9fe315ecd97e2108c027ca3475668"`
- Ledger Invariant: $|\text{Cash} + \text{Margin} + \text{Unrealized} - (\text{Equity} + \text{Realized})| < 10^{-15}\text{ USDT}$

## Code Layout
- `src/autonomous_futures/feed/strategy_mining.py`: Core mining, mutation engine, OOS evaluator, dynamic miner
- `src/autonomous_futures/domain/contracts.py`: Extension for `microstructure_momentum` strategy family
- `src/autonomous_futures/api/canary.py`: Response models and verified loader for strategy mining
- `src/autonomous_futures/api/app.py`: Endpoint registration for `GET /api/v1/canary/strategy-mining`
- `frontend/src/lib/navigation.ts`: Route `'mining'`, hash `#/mining`
- `frontend/src/components/strategy-mining-page.tsx`: DaisyUI 5.7.42 dashboard component
- `frontend/src/App.tsx`: Navigation sidebar link and component view mounting
- `scripts/run_phase_298_strategy_mining.py`: Deterministic 4-track runner
- `tests/unit/test_phase_298_strategy_mining.py`: Core backend unit tests
- `tests/unit/test_phase_298_strategy_mining_api.py`: API endpoint unit tests
- `frontend/src/components/__tests__/strategy-mining-page.test.tsx`: Vitest dashboard tests
