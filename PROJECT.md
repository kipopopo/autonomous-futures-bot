# Project: Phase 309 — Autonomous Live Production Launch & Micro-Capital Self-Driving Trading Engine

## Architecture
Phase 309 unifies all preceding canary engineering phases (Phases 292–308) into a live self-driving production trading engine operating under strict micro-capital confinement boundaries:
1. **Micro-Capital Confinement & Real-Time Trading Loop**:
   - Dynamic micro-order slicing ($\le 5.00$ USDT per slice) quantized by exchange step-size with Binance `MIN_NOTIONAL` compliance.
   - Aggregate exposure ceiling ($\le 25.00$ USDT) across active candidate assets (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`).
   - Unencumbered cash reserve floor ($\ge 75.0\%$).
   - Strict intra-day loss ceiling ($\le 3.00$ USDT) with fail-closed auto-flattening.
2. **Multi-Horizon Alpha Ensemble & Hawkes Risk Interlocks**:
   - Real-time signals across `BTCUSDT`, `ETHUSDT`, `SOLUSDT` combining Micro (1s–5s), Short (1m–5m), and Medium (15m–1h) horizons with regime-conditioned weights and conflict shading.
   - Hawkes spectral radius cutoff ($\rho \ge 1.0$) with instantaneous cascade suppression (< 1 ms).
   - Feed SLA gateway freshness ($\le 500$ ms).
3. **Double-Entry Solvency Bookkeeping**:
   - $\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} \equiv \text{Starting Equity} + \text{Realized PnL}$
   - Invariant tolerance $|\text{drift}| < 10^{-15}$ USDT.
4. **Multi-Sig Governance & Hardware/OS Kill-Switch Interlock**:
   - 2-of-3 M-of-N cryptographic quorum verification (`CRO`, `SEC`, `DEV`) with monotonic nonce replay prevention.
   - 3-tier emergency kill switch (Level 1: Soft Pause, Level 2: Lockout, Level 3: Hardware Panic with credential memory wipe).
   - Signal trapping (`SIGINT`, `SIGTERM`) and token tripwire file (`emergency_kill.lock`).
5. **Cryptographic Merkle DAG verification**:
   - Upstream hash: `65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e` (Phase 308).
   - Verification runner script: `scripts/run_phase_309_autonomous_launch.py` and `scripts/run_phase_309_production_launch.py`.
   - Immutable research artifacts in `artifacts/research/phase309/`.
6. **Observational Backend API & DaisyUI 5.7.42 Dashboard**:
   - Read-only FastAPI endpoint `GET /api/v1/canary/production-launch`.
   - Frontend dashboard component (`production-launch-page.tsx`) under route `#/production-launch` with status banner, KPI cards, allocation matrix, kill-switch panel, and double-entry solvency meter.

```
                    [Binance USDⓈ-M Live Feeds (BTC, ETH, SOL)]
                                      │
                                      ▼
                        [SelfDrivingTradingEngine]
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
 [Feed SLA Gate]            [Hawkes Cascade Gate]        [Multi-Horizon Ensemble]
  (Age <= 500 ms)               (rho < 1.0)              (Micro / Short / Med)
         │                            │                            │
         └────────────────────────────┼────────────────────────────┘
                                      ▼
                        [Pre-Trade Risk Confinement]
                       ├── Micro Slicing (<= 5.00 USDT)
                       ├── Aggregate Cap (<= 25.00 USDT)
                       ├── Cash Reserve (>= 75.0%)
                       └── Loss Ceiling (<= 3.00 USDT Auto-Flatten)
                                      │
                                      ▼
                      [Multi-Sig & Kill-Switch Interlock]
                       ├── 2-of-3 Quorum (CRO, SEC, DEV)
                       ├── 3-Tier Kill Switch (L1 / L2 / L3)
                       └── File Tripwire (emergency_kill.lock)
                                      │
                                      ▼
                      [Double-Entry Solvency Ledger]
                       ├── Assets == Obligations
                       └── |drift| < 10^-15 USDT
                                      │
                                      ▼
                      [Cryptographic Merkle DAG Chain]
                       ├── Upstream Hash: 65c2e7d2... (Phase 308)
                       └── Phase 309 Artifacts & Merkle Root
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Micro-Order Sizing & Slicing | Quantize child orders <= 5.00 USDT with step size and MIN_NOTIONAL compliance | M1 | ORIGINAL_REQUEST §1 |
| 2 | Aggregate Exposure Ceiling | Total active exposure strictly <= 25.00 USDT across BTC, ETH, SOL | M1 | ORIGINAL_REQUEST §1 |
| 3 | Unencumbered Cash Reserve Floor | Maintain >= 75.0% liquid unencumbered cash buffer at all times | M1 | ORIGINAL_REQUEST §1 |
| 4 | Intra-Day Loss Ceiling & Flattening | Accumulate intra-day loss; if >= 3.00 USDT, fail-closed emergency flatten | M1 | ORIGINAL_REQUEST §1 |
| 5 | Multi-Horizon Alpha Ensemble | Micro (1s-5s), Short (1m-5m), Medium (15m-1h) signals across BTC, ETH, SOL | M1 | ORIGINAL_REQUEST §2 |
| 6 | Hawkes Spectral Radius Cutoff | If rho >= 1.0, instantly suppress order dispatch (< 1 ms reaction time) | M1 | ORIGINAL_REQUEST §2 |
| 7 | Feed SLA Heartbeat Gate | Heartbeat latency <= 500 ms gate before processing ticks | M1 | ORIGINAL_REQUEST §2 |
| 8 | Double-Entry Solvency Ledger | Exact balance reconciliation with \|drift\| < 1e-15 USDT | M1 | ORIGINAL_REQUEST §3 |
| 9 | Multi-Sig Governance (2-of-3) | HMAC-SHA256 quorum verification across CRO, SEC, DEV with anti-replay nonces | M1 | ORIGINAL_REQUEST §4 |
| 10 | 3-Tier Emergency Kill-Switch | Soft Pause, Lockout, and Hardware Panic with credential memory wipe | M1 | ORIGINAL_REQUEST §4 |
| 11 | OS Signal & Token Tripwire | Trapping SIGINT/SIGTERM and monitoring emergency_kill.lock file | M1 | ORIGINAL_REQUEST §4 |
| 12 | Cryptographic Merkle DAG Chain | Upstream hash 65c2e7d2... link; generate artifacts in artifacts/research/phase309/ | M1 | ORIGINAL_REQUEST §5 |
| 13 | Autonomous Launch Runner Script | scripts/run_phase_309_autonomous_launch.py with verification & simulation modes | M1 | ORIGINAL_REQUEST §7 |
| 14 | Observational FastAPI API | GET /api/v1/canary/production-launch returning validated launch telemetry | M1 | ORIGINAL_REQUEST §7 |
| 15 | DaisyUI Production Launch Dashboard | React component, navigation tab (#/production-launch), and Vitest test suite | M2 | ORIGINAL_REQUEST §7 |
| 16 | Comprehensive Test Suite & Quality Gates | Targeted pytest, ruff check, ruff format --check, mypy src scripts, Vitest | M3 | ORIGINAL_REQUEST §7 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Core Backend Engine, Runner & Quality Gate Fixes | Fix mypy type errors in kill_switch.py & self_driving.py, format code with ruff, provide scripts/run_phase_309_autonomous_launch.py | none | COMPLETED |
| 2 | Frontend Mission Control Dashboard & Telemetry | Implement production-launch-page.tsx, canary.ts types, api.ts fetcher, navigation route, Vitest suite, and App.tsx tab | M1 | COMPLETED |
| 3 | Comprehensive Testing & Verification Suite | Targeted pytest suite, runner verification, and Vitest suite execution | M2 | COMPLETED |
| 4 | Static Quality Gates & Forensic Integrity Audit | ruff check, ruff format --check, mypy src scripts, targeted pytest, npm run test/build, and forensic auditor sign-off | M3 | COMPLETED |

## Interface Contracts

### 1. `SelfDrivingTradingEngine`
```python
class SelfDrivingTradingEngine:
    def __init__(self, config: MicroCapitalConfig, output_dir: Path) -> None: ...
    def run_pre_flight_check(self) -> dict[str, Any]: ...
    def process_microstructure_tick(self, tick: MarketTick) -> Optional[SelfDrivingOrder]: ...
    def handle_kill_switch_trip(self, reason: str, level: KillSwitchLevel) -> None: ...
    def export_artifacts(self) -> dict[str, Any]: ...
```

### 2. `MultiSigGovernanceEngine` & `HardwareOSKillSwitchEngine`
```python
class MultiSigGovernanceEngine:
    def submit_proposal(self, action: GovernanceActionType, target: str, params: dict[str, Any], caller: SignerIdentity) -> GovernanceProposal: ...
    def vote_on_proposal(self, proposal_id: str, signer: SignerIdentity, vote: VoteType, signature_hex: str, nonce: int) -> GovernanceProposal: ...

class HardwareOSKillSwitchEngine:
    def trigger_soft_pause(self, reason: str) -> None: ...
    def trigger_lockout(self, reason: str) -> None: ...
    def trigger_hardware_panic(self, reason: str, source: str) -> None: ...
    def check_file_tripwire(self) -> bool: ...
```

### 3. API & Merkle DAG Contract
- Endpoint: `GET /api/v1/canary/production-launch`
- Response Model: `CanaryProductionLaunchResponse`
- Upstream Merkle Parent: `65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e`
- Phase 309 Merkle Root: `5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844`
- Solvency Ledger Invariant: $|\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} - (\text{Starting Equity} + \text{Realized PnL})| < 10^{-15}\text{ USDT}$

## Code Layout
- `src/autonomous_futures/production/self_driving.py`: Core production self-driving engine & micro-capital confinement
- `src/autonomous_futures/safety/kill_switch.py`: 2-of-3 multi-sig governance, 3-tier kill-switch & double-entry solvency ledger
- `src/autonomous_futures/feed/alpha_ensemble.py`: Multi-horizon alpha ensemble and regime blending
- `src/autonomous_futures/feed/hawkes_cascades.py`: Hawkes point process streaming and spectral radius calculation
- `src/autonomous_futures/api/canary.py`: FastAPI models and verified loader for Phase 309
- `src/autonomous_futures/api/app.py`: Endpoint registration for `GET /api/v1/canary/production-launch`
- `scripts/run_phase_309_autonomous_launch.py`: Primary CLI verification and simulation runner script
- `scripts/run_phase_309_production_launch.py`: Core production launch execution script
- `tests/unit/test_phase_309_self_driving.py`: Unit tests for micro-capital confinement, Hawkes cutoff, and solvency
- `tests/unit/test_phase_309_production_launch_api.py`: Unit tests for Phase 309 FastAPI endpoints
- `frontend/src/lib/canary.ts`: TypeScript data models for Phase 309 production launch
- `frontend/src/lib/api.ts`: API client functions for fetching production launch data
- `frontend/src/lib/navigation.ts`: Navigation routes and view definitions
- `frontend/src/components/production-launch-page.tsx`: DaisyUI 5.7.42 production launch view component
- `frontend/src/components/__tests__/production-launch-page.test.tsx`: Vitest component tests
- `frontend/src/App.tsx`: Navigation tab and component view registration
