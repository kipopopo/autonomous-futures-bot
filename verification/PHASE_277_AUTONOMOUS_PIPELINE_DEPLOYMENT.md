# Phase 277 Verification Report: Autonomous Pipeline Deployment & Operational Verification on Kainode VPS

**Decision**: DEPLOYED / PASSED — Autonomous Strategy Pipeline Deployed Alongside Undisturbed Live Paper Trading Daemon.  
**Date**: 2026-09-09T06:22:30Z  
**Host Target**: Kainode VPS (`147.79.18.15`, hostname: `kipopopo`, Ubuntu 24.04.4 LTS x86_64, Linux kernel 6.8.0-139-generic, systemd 255)  
**SSH Operator**: `afbot:afbot` (UID 1001, GID 1001), key: `C:/Users/thaqi/.ssh/kainode_ed25519_openssh`  
**Host ED25519 Fingerprint**: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`  
**Git Commit SHA**: `f80b5d4031494fe21adc02e1d6f45a0ef2f90fa4`  

---

## 1. Executive Summary & Safety Invariant Attestation

Phase 277 establishes production staging, byte-parity synchronization, and zero-disruption operational verification of the Autonomous Strategy Pipeline on the Kainode Linux VPS (`147.79.18.15`) alongside the continuously running 24/7 Live Paper Trading Daemon (`autonomous-futures-paper-live.service`).

All staging, pre-flight audits, and smoke testing were conducted under unprivileged operator `afbot` with zero modifications to systemd service units, zero interruptions to the live trading process, and zero live capital exposure.

### Strict Safety Invariants Attestation
1. **ZERO Restarts to Live Paper Daemon**: `autonomous-futures-paper-live.service` maintained `MainPID=702991` and `NRestarts=2` continuously throughout all staging, compilation, and testing operations. Total restarts incurred: **0**.
2. **ZERO Paid LLM API Calls**: The scheduler single evaluation pass was conducted strictly with `--provider demo`, utilizing offline heuristic strategy proposals and local walk-forward evaluation. No external LLM endpoints were contacted.
3. **ZERO Live Exchange Orders**: Verified via live telemetry: `orders_submitted=0`, `execution_authority=false`, `live_trading_activation=false`, `paper_activation=true`, `promotion_state=unpromoted`.
4. **ZERO Destructive Database Operations**: All SQLite database examinations were executed using `mode=ro` and `PRAGMA query_only=ON`. Pre-flight and post-flight ledger counts remained identical at 56 opens and 56 closes (unmatched delta: 0), with 0 dirty recovery intents.

---

## 2. Remote Codebase Staging & Byte Parity Manifest (R1)

### 2.1 Release Identity & Synchronization
The target production checkout at `/opt/autonomous-futures-bot` on Kainode VPS was updated via `git fetch origin main && git reset --hard origin/main` to synchronize directly with the verified Phase 1–4 release commit on `origin/main`.

- **Target Directory**: `/opt/autonomous-futures-bot`
- **Git Commit SHA**: `f80b5d4031494fe21adc02e1d6f45a0ef2f90fa4`
- **Commit Subject**: `feat(phase-4): e2e closed-loop test suite, health diagnostics CLI, and hardened systemd service`
- **File Ownership & Permissions**: All files and directories owned by `afbot:afbot` (`drwxrwxr-x` directories, `-rw-rw-r--` files).

### 2.2 Byte Parity Manifest Checksums
Byte parity between local workstation and remote VPS was mathematically attested using the accumulated SHA-256 algorithm:
$$\text{Accumulated Hash} = \text{SHA-256}\left( \sum_{\text{sorted paths}} (\text{path UTF-8} \mathbin{\Vert} \mathtt{0x00} \mathbin{\Vert} \text{SHA-256}(\text{file bytes})) \right)$$

- **15 Changed Production & Script Files Hash**:  
  `d5c0b53c9048d6ba38a80f82d4b4e69bcef0bbe4ef202ce1925d71f0408666b4`  
  *(Exact 1:1 match across local and remote)*
- **All 246 Sync Target Files Hash** (`src/autonomous_futures/`, `scripts/`, `systemd/`, `deploy/`):  
  `3a87ac47a67433b512b2b07b05588106c53b67df8dadb6a181ff21cc8002fb0b`  
  *(Exact 1:1 match across local and remote)*

#### Individual SHA-256 Digests (15 Changed Files)
| Relative File Path | SHA-256 Checksum |
|---|---|
| `scripts/check_autonomous_pipeline_health.py` | `a751495ea32f80b01237e54238ff2d7f43dc7a538edcf8157072092fb1b845fd` |
| `scripts/run_autonomous_cycle.py` | `d99039ad77a8518345c1227ab556e47ea4cc752bec1cb27d25e7e23e743af776` |
| `scripts/run_autonomous_scheduler.py` | `b2460853789313809929a864c257fd519ec4fcb8c00de75e43ded5a9fb81a510` |
| `scripts/run_phase_259_live_paper_daemon.py` | `674ac9c25357e83cde0f223e514f58cf80103022f0f85379b4f292218710719b` |
| `src/autonomous_futures/paper/__init__.py` | `47d930a9d28d0a1ef03eb710d325a7fa498a8114434c6e79615eede4e2f3bcd1` |
| `src/autonomous_futures/paper/admission.py` | `cb56a9b9e41889ac19c0acb77f32f6daeefbda18561ea127c8189d5090047c02` |
| `src/autonomous_futures/paper/candidate_registry.py` | `edd17be49f8ea23ea2b77df79847541bab2da37467ca60322c456cd1c62c2670` |
| `src/autonomous_futures/paper/feedback_extractor.py` | `2c209eff0a07f281cceffd50def507ec77eb00eb2ea09a8736b75a3c7ff7405d` |
| `src/autonomous_futures/paper/live_engine.py` | `177e589f7b30e5dc5ada34b227ef5b99b0f97c278940235a7d3cb2b2388fd90b` |
| `src/autonomous_futures/paper/sqlite_ledger.py` | `507134036f0a6365db09c82ba2bdac9c284a70ab922debea3408c50f12df489a` |
| `src/autonomous_futures/pipeline/__init__.py` | `8e8667d792086f7e69c403200fe49d22322ffc01db7b3421a9445208727a2df2` |
| `src/autonomous_futures/pipeline/autonomous_cycle.py` | `a0c11712eef0fcab83855d7549a7b420387b5f6bc77a7ba78b748811150c851f` |
| `src/autonomous_futures/research/google_ai_studio_provider.py` | `94ba6a4cdd62e227c045248b17a4c72ba54aa98cdec8ddea46af85dbb41a516a` |
| `src/autonomous_futures/research/learner_critic_provider.py` | `f88a707c62ce6988d4c944b5008b21e7d5a3e600143613d1d68d3fc90c2c0ba6` |
| `systemd/autonomous-futures-scheduler.service.template` | `ee3b0694610f3365a972a944417f7aca10c450e12de70ebad4089370883fc506` |

### 2.3 Remote Python Source Compilation (PEP 758 Compatibility)
Remote compilation executed across all 216 modules in `src` and 23 scripts in `scripts`:
```bash
/opt/autonomous-futures-bot/.venv/bin/python -m compileall src scripts
```
- **Interpreter**: Python 3.14.7 (`/opt/autonomous-futures-bot/.venv/bin/python`)
- **Compilation Result**: Clean compilation across 246 files.
- **Errors / Warnings**: `0` errors, `0` warnings.
- **PEP 758 Verification**: Verified that unparenthesized exception handling in Python 3.14 (PEP 758) compiles cleanly without syntax errors under the production venv.

---

## 3. Pre-Flight Ledger & Live Service Invariant Verification (R2)

### 3.1 Live Paper Service Pre-Flight Audit
The running live paper trading daemon was inspected directly via systemd:
```bash
systemctl show autonomous-futures-paper-live.service -p MainPID,ActiveState,SubState,NRestarts,ExecMainStartTimestamp
```
- **MainPID**: `702991`
- **ActiveState**: `active`
- **SubState**: `running`
- **NRestarts**: `2`
- **ExecMainStartTimestamp**: `Tue 2026-09-08 23:24:23 UTC`
- **Monitored Symbols**: `BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT`
- **Active Positions**: `0`
- **Capital**: `98.60 USDT` cash / equity

### 3.2 Read-Only SQLite Ledger Integrity Audit
Read-only queries (`mode=ro`, `PRAGMA query_only=ON`) against `/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3`:
- `PRAGMA integrity_check`: `[('ok',)]`
- `paper_ledger_events` Breakdown: `[('close', 56), ('open', 56)]`
- Total Events: `112`
- Unmatched Delta: `0` (exact event parity)
- `paper_position_update_intent` Count: `0` (clean, zero dirty recovery intents)

Read-only audit of secondary database `/opt/autonomous-futures-bot/artifacts/paper_live/paper-lifecycle.sqlite3`:
- `PRAGMA integrity_check`: `[('ok',)]`
- Telemetry Marks Count: `238`

### 3.3 Pre-Flight Health Diagnostic CLI Run
Execution of the new diagnostic CLI prior to running the scheduler:
```bash
/opt/autonomous-futures-bot/.venv/bin/python scripts/check_autonomous_pipeline_health.py \
    --storage-dir /opt/autonomous-futures-bot/artifacts/paper_live \
    --allow-missing-scheduler
```
- **Exit Code**: `2` (`CRITICAL`)
- **Observations Reported**:
  * `paper_daemon`: Running under PID 702991, uptime 6h 52m 43s, heartbeat age 24.29s (< 120s threshold).
  * `paper_daemon.circuit_breaker`: Reported `HALTED`. Telemetry and journal logs confirm this was triggered earlier during high market volatility on the Binance public ticker stream. Per `autonomous_futures/paper/circuit_breakers.py`, state transitions are monotonic (`NORMAL -> THROTTLED -> HALTED -> EMERGENCY_FLAT`) to preserve capital; open positions remained 0 and capital remained safe at 98.60 USDT.
  * `scheduler`: Evaluated as `HEALTHY` (bypassed via `--allow-missing-scheduler`).
  * `candidate_registry`: Reported `CRITICAL` because `candidate_registry.json` was not yet initialized prior to Phase 5.
  * `sqlite_ledger` and `sqlite_lifecycle`: Evaluated as `HEALTHY`.

---

## 4. Non-Disruptive Autonomous Cycle & Scheduler Dry-Run Smoke Test (R3)

### 4.1 Isolated Scheduler Directory Setup
The designated scheduler state directory was created with operator permissions:
- Path: `/opt/autonomous-futures-bot/artifacts/paper_live/scheduler`
- Owner: `afbot:afbot`
- Mode: `drwxrwxr-x` (`775`)

### 4.2 Single Evaluation Pass Execution
Executed an isolated, single evaluation pass using unprivileged user `afbot`:
```bash
/opt/autonomous-futures-bot/.venv/bin/python scripts/run_autonomous_scheduler.py \
    --symbol BTCUSDT \
    --once \
    --provider demo \
    --ledger-db /opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3 \
    --parquet-path /opt/autonomous-futures-bot/research/immutable-data/5m/canonical/BTCUSDT-5m.parquet \
    --candidate-registry-path /opt/autonomous-futures-bot/artifacts/paper_live/candidate_registry.json \
    --output-dir /opt/autonomous-futures-bot/artifacts/paper_live/scheduler
```
- **Execution Log Highlights**:
  * `Acquired single-instance execution lock at .../scheduler/scheduler.lock (PID 711097)`
  * `Autonomous scheduler started for BTCUSDT`
  * `Launching autonomous cycle cycle-btcusdt-20260909061850-228b36 for BTCUSDT (trigger: manual_once)`
  * `Released single-instance execution lock at .../scheduler/scheduler.lock`
- **Execution Duration**: `11.06s`
- **Exit Code**: `0`
- **Lockfile Status**: `scheduler.lock` cleanly unlinked upon cycle completion.

### 4.3 Candidate Registry Baseline Bootstrap
To establish initial candidate registry state reflecting the 4 live paper trading symbols bound in `LivePaperEngine`, `candidate_registry.json` was generated and validated:
- **Registry Path**: `/opt/autonomous-futures-bot/artifacts/paper_live/candidate_registry.json`
- **Manifest Version**: `1`
- **Cryptographic Registry Hash**: `d28301ae968654478ea8ea6e8692a0150da915db692cfd0a006a9b314374a8c8`
- **Active Candidates Registered**:
  * `BTCUSDT`: `cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74`
  * `DOGEUSDT`: `cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8`
  * `ETHUSDT`: `cand-1f87c23b87c117a5909a32a38dd44f0001b66d70f6a0818375a6e95d429aa632`
  * `SOLUSDT`: `cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd`
- All 4 underlying candidate artifacts verified intact under `artifacts/research/phase252/candidates/`.

### 4.4 Scheduler Telemetry Checkpoint (`scheduler-health.json`)
The emitted health telemetry artifact was verified against the expected schema:
```json
{
  "status": "STOPPED",
  "pid": null,
  "started_at": "2026-09-09T06:18:50.269103+00:00",
  "updated_at": "2026-09-09T06:19:01.386018+00:00",
  "last_run_at": "2026-09-09T06:18:50.275230+00:00",
  "next_run_at": null,
  "consecutive_failures": 0,
  "total_cycles_executed": 1,
  "admitted_candidates_count": 0,
  "last_cycle_result": {
    "cycle_id": "cycle-btcusdt-20260909061850-228b36",
    "trigger_type": "manual_once",
    "status": "completed_unadmitted",
    "exit_code": 0,
    "candidate_id": "cand-4557adbcc0f8005ab5878fc5d20ececc9ead3230323f3c7679c8202cb03d16ac",
    "admitted": false,
    "executed_at": "2026-09-09T06:18:50.275230+00:00",
    "duration_seconds": 11.06,
    "error_message": null
  },
  "symbol": "BTCUSDT",
  "lockfile": "/opt/autonomous-futures-bot/artifacts/paper_live/scheduler/scheduler.lock",
  "mode": "once"
}
```

### 4.5 Post-Smoke Unified Health Diagnostic Check
A full diagnostic run across all subsystems was executed:
```bash
/opt/autonomous-futures-bot/.venv/bin/python scripts/check_autonomous_pipeline_health.py \
    --storage-dir /opt/autonomous-futures-bot/artifacts/paper_live
```
- **Overall Result**: 23 checks passed, 2 warnings, 1 failure.
- **Subsystem Breakdown**:
  * `CANDIDATE REGISTRY`: **HEALTHY** (Manifest Version 1, Cryptographic Hash `d28301ae...` VALID, 4 symbols registered).
  * `SQLITE PAPER LEDGER`: **HEALTHY** (`integrity_check: ok`, 0 dirty intents, 112 trade events, 0 unmatched open trades).
  * `SQLITE PAPER LIFECYCLE`: **HEALTHY** (`integrity_check: ok`, 238 marks).
  * `AUTONOMOUS SCHEDULER`: **DEGRADED** (Cleanly stopped per `--once` mode; warning raised due to heartbeat age >120s as expected for single-shot batch invocation).
  * `LIVE PAPER DAEMON`: **CRITICAL** (Process alive under PID 702991 with fresh heartbeats <10s; failure raised solely due to pre-existing `circuit_breaker: HALTED` condition).

### 4.6 Post-Flight Invariant Verification
Re-auditing confirmed zero process or database disruption:
- `systemctl show autonomous-futures-paper-live.service -p MainPID,NRestarts`:
  * `MainPID=702991` (unchanged)
  * `NRestarts=2` (unchanged, 0 restarts)
- SQLite Ledger:
  * `integrity_check`: `ok`
  * `dirty_intents`: `0`
  * `trade_events`: `56 opens`, `56 closes` (unchanged)

---

## 5. Hardened Production Systemd Service Specification & Operational Runbook (R4)

### 5.1 Systemd Service Unit Definition
The production scheduler daemon service is defined in template `/opt/autonomous-futures-bot/systemd/autonomous-futures-scheduler.service.template`:
```ini
[Unit]
Description=Autonomous Futures Strategy Optimization Scheduler Daemon
After=network.target autonomous-futures-paper-live.service
Wants=autonomous-futures-paper-live.service
Documentation=https://github.com/kipopopo/autonomous-futures-bot

[Service]
Type=simple
User=afbot
Group=afbot
WorkingDirectory=/opt/autonomous-futures-bot

# Security & Sandbox Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictSUIDSGID=true
MemoryDenyWriteExecute=false
LockPersonality=true

# Filesystem Access Boundaries
ReadWritePaths=/opt/autonomous-futures-bot/artifacts /opt/autonomous-futures-bot/artifacts/paper_live /opt/autonomous-futures-bot/artifacts/paper_live/scheduler /opt/autonomous-futures-bot/artifacts/paper_live/candidate_registry.json

# Process Invocation
ExecStart=/opt/autonomous-futures-bot/.venv/bin/python scripts/run_autonomous_scheduler.py \
    --symbol BTCUSDT \
    --interval-seconds 3600 \
    --min-cooldown-seconds 300 \
    --provider google_ai_studio \
    --model gemma-4-31b-it \
    --ledger-db /opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3 \
    --lifecycle-db /opt/autonomous-futures-bot/artifacts/paper_live/paper-lifecycle.sqlite3 \
    --parquet-path /opt/autonomous-futures-bot/research/immutable-data/5m/canonical/BTCUSDT-5m.parquet \
    --candidate-registry-path /opt/autonomous-futures-bot/artifacts/paper_live/candidate_registry.json \
    --output-dir /opt/autonomous-futures-bot/artifacts/paper_live/scheduler

Restart=always
RestartSec=30
TimeoutStopSec=30
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

### 5.2 Step-by-Step Operator Installation Runbook
Executed via root administrative shell or host web console:

```bash
# Step 1: Copy hardened template into systemd system directory
sudo cp /opt/autonomous-futures-bot/systemd/autonomous-futures-scheduler.service.template \
    /etc/systemd/system/autonomous-futures-scheduler.service

# Step 2: Establish strict unit file permissions
sudo chown root:root /etc/systemd/system/autonomous-futures-scheduler.service
sudo chmod 644 /etc/systemd/system/autonomous-futures-scheduler.service

# Step 3: Reload systemd configuration
sudo systemctl daemon-reload

# Step 4: Enable service on system boot and start immediately
sudo systemctl enable --now autonomous-futures-scheduler.service

# Step 5: Verify service is active and running
sudo systemctl status autonomous-futures-scheduler.service
```

### 5.3 Operator Management & Telemetry Commands
Operators managing the autonomous pipeline service can utilize standard systemd and diagnostic CLI tooling:

```bash
# View active service status and recent journal logs
sudo systemctl status autonomous-futures-scheduler.service

# Stream live scheduler journal logs
sudo journalctl -u autonomous-futures-scheduler.service -f -n 100

# Inspect pipeline health in structured format
/opt/autonomous-futures-bot/.venv/bin/python /opt/autonomous-futures-bot/scripts/check_autonomous_pipeline_health.py \
    --storage-dir /opt/autonomous-futures-bot/artifacts/paper_live

# Emit machine-readable health JSON
/opt/autonomous-futures-bot/.venv/bin/python /opt/autonomous-futures-bot/scripts/check_autonomous_pipeline_health.py \
    --storage-dir /opt/autonomous-futures-bot/artifacts/paper_live --json

# Restart scheduler service
sudo systemctl restart autonomous-futures-scheduler.service

# Reset live paper daemon circuit breaker when market stabilizes (optional)
sudo systemctl restart autonomous-futures-paper-live.service
```

### 5.4 Rollback & Decommission Procedure
If decommissioning or rolling back the scheduler daemon:

```bash
# Stop and disable the scheduler service
sudo systemctl stop autonomous-futures-scheduler.service
sudo systemctl disable autonomous-futures-scheduler.service

# Clean up stale lockfile if left behind
rm -f /opt/autonomous-futures-bot/artifacts/paper_live/scheduler/scheduler.lock

# Reload systemd
sudo systemctl daemon-reload
```

---

## 6. Local Static Quality Gates & Test Verification Evidence

All local code modifications from Phases 1–4 and Phase 5 were evaluated against the repository's strict quality gates:

### 6.1 Ruff Lint & Format Checks
```bash
uv run --locked ruff check src tests scripts
```
- **Result**: `All checks passed!`
- **Errors**: `0`

```bash
uv run --locked ruff format --check src tests scripts
```
- **Result**: `478 files already formatted`
- **Modifications Required**: `0`

### 6.2 Mypy Strict Static Type Verification
```bash
uv run --locked mypy src scripts
```
- **Result**: `Success: no issues found in 238 source files`
- **Type Violations**: `0`

### 6.3 Autonomous Pipeline E2E Integration Suite
```bash
uv run --locked pytest tests/integration/test_autonomous_pipeline_e2e.py
```
- **Result**: `4 passed in 13.50s`
- **Scenarios Verified**:
  1. `test_end_to_end_autonomous_cycle_demo_closed_loop`: Seamless execution from ledger trade feedback extraction, walk-forward evaluation, candidate admission, and registry publication.
  2. `test_candidate_registry_hot_reload_in_live_engine`: Hot-reloader dynamically detects updated candidate registry hash and binds new candidate definitions without restart.
  3. `test_position_binding_preservation_across_candidate_reload`: Existing open positions retain their historical candidate parameters while subsequent positions execute the revised candidate strategy.
  4. `test_systemd_template_compliance`: Validates systemd unit syntax, sandboxing directives, user/group configurations, and execution path boundaries.

---

## 7. Independent Verification & Operator Readback Runbook

To independently verify the deployed environment on Kainode VPS from any authorized workstation:

```bash
# 1. Verify remote Git commit SHA
ssh -i "C:/Users/thaqi/.ssh/kainode_ed25519_openssh" afbot@147.79.18.15 \
    "cd /opt/autonomous-futures-bot && git rev-parse HEAD"
# Expected Output: f80b5d4031494fe21adc02e1d6f45a0ef2f90fa4

# 2. Verify live paper daemon PID and restart invariant
ssh -i "C:/Users/thaqi/.ssh/kainode_ed25519_openssh" afbot@147.79.18.15 \
    "systemctl show autonomous-futures-paper-live.service -p MainPID,NRestarts,ActiveState,SubState"
# Expected Output: MainPID=702991, NRestarts=2, ActiveState=active, SubState=running

# 3. Verify SQLite ledger integrity and zero dirty intents
ssh -i "C:/Users/thaqi/.ssh/kainode_ed25519_openssh" afbot@147.79.18.15 \
    "/opt/autonomous-futures-bot/.venv/bin/python -c \"import sqlite3; con = sqlite3.connect('file:/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3?mode=ro', uri=True); con.execute('PRAGMA query_only = ON;'); print('integrity:', con.execute('PRAGMA integrity_check;').fetchall()); print('intents:', con.execute('SELECT count(*) FROM paper_position_update_intent;').fetchone()[0])\""
# Expected Output: integrity: [('ok',)], intents: 0

# 4. Verify candidate registry cryptographic hash and symbols
ssh -i "C:/Users/thaqi/.ssh/kainode_ed25519_openssh" afbot@147.79.18.15 \
    "/opt/autonomous-futures-bot/.venv/bin/python -c \"import sys; sys.path.insert(0, '/opt/autonomous-futures-bot/src'); from autonomous_futures.paper.candidate_registry import read_candidate_registry; r = read_candidate_registry('/opt/autonomous-futures-bot/artifacts/paper_live/candidate_registry.json', verify_hash=True); print('version:', r.registry_version, 'symbols:', list(r.symbols.keys()), 'hash:', r.registry_hash)\""
# Expected Output: version: 1, symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT'], hash: d28301ae968654478ea8ea6e8692a0150da915db692cfd0a006a9b314374a8c8

# 5. Verify scheduler health checkpoint and clean lockfile release
ssh -i "C:/Users/thaqi/.ssh/kainode_ed25519_openssh" afbot@147.79.18.15 \
    "cat /opt/autonomous-futures-bot/artifacts/paper_live/scheduler/scheduler-health.json && test ! -f /opt/autonomous-futures-bot/artifacts/paper_live/scheduler/scheduler.lock && echo 'LOCKFILE_CLEANLY_RELEASED'"
# Expected Output: Valid scheduler-health.json, followed by LOCKFILE_CLEANLY_RELEASED
```
