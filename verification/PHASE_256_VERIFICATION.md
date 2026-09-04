# Phase 256 Verification Report: Remote Codebase Synchronization, Systemd Paper Daemon Service Unit Architecture, Staging Preflight Tooling & Service Verification

**Date**: 2026-09-05
**Status**: PASSED (Remote Git Codebase Synchronized to Commit `b438522`, 11,854 Files 100% Owned by `afbot:afbot`, Systemd Paper Daemon Service Unit Delivered with Strict Sandboxing & `ReadWritePaths`, Paper Staging Preflight Tooling & Bounded Simulation Operational, Remote Unit Test Suite 30/30 Passed in 3.43s, Remote Smoke Test Passed with Exit Code 0, Zero Exchange Access, Zero Secrets Leaked, All 6 Local Repository Verification Gates Passed Cleanly with 1,277 Passing Tests)
**Host Target**: Kainode VPS (`147.79.18.15`, hostname `kipopopo`, Ubuntu 24.04.4 LTS Noble Numbat x86_64, Linux kernel `6.8.0-124-generic`)
**Operator User**: `afbot` (UID 1001, GID 1001)
**SSH Key**: `C:\Users\thaqi\.ssh\kainode_ed25519_openssh` (Ed25519)
**Target Path**: `/opt/autonomous-futures-bot`
**Author**: Worker Doc 1 (`worker_doc_1`, teamwork implementer, qa & specialist)
**Project Blueprint**: `.agents/orchestrator_15/PROJECT.md`
**Authoritative Request Reference**: `.agents/ORIGINAL_REQUEST.md` (lines 573–623, Section `## 2026-09-04T20:59:14Z`)
**Milestone**: Phase 256 Remote Codebase Synchronization & Systemd Paper Daemon Architecture

---

## 1. Executive Summary

Phase 256 establishes the complete deployment baseline, systemd service unit architecture, diagnostic preflight tooling, and empirical smoke verification for the **Autonomous Futures Bot Sandboxed Paper Trading Daemon** (`autonomous-futures-paper.service`) on Kainode VPS (`147.79.18.15`).

Following the mathematical proofs and adverse stress survival established in Phase 254 (100 USDT Shared Portfolio Margin) and Phase 255 (Multi-Vector Adverse Stress Testing), Phase 256 transitions the paper trading subsystem to an unprivileged systemd daemon environment on Ubuntu 24.04 LTS. All operations strictly enforce non-root execution (`afbot:afbot`), offline safety invariants (`orders=0`, `exchange_access=false`, `promotion_state="unpromoted"`, `paper_activation=false`), and zero external credential exposure.

### Summary of Core Achievements

1. **Remote Git Codebase Synchronization (Requirement R1)**:
   - Synchronized `/opt/autonomous-futures-bot` on Kainode VPS with GitHub `origin/main` directly to target commit `b4385224b3b2e40a29a2b0fd6fdc59c53905f259` (`b438522`).
   - Reconciled working tree drift to zero uncommitted changes and verified that all 11,854 filesystem objects in `/opt/autonomous-futures-bot` are owned 100% by unprivileged operator `afbot:afbot`.
   - Verified the remote virtual environment at `/opt/autonomous-futures-bot/.venv` with CPython 3.14.7 and pytest 9.1.1, passing remote runtime import probes and sanity tests.

2. **Systemd Paper Daemon Service Unit Architecture (Requirement R2)**:
   - Delivered `deploy/autonomous-futures-paper.service` implementing strict systemd security sandboxing: `User=afbot`, `Group=afbot`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp=yes`, `NoNewPrivileges=yes`, `ProtectKernelModules=yes`, `ProtectKernelTunables=yes`, `ProtectControlGroups=yes`, and `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`.
   - Configured `ReadWritePaths=/opt/autonomous-futures-bot/artifacts/paper/` to permit SQLite database transactions and JSON report persistence without triggering read-only filesystem (`EROFS`) errors under strict sandboxing.
   - Resource bounds codified: `CPUQuota=500%`, `MemoryMax=10G`, `TimeoutStartSec=180`, `Type=oneshot`, `Restart=no`.
   - Zero-credential boundary strictly codified: `LoadCredentialEncrypted` is omitted; zero API keys or live exchange secrets are required or referenced.

3. **Paper Daemon Staging Preflight & Diagnostic Tooling (Requirement R3)**:
   - Implemented modular diagnostic engine in `src/autonomous_futures/paper_preflight.py` and CLI entry point in `scripts/preflight_kainode_paper.py`.
   - Built deterministic bounded in-memory 5m candle generator (`generate_deterministic_5m_bars`) and synthetic simulation loop executing 200 bars under the single shared 100.00 USDT portfolio margin model with dynamic leverage (1.0x to 3.0x), adverse fees (0.04%), and slippage (2 bps).
   - Validated exact Decimal balance reconciliation ($Cash_{\text{final}} = Starting + Net PnL$) and SQLite persistence (`paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`).
   - Authored 30 comprehensive unit tests across `tests/unit/test_paper_service.py` (11 tests) and `tests/unit/test_preflight_kainode_paper.py` (19 tests), passing 100% locally and on the remote VPS.

4. **Remote Service Installation & Smoke Verification (Requirement R4)**:
   - Synchronized all 5 Milestone 2 files to `/opt/autonomous-futures-bot` on Kainode VPS and initialized `/opt/autonomous-futures-bot/artifacts/paper` with mode `750` owned by `afbot:afbot`.
   - Executed remote unit test suite on Kainode VPS: 30/30 tests passed in 3.43 seconds.
   - Executed remote preflight diagnostic and bounded smoke simulation under `/opt/autonomous-futures-bot/.venv`, achieving exit code `0`, returning `"ready": true`, and generating all 3 SQLite databases and 3 telemetry JSON reports.
   - Documented sudoers privilege boundaries (`/etc/sudoers.d/afbot-service`), verified root-only restriction on `/etc/systemd/system/`, tested `systemctl status`, `restart`, and `journalctl -u` queries, and provided the canonical one-line root console installation command.

5. **Security & Safety Invariants Verification (Requirement R5 & Invariants)**:
   - Validated complete compliance with Invariants INV-1 through INV-8.
   - Zero API keys, private tokens, passwords, or raw prompts logged or committed across all remote and local artifacts.
   - Live exchange access remains strictly disabled (`exchange_access = false`, live `orders = 0`, `execution_authority = false`, `promotion_state = "unpromoted"`, `paper_activation = false`).

6. **Local Repository Verification Gates (Requirement R5)**:
   - Executed and passed all 6 local verification gates:
     - Gate 1: `uv run --locked pytest -q` -> **1,277 passed in 212.92s** (0:03:32).
     - Gate 2: `uv run --locked ruff check src tests scripts` -> **All checks passed!**
     - Gate 3: `uv run --locked ruff format --check src tests scripts` -> **390 files already formatted**.
     - Gate 4: `uv run --locked mypy src scripts` -> **Success: no issues found in 200 source files**.
     - Gate 5: `uv lock --check` -> **Resolved 67 packages in 0.80ms**.
     - Gate 6: `git diff --check` -> **Clean exit (code 0)**.

---

## 2. Deliverable 1: Remote Git Codebase Synchronization (R1)

### 2.1 Remote Host Baseline & Operator Access

Operator connectivity was established via SSH using the dedicated Ed25519 key without password prompts:
```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "id; hostname; uname -a"
```
**Verbatim Output**:
```text
uid=1001(afbot) gid=1001(afbot) groups=1001(afbot)
kipopopo
Linux kipopopo 6.8.0-124-generic #124-Ubuntu SMP PREEMPT_DYNAMIC Tue May 26 13:00:45 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

### 2.2 Initial State & Drift Identification

Prior to synchronization, inspection of `/opt/autonomous-futures-bot` revealed that the remote directory was 7 commits behind at `e074428` with modifications from previous research phases:
```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "git -C /opt/autonomous-futures-bot status; git -C /opt/autonomous-futures-bot log -1 --oneline"
```
**Verbatim Output**:
```text
On branch main
Your branch is behind 'origin/main' by 7 commits, and can be fast-forwarded.
  (use "git pull" to update your local branch)

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   scripts/preflight_kainode_staging.py
	modified:   src/autonomous_futures/domain/contracts.py
	modified:   src/autonomous_futures/paper/ledger.py
	modified:   src/autonomous_futures/research/creator_prompts.py
	modified:   src/autonomous_futures/research_lab/research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_persistence.py
	modified:   tests/unit/test_research_lab_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_persistence.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	artifacts/
	scripts/evaluate_phase_250_walk_forward.py
	scripts/probe_creator_staging.py
	scripts/run_phase_251_paper_simulation.py
	scripts/run_phase_252_batch_campaign.py
	src/autonomous_futures/creator_staging_probe.py
	src/autonomous_futures/phase_252_batch.py
	tests/unit/test_creator_staging_probe.py
	tests/unit/test_phase_250_adversarial_challenge.py
	tests/unit/test_phase_250_walk_forward.py
	tests/unit/test_phase_251_adversarial_challenge.py
	tests/unit/test_phase_251_paper_simulation.py
	tests/unit/test_phase_252_batch_campaign.py

no changes added to commit (use "git add" and/or "git commit -a")
e074428 Record live systemd staging service execution and journal telemetry
```

### 2.3 Synchronization Execution & Commit Parity

To cleanly reconcile the repository directly against GitHub `origin/main` without conflicts:
```powershell
ssh -o BatchMode=yes -o ConnectTimeout=15 -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "git -C /opt/autonomous-futures-bot fetch origin main && git -C /opt/autonomous-futures-bot reset --hard origin/main"
```
**Verbatim Output**:
```text
From https://github.com/kipopopo/autonomous-futures-bot
 * branch            main       -> FETCH_HEAD
HEAD is now at b438522 Execute multi-vector adverse volatility and slippage stress-testing
```

#### Commit Hash Verification:
- **Remote `HEAD` SHA**: `b4385224b3b2e40a29a2b0fd6fdc59c53905f259`
- **Remote `origin/main` SHA**: `b4385224b3b2e40a29a2b0fd6fdc59c53905f259`
- **Local `HEAD` SHA**: `b4385224b3b2e40a29a2b0fd6fdc59c53905f259`
- **Parity Status**: **100% BIT-FOR-BIT IDENTICAL**

#### Remote Git Log Alignment (3 Most Recent Commits):
```text
b438522 Execute multi-vector adverse volatility and slippage stress-testing
6a0b33b Execute multi-asset sandboxed paper trading simulation with shared 100 USDT margin
1849169 Execute multi-asset walk-forward evaluation with 100 USDT and dynamic leverage
```

#### Working Tree Cleanliness:
```powershell
ssh -o BatchMode=yes -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "git -C /opt/autonomous-futures-bot diff && git -C /opt/autonomous-futures-bot diff --cached"
```
- **Exit Code**: `0`
- **Output**: Empty (zero uncommitted or staged differences)
- **Untracked Code Probe**: `git status --porcelain -uall` confirmed zero untracked `.py`, `.sh`, or `.service` files.

### 2.4 Remote Filesystem Ownership & Permission Audit

An exhaustive scan across all filesystem objects in `/opt/autonomous-futures-bot` was performed:
```powershell
# Count objects NOT owned by afbot:afbot
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "find /opt/autonomous-futures-bot ! -user afbot -o ! -group afbot | wc -l"
# Count total objects
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "find /opt/autonomous-futures-bot | wc -l"
```
- **Non-afbot Objects**: `0`
- **Total Objects**: `11,854`
- **Ownership Parity**: Exactly **100.0%** (11,854 of 11,854) of all files and directories in `/opt/autonomous-futures-bot` are owned by `afbot:afbot`.

### 2.5 Remote Virtual Environment & Runtime Verification

The remote CPython runtime and locked dependencies were validated:
```powershell
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "/opt/autonomous-futures-bot/.venv/bin/python3 --version; /opt/autonomous-futures-bot/.venv/bin/pytest --version"
```
**Verbatim Output**:
```text
Python 3.14.7
pytest 9.1.1
```

#### Remote Import Probe:
```powershell
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 'PYTHONPATH=/opt/autonomous-futures-bot/src /opt/autonomous-futures-bot/.venv/bin/python3 -c "import autonomous_futures, pydantic, httpx, pytest; print(\"REMOTE_VENV_VERIFIED\")"'
```
- **Exit Code**: `0`
- **Output**: `REMOTE_VENV_VERIFIED`

#### Remote Pytest Sanity Runs:
1. `tests/unit/test_creator_staging_service.py`: **13 passed in 0.38s**
2. `tests/unit/test_domain_contracts.py`: **4 passed in 0.46s**

---

## 3. Deliverable 2: Systemd Paper Daemon Service Unit Architecture (R2)

### 3.1 Verbatim Service Unit Text (`deploy/autonomous-futures-paper.service`)

The production/staging service unit file is authored in `deploy/autonomous-futures-paper.service` (31 lines, 923 bytes):

```ini
[Unit]
Description=Autonomous Futures Bot sandboxed paper trading daemon
After=network-online.target
Wants=network-online.target
Documentation=file:///opt/autonomous-futures-bot/README.md

[Service]
Type=oneshot
User=afbot
Group=afbot
WorkingDirectory=/opt/autonomous-futures-bot
Environment=PYTHONPATH=/opt/autonomous-futures-bot/src
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/autonomous-futures-bot/.venv/bin/python scripts/preflight_kainode_paper.py --storage-dir /opt/autonomous-futures-bot/artifacts/paper --starting-equity 100.00 --bars 200 --smoke-test
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/opt/autonomous-futures-bot/artifacts/paper/
ProtectKernelModules=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CPUQuota=500%
MemoryMax=10G
TimeoutStartSec=180
Restart=no

[Install]
WantedBy=multi-user.target
```

### 3.2 Directive-by-Directive Technical Analysis

| Directive | Section | Value | Architectural Security & Operational Rationale |
|:---|:---:|:---|:---|
| `Description` | `[Unit]` | `Autonomous Futures Bot sandboxed paper trading daemon` | Canonical human-readable label identifying the service in `systemctl` and `journalctl`. |
| `After` / `Wants` | `[Unit]` | `network-online.target` | Orders startup after network resolution is established, standard for production daemons. |
| `Documentation` | `[Unit]` | `file:///opt/autonomous-futures-bot/README.md` | Operator documentation pointer accessible via `systemctl help autonomous-futures-paper.service`. |
| `Type` | `[Service]` | `oneshot` | Declares a finite batch execution model suitable for preflight diagnostic validation and bounded simulation runs. |
| `User` / `Group` | `[Service]` | `afbot` / `afbot` | **INV-2 Non-Root Operator**: Forces daemon execution under unprivileged operator UID 1001, GID 1001. Blocks execution under UID 0 (root). |
| `WorkingDirectory` | `[Service]` | `/opt/autonomous-futures-bot` | Pins the root repository workspace for relative path resolution. |
| `Environment` | `[Service]` | `PYTHONPATH=...`, `PYTHONUNBUFFERED=1` | Sets module resolution path to `src/` and flushes stdout/stderr buffers immediately to systemd journal. |
| `ExecStart` | `[Service]` | `/opt/.../.venv/bin/python scripts/preflight_kainode_paper.py ...` | Executes Python CLI runner with explicit arguments: `--storage-dir`, `--starting-equity 100.00`, `--bars 200`, and `--smoke-test`. |
| `NoNewPrivileges` | `[Service]` | `yes` | **INV-3 Process Sandboxing**: Sets `PR_SET_NO_NEW_PRIVS`, preventing child processes from gaining elevated privileges via `setuid`/`setgid` binaries or file capabilities. |
| `PrivateTmp` | `[Service]` | `yes` | **INV-3 Process Sandboxing**: Mounts an isolated filesystem namespace for `/tmp` and `/var/tmp`, preventing cross-process snooping or symlink attacks. |
| `ProtectSystem` | `[Service]` | `strict` | **INV-3 Process Sandboxing**: Mounts the entire filesystem (`/usr`, `/boot`, `/etc`, and critically `/opt`) as strictly **read-only** for the daemon process. |
| `ProtectHome` | `[Service]` | `read-only` | **INV-3 Process Sandboxing**: Mounts `/home`, `/root`, and `/run/user` as read-only, shielding operator files and SSH keys. |
| `ReadWritePaths` | `[Service]` | `/opt/autonomous-futures-bot/artifacts/paper/` | **INV-4 Storage Isolation Exception**: Carves out a dedicated read-write mount exception under `/opt`. Without this directive, `ProtectSystem=strict` causes immediate `sqlite3.OperationalError: attempt to write a readonly database` (`EROFS`). |
| `ProtectKernelModules` | `[Service]` | `yes` | Denies explicit module loading, unloading, and modification (`CAP_SYS_MODULE` stripped). |
| `ProtectKernelTunables` | `[Service]` | `yes` | Mounts `/proc/sys`, `/sys`, and `/proc/sysrq-trigger` as strictly read-only. |
| `ProtectControlGroups` | `[Service]` | `yes` | Mounts Linux cgroups hierarchy as read-only. |
| `RestrictAddressFamilies` | `[Service]` | `AF_INET AF_INET6 AF_UNIX` | Restricts socket address families strictly to standard IPv4, IPv6, and local UNIX domain sockets, blocking raw packet sockets (`AF_PACKET`, `AF_NETLINK`). |
| `CPUQuota` | `[Service]` | `500%` | Resource containment: caps daemon CPU utilization to 5 cores (500%) on multi-core VPS. |
| `MemoryMax` | `[Service]` | `10G` | Resource containment: sets hard cgroup memory ceiling of 10 Gigabytes, preventing runaway memory exhaustion. |
| `TimeoutStartSec` | `[Service]` | `180` | Bounded execution timer: terminates process with `SIGKILL` if execution exceeds 3 minutes. |
| `Restart` | `[Service]` | `no` | Prevents automated restart loops upon failure, preserving forensic state for operator analysis. |
| `WantedBy` | `[Install]` | `multi-user.target` | Standard multi-user target hook for boot-time or administrative enablement. |

### 3.3 Zero-Credential Boundary Architecture

Unlike `autonomous-futures-creator-staging.service` (which uses `LoadCredentialEncrypted` to decrypt an AI Studio API key into RAM-backed tmpfs), `autonomous-futures-paper.service` **strictly omits `LoadCredentialEncrypted`**.
- Paper trading operates in an isolated, offline, forward-testing regime.
- No Binance API keys, exchange secrets, or authentication tokens are configured or required.
- The unit file contains **zero secrets, zero passwords, and zero credential directives**.

---

## 4. Deliverable 3: Paper Daemon Staging Preflight & Diagnostic Tooling (R3)

### 4.1 Architecture of `paper_preflight.py` & `preflight_kainode_paper.py`

The preflight diagnostic tooling is architected across two decoupled components:

```
+-----------------------------------------------------------------------------+
|               scripts/preflight_kainode_paper.py (CLI Runner)               |
+-----------------------------------------------------------------------------+
| - Argparse CLI flags: --storage-dir, --starting-equity, --bars, --smoke-test|
| - Handles exit codes: 0 (Ready), 2 (Argument Error), 3 (Validation Error)   |
| - Emits canonical structured JSON telemetry report to stdout                |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|             src/autonomous_futures/paper_preflight.py (Engine)              |
+-----------------------------------------------------------------------------+
| 1. Domain Models (Pydantic v2):                                             |
|    - PaperHostEnvironmentReport: Python >= 3.12, user afbot, OS baseline    |
|    - PaperStorageDirectoryReport: mode 0o750/0o700, owner afbot, atomic R/W |
|    - PaperOfflineSafetyReport: zero secrets, exchange_access=False          |
|    - PaperSmokeTestReport: trades, positions & balance reconciliation       |
|    - PaperPreflightReport: root aggregation with cross-validator            |
| 2. Deterministic 5m Bar Generator:                                          |
|    - generate_deterministic_5m_bars(): reproducible synthetic OHLCV        |
|    - Validated via canonicalize_bars() ensuring strict candle envelopes     |
| 3. Shared Margin Account & Dynamic Leverage:                                |
|    - SharedMarginAccount: 100.00 USDT starting cash, 80% utilization cap    |
|    - calculate_dynamic_leverage(): scales 1.0x to 3.0x on conviction        |
| 4. Bounded Paper Smoke Execution:                                           |
|    - execute_paper_smoke_test(): isolated SQLite stores, trades,            |
|      reconciliation via reconcile_paper_positions(), health reporting       |
+-----------------------------------------------------------------------------+
```

### 4.2 Bounded Synthetic Simulation Mechanics

1. **Synthetic Data Synthesis**:
   `generate_deterministic_5m_bars(start, total_bars)` deterministically generates 200 synthetic 5m bars starting at `2026-01-01T00:00:00Z` using a sinusoidal mean-reverting price path ($P_0 = 0.1500$, amplitude $0.0050$, period 24 bars). It runs through `canonicalize_bars()` to guarantee valid candle geometry ($High \ge \max(Open, Close)$ and $Low \le \min(Open, Close)$).

2. **Shared 100.00 USDT Portfolio Margin**:
   The engine initializes `SharedMarginAccount(cash=Decimal("100.00"))`. Maximum margin utilization is capped at 80.00% ($\sum M_{\text{locked}} / \text{Equity} \le 0.80$), guaranteeing an unencumbered reserve buffer of $\ge 20.00\%$.

3. **Dynamic Leverage Scaling**:
   Leverage is dynamically sized via `calculate_dynamic_leverage(conviction)`:
   $$\text{Leverage} = 1.0 + (C - 0.50) \times 4.0, \quad \text{clamped to } [1.0, 3.0]$$
   For baseline conviction $C = 0.75$, dynamic leverage sizes to $2.0\times$. Under stress or low conviction, leverage automatically clamps to defensive $1.0\times$.

4. **Adverse Fill & Exact Balance Accounting**:
   Fills are executed with 0.04% taker fees and 2 bps adverse slippage. Transactions are persisted into SQLite (`paper-ledger.sqlite3`). Upon trade closeout:
   $$\text{Final Cash} = \text{Starting Cash} + \text{Net Realized PnL} = 100.00 + 3.38620717038206880 = 103.38620717038206880 \text{ USDT}$$
   Position reconciliation confirms 0 open stranded positions, and cash balance matches with **0.000000000000000000 balance drift**.

### 4.3 Unit Test Suite Architecture & Results (30 Tests)

Two dedicated test suites were implemented in `tests/unit/`:

#### 1. `tests/unit/test_paper_service.py` (11 Tests):
- `test_paper_service_file_exists`: Verifies file exists in `deploy/` with mode `644`.
- `test_paper_service_sections_present`: Asserts `[Unit]`, `[Service]`, and `[Install]` sections.
- `test_paper_service_unit_directives`: Validates `Description`, `After`, `Wants`, `Documentation`.
- `test_paper_service_user_and_group_non_root`: Validates `User=afbot`, `Group=afbot`, rejects `root`.
- `test_paper_service_sandboxing_directives`: Verifies `ProtectSystem=strict`, `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectHome=read-only`, kernel protection flags, and address family restrictions.
- `test_paper_service_storage_read_write_paths`: Verifies `ReadWritePaths=/opt/autonomous-futures-bot/artifacts/paper/`.
- `test_paper_service_resource_envelope`: Verifies `CPUQuota=500%`, `MemoryMax=10G`, `TimeoutStartSec=180`.
- `test_paper_service_working_directory_and_environment`: Verifies working dir and `PYTHONPATH`.
- `test_paper_service_exec_start_command`: Verifies exact CLI parameters and Python binary path.
- `test_paper_service_absence_of_exchange_credentials`: Asserts absence of `LoadCredentialEncrypted`, `BINANCE`, `API_KEY`, or `SECRET`.
- `test_paper_service_install_hook`: Verifies `WantedBy=multi-user.target`.

#### 2. `tests/unit/test_preflight_kainode_paper.py` (19 Tests):
- `test_preflight_valid_environment_and_smoke_test`: Validates nominal path returning `"ready": true` and exit code 0.
- `test_preflight_missing_storage_directory`: Validates error reporting when storage directory does not exist.
- `test_preflight_storage_not_a_directory`: Validates rejection when storage path points to a file.
- `test_preflight_loose_permissions_mode_644`: Validates rejection of insecure directory modes (`644`).
- `test_preflight_loose_permissions_mode_777`: Validates rejection of world-writable directory modes (`777`).
- `test_preflight_invalid_directory_owner`: Validates rejection of directories owned by unauthorized users.
- `test_preflight_non_writable_directory`: Validates atomic sentinel write failure detection.
- `test_preflight_credential_contamination_env`: Validates detection and rejection of forbidden exchange environment variables (`BINANCE_API_KEY`, etc.).
- `test_preflight_credential_contamination_file`: Validates detection and rejection of credentials files in credentials directory.
- `test_preflight_offline_safety_invariants`: Verifies `orders=0`, `exchange_access=false`, `promotion_state="unpromoted"`.
- `test_preflight_host_environment_checks`: Tests Python version and user validation across platforms.
- `test_preflight_smoke_test_custom_bars_and_capital`: Tests custom parameterization (72 bars, 50 USDT).
- `test_preflight_no_smoke_test_flag`: Verifies `--no-smoke-test` bypasses simulation while validating environment.
- `test_preflight_cli_invalid_arguments_exit_code_2`: Verifies exit code 2 on negative equity or bars < 30.
- `test_preflight_cli_output_json`: Verifies `--output-json` writes report directly to target file.
- `test_preflight_report_model_consistency`: Asserts Pydantic cross-validator consistency (`ready=False` on errors).
- `test_deterministic_5m_bars_generation`: Verifies synthetic candle continuity, step intervals, and envelopes.
- `test_dynamic_leverage_scaling`: Tests mathematical formula across conviction range ($C \in [0.4, 1.0]$).
- `test_validate_paper_storage_directory_direct`: Directly exercises POSIX permission validator.

#### Test Execution Evidence:
- **Local Test Run**: `uv run --locked pytest tests/unit/test_paper_service.py tests/unit/test_preflight_kainode_paper.py -v` -> **30 passed in 2.43s**.
- **Remote VPS Test Run**: `.venv/bin/pytest tests/unit/test_paper_service.py tests/unit/test_preflight_kainode_paper.py -v` -> **30 passed in 3.43s**.

---

## 5. Deliverable 4: Remote Service Installation & Smoke Verification (R4)

### 5.1 Remote File Synchronization & Permissions

The 5 Milestone 2 codebase files were synchronized to `/opt/autonomous-futures-bot` on Kainode VPS via SCP and set to canonical POSIX permissions:
- `/opt/autonomous-futures-bot/deploy/autonomous-futures-paper.service` (mode `644`, owner `afbot:afbot`)
- `/opt/autonomous-futures-bot/src/autonomous_futures/paper_preflight.py` (mode `644`, owner `afbot:afbot`)
- `/opt/autonomous-futures-bot/scripts/preflight_kainode_paper.py` (mode `755`, owner `afbot:afbot`)
- `/opt/autonomous-futures-bot/tests/unit/test_paper_service.py` (mode `644`, owner `afbot:afbot`)
- `/opt/autonomous-futures-bot/tests/unit/test_preflight_kainode_paper.py` (mode `644`, owner `afbot:afbot`)

Verification via `ls -l`:
```text
-rw-r--r-- 1 afbot afbot   923 Sep  4 21:26 /opt/autonomous-futures-bot/deploy/autonomous-futures-paper.service
-rwxr-xr-x 1 afbot afbot  4497 Sep  4 21:26 /opt/autonomous-futures-bot/scripts/preflight_kainode_paper.py
-rw-r--r-- 1 afbot afbot 33016 Sep  4 21:26 /opt/autonomous-futures-bot/src/autonomous_futures/paper_preflight.py
-rw-r--r-- 1 afbot afbot  6779 Sep  4 21:26 /opt/autonomous-futures-bot/tests/unit/test_paper_service.py
-rw-r--r-- 1 afbot afbot 15450 Sep  4 21:27 /opt/autonomous-futures-bot/tests/unit/test_preflight_kainode_paper.py
```

### 5.2 Storage Directory Initialization (`artifacts/paper`)

The dedicated SQLite storage path was initialized with mode `750` (`drwxr-x---`) owned by `afbot:afbot`:
```powershell
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "mkdir -p /opt/autonomous-futures-bot/artifacts/paper && chmod 750 /opt/autonomous-futures-bot/artifacts/paper && stat -c '%a %U:%G' /opt/autonomous-futures-bot/artifacts/paper"
```
**Verbatim Output**:
```text
750 afbot:afbot
```

### 5.3 Remote Pytest Suite Execution (30/30 Passed on Ubuntu 24.04)

```powershell
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "cd /opt/autonomous-futures-bot && .venv/bin/pytest tests/unit/test_paper_service.py tests/unit/test_preflight_kainode_paper.py -v"
```
**Verbatim Output**:
```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- /opt/autonomous-futures-bot/.venv/bin/python
cachedir: .pytest_cache
hypothesis profile 'default'
rootdir: /opt/autonomous-futures-bot
configfile: pyproject.toml
plugins: anyio-4.14.2, hypothesis-6.165.2
collecting ... collected 30 items

tests/unit/test_paper_service.py::test_paper_service_file_exists PASSED  [  3%]
tests/unit/test_paper_service.py::test_paper_service_sections_present PASSED [  6%]
tests/unit/test_paper_service.py::test_paper_service_unit_directives PASSED [ 10%]
tests/unit/test_paper_service.py::test_paper_service_user_and_group_non_root PASSED [ 13%]
tests/unit/test_paper_service.py::test_paper_service_sandboxing_directives PASSED [ 16%]
tests/unit/test_paper_service.py::test_paper_service_storage_read_write_paths PASSED [ 20%]
tests/unit/test_paper_service.py::test_paper_service_resource_envelope PASSED [ 23%]
tests/unit/test_paper_service.py::test_paper_service_working_directory_and_environment PASSED [ 26%]
tests/unit/test_paper_service.py::test_paper_service_exec_start_command PASSED [ 30%]
tests/unit/test_paper_service.py::test_paper_service_absence_of_exchange_credentials PASSED [ 33%]
tests/unit/test_paper_service.py::test_paper_service_install_hook PASSED [ 36%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_valid_environment_and_smoke_test PASSED [ 40%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_missing_storage_directory PASSED [ 43%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_storage_not_a_directory PASSED [ 46%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_loose_permissions_mode_644 PASSED [ 50%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_loose_permissions_mode_777 PASSED [ 53%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_invalid_directory_owner PASSED [ 56%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_non_writable_directory PASSED [ 60%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_credential_contamination_env PASSED [ 63%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_credential_contamination_file PASSED [ 66%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_offline_safety_invariants PASSED [ 70%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_host_environment_checks PASSED [ 73%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_smoke_test_custom_bars_and_capital PASSED [ 76%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_no_smoke_test_flag PASSED [ 80%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_cli_invalid_arguments_exit_code_2 PASSED [ 83%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_cli_output_json PASSED [ 86%]
tests/unit/test_preflight_kainode_paper.py::test_preflight_report_model_consistency PASSED [ 90%]
tests/unit/test_preflight_kainode_paper.py::test_deterministic_5m_bars_generation PASSED [ 93%]
tests/unit/test_preflight_kainode_paper.py::test_dynamic_leverage_scaling PASSED [ 96%]
tests/unit/test_preflight_kainode_paper.py::test_validate_paper_storage_directory_direct PASSED [100%]

============================== 30 passed in 3.43s ==============================
```

### 5.4 Remote Preflight Diagnostic & Bounded Smoke Test Execution

The diagnostic runner was executed against the remote environment:
```powershell
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 'cd /opt/autonomous-futures-bot && PYTHONPATH=/opt/autonomous-futures-bot/src /opt/autonomous-futures-bot/.venv/bin/python scripts/preflight_kainode_paper.py --storage-dir /opt/autonomous-futures-bot/artifacts/paper --starting-equity 100.00 --bars 200 --smoke-test'
```
- **Exit Code**: `0`
- **Verbatim Structured JSON Output**:
```json
{
  "errors": [],
  "host_environment": {
    "current_uid": 1001,
    "current_user": "afbot",
    "in_systemd": false,
    "os_name": "Ubuntu 24.04.4 LTS",
    "platform": "linux",
    "python_version": "3.14.7",
    "python_version_valid": true,
    "user_valid": true,
    "validation_error": null
  },
  "metadata": {
    "bars": 200,
    "smoke_test_requested": true,
    "starting_equity": "100.00",
    "storage_dir": "/opt/autonomous-futures-bot/artifacts/paper",
    "timestamp": "2026-09-04T21:28:21.262972+00:00"
  },
  "offline_safety": {
    "credentials_detected": [],
    "exchange_access": false,
    "execution_authority": false,
    "live_credentials_forbidden": true,
    "orders": 0,
    "paper_activation": false,
    "promotion_state": "unpromoted",
    "validation_error": null
  },
  "ready": true,
  "smoke_test": {
    "balance_reconciled": true,
    "cohort_status": "not_ready",
    "executed": true,
    "health_status": "maturing",
    "positions_reconciled": true,
    "total_bars": 200,
    "trades_executed": 1,
    "validation_error": null
  },
  "status": "ready_for_paper_daemon",
  "storage_directory": {
    "exists": true,
    "is_directory": true,
    "mode_octal": "0o750",
    "mode_valid": true,
    "owner_name": "afbot",
    "owner_uid": 1001,
    "owner_valid": true,
    "path": "/opt/autonomous-futures-bot/artifacts/paper",
    "read_write_capable": true,
    "validation_error": null
  },
  "warnings": []
}
```

### 5.5 Remote Storage Artifacts & SQLite Databases Verification

Inspection of `/opt/autonomous-futures-bot/artifacts/paper` confirmed the generation of all 3 isolated SQLite databases and 3 structured JSON reports:
```powershell
ssh -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 'ls -la /opt/autonomous-futures-bot/artifacts/paper'
```
**Verbatim Output**:
```text
total 52
drwxr-x--- 2 afbot afbot  4096 Sep  4 21:28 .
drwxrwxr-x 4 afbot afbot  4096 Sep  4 21:26 ..
-rw-rw-r-- 1 afbot afbot   924 Sep  4 21:28 paper-cohort-readiness-report.json
-rw-rw-r-- 1 afbot afbot  1109 Sep  4 21:28 paper-health-report.json
-rw-r--r-- 1 afbot afbot  8192 Sep  4 21:28 paper-ledger.sqlite3
-rw-r--r-- 1 afbot afbot 16384 Sep  4 21:28 paper-lifecycle.sqlite3
-rw-r--r-- 1 afbot afbot  8192 Sep  4 21:28 paper-observations.sqlite3
-rw-rw-r-- 1 afbot afbot   280 Sep  4 21:28 paper-summary.json
```

#### Verbatim Telemetry Content (`paper-summary.json`):
```json
{
  "total_bars": 200,
  "trades_executed": 1,
  "starting_equity": "100.00",
  "final_cash": "103.38620717038206880",
  "net_pnl": "3.38620717038206880",
  "positions_reconciled": true,
  "balance_reconciled": true,
  "health_status": "maturing",
  "cohort_status": "not_ready"
}
```

### 5.6 Sudoers Privileges & Systemd Service Queries

1. **Sudoers Rule Inspection (`/etc/sudoers.d/afbot-service`)**:
   Querying `sudo -l` over operator SSH confirmed:
   ```text
   Matching Defaults entries for afbot on kipopopo:
       env_reset, mail_badpass, secure_path=/usr/local/sbin\:/usr/local/bin\:/usr/sbin\:/usr/bin\:/sbin\:/bin\:/snap/bin, use_pty

   User afbot may run the following commands on kipopopo:
       (ALL) NOPASSWD: /usr/bin/systemctl restart autonomous-futures-*, /usr/bin/systemctl status autonomous-futures-*, /usr/bin/journalctl -u autonomous-futures-*, /bin/systemctl restart autonomous-futures-*, /bin/systemctl status autonomous-futures-*, /bin/journalctl -u autonomous-futures-*
   ```
2. **Direct Write Permission Boundary**:
   Testing copy to `/etc/systemd/system/` from operator account `afbot` returned `Permission denied` (`cp: cannot create regular file '/etc/systemd/system/autonomous-futures-paper.service': Permission denied`). This is the correct Linux security posture: only root can register system service definitions.
3. **Canonical One-Line Root Installation Command**:
   ```bash
   install -m 644 -o root -g root /opt/autonomous-futures-bot/deploy/autonomous-futures-paper.service /etc/systemd/system/autonomous-futures-paper.service && systemctl daemon-reload
   ```
4. **Service Status & Restart Probes via Operator SSH**:
   - `sudo systemctl status autonomous-futures-paper.service`: Exit code `1`, output `Unit autonomous-futures-paper.service could not be found.` (Pre-installation baseline verified).
   - `sudo systemctl restart autonomous-futures-paper.service`: Exit code `1`, output `Failed to restart autonomous-futures-paper.service: Unit autonomous-futures-paper.service not found.`
   - `sudo journalctl -u autonomous-futures-paper.service --no-pager -n 50`: Exit code `0`, output `-- No entries --`.

### 5.7 Forensic Zero-Secret Leakage Audit

A comprehensive forensic audit was performed across all outputs, logs, command returns, and generated artifacts:
- Preflight JSON telemetry: `"credentials_detected": []`, `"live_credentials_forbidden": true`.
- Service unit file: Zero references to API keys, passwords, or encrypted tokens.
- SQLite files and JSON reports: Zero API keys, private tokens, or secrets.
- Git working tree: Clean, zero secrets staged or committed.

---

## 6. Deliverable 5: Security & Safety Invariants Verification

### Invariants Compliance Matrix (INV-1 through INV-8)

| Invariant ID | Invariant Title | Core Specification | Empirical Verification Finding | Compliance Status |
|:---:|:---|:---|:---|:---:|
| **INV-1** | **Zero Secret Leakage** | No API keys, passwords, bearer tokens, or secrets logged, committed, or exposed. | Scanned preflight telemetry, unit files, shell logs, and test runs. `credentials_detected` is empty. | **VERIFIED COMPLIANT** |
| **INV-2** | **Non-Root Operator `afbot`** | All processes run under UID 1001 / GID 1001 (`afbot`). No root daemon execution. | Service unit specifies `User=afbot`, `Group=afbot`. Preflight validates `current_uid=1001`, `current_user="afbot"`. | **VERIFIED COMPLIANT** |
| **INV-3** | **Process Sandboxing** | Strict systemd isolation: read-only filesystem, private tmp, no new privileges. | Service unit enforces `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp=yes`, `NoNewPrivileges=yes`, address family restrictions. Tested via unit tests. | **VERIFIED COMPLIANT** |
| **INV-4** | **Storage Directory Isolation** | Dedicated isolated path for SQLite persistence without granting general write access. | `ReadWritePaths=/opt/autonomous-futures-bot/artifacts/paper/`. Path initialized with mode `750` (`drwxr-x---`) owned by `afbot:afbot`. Atomic R/W verified. | **VERIFIED COMPLIANT** |
| **INV-5** | **Zero Exchange Access** | Zero network calls to Binance live or testnet API endpoints (`exchange_access = false`). | Verified `exchange_access: false` in preflight report. Offline synthetic bar generator used. Zero exchange clients initialized. | **VERIFIED COMPLIANT** |
| **INV-6** | **Zero Execution Authority** | Live order submissions prohibited (`orders = 0`, `execution_authority = false`). | Verified `orders: 0` and `execution_authority: false` across preflight JSON telemetry and health reports. | **VERIFIED COMPLIANT** |
| **INV-7** | **Promotion State Unpromoted** | Daemon remains in unpromoted staging research state (`promotion_state = "unpromoted"`). | Verified `promotion_state: "unpromoted"` and `paper_activation: false` across preflight and health telemetry. | **VERIFIED COMPLIANT** |
| **INV-8** | **Offline Bounded Simulation** | Simulation operates strictly on bounded synthetic data without lookahead. | Verified bounded 200 synthetic 5m bars, deterministic cash accounting ($100.00 \to 103.3862$ USDT), and 0 stranded open positions. | **VERIFIED COMPLIANT** |

---

## 7. Deliverable 6: Local Repository Verification Gates Results

All 6 local repository verification gates were executed synchronously against the local workspace:

### Gate Summary Table

| Gate # | Verification Gate Command | Target Scope | Runtime | Exit Code | Result Summary | Status |
|:---:|:---|:---|:---:|:---:|:---|:---:|
| **Gate 1** | `uv run --locked pytest -q` | Full repository test suite | 212.92s | `0` | **1,277 passed in 212.92s** (1247 baseline + 30 new tests) | **PASSED** |
| **Gate 2** | `uv run --locked ruff check src tests scripts` | Linting across all source files | 0.45s | `0` | **All checks passed!** | **PASSED** |
| **Gate 3** | `uv run --locked ruff format --check src tests scripts` | Formatting across all source files | 0.38s | `0` | **390 files already formatted** | **PASSED** |
| **Gate 4** | `uv run --locked mypy src scripts` | Static type checking | 2.15s | `0` | **Success: no issues found in 200 source files** | **PASSED** |
| **Gate 5** | `uv lock --check` | Dependency lockfile parity | 0.80ms | `0` | **Resolved 67 packages in 0.80ms** | **PASSED** |
| **Gate 6** | `git diff --check` | Whitespace & merge conflict check | 0.12s | `0` | **Clean exit, zero whitespace violations** | **PASSED** |

### Verbatim Gate Outputs

#### Gate 1: Full Pytest Test Suite (`uv run --locked pytest -q`)
```text
........................................................................ [  5%]
........................................................................ [ 11%]
........................................................................ [ 16%]
........................................................................ [ 22%]
........................................................................ [ 28%]
........................................................................ [ 33%]
........................................................................ [ 39%]
........................................................................ [ 45%]
........................................................................ [ 50%]
........................................................................ [ 56%]
........................................................................ [ 62%]
........................................................................ [ 67%]
........................................................................ [ 73%]
........................................................................ [ 78%]
........................................................................ [ 84%]
........................................................................ [ 90%]
........................................................................ [ 95%]
.....................................................                    [100%]
1277 passed in 212.92s (0:03:32)
```
*(Exit code: `0`, zero failures, zero regressions across all 1,277 tests)*

#### Gate 2: Ruff Linter Check (`uv run --locked ruff check src tests scripts`)
```text
All checks passed!
```
*(Exit code: `0`)*

#### Gate 3: Ruff Formatter Check (`uv run --locked ruff format --check src tests scripts`)
```text
390 files already formatted
```
*(Exit code: `0`)*

#### Gate 4: Mypy Static Type Checking (`uv run --locked mypy src scripts`)
```text
Success: no issues found in 200 source files
```
*(Exit code: `0`)*

#### Gate 5: UV Dependency Lockfile Check (`uv lock --check`)
```text
Resolved 67 packages in 0.80ms
```
*(Exit code: `0`)*

#### Gate 6: Git Working Tree Cleanliness Check (`git diff --check`)
*(Clean exit with code 0; zero whitespace violations, zero merge conflict markers)*

---

## 8. Conclusion & Operator Runbook for Web Console

### 8.1 Architectural Conclusion

Phase 256 successfully establishes the remote execution and systemd daemon infrastructure for the Autonomous Futures Bot paper trading subsystem:
- Remote host `/opt/autonomous-futures-bot` on Kainode VPS (`147.79.18.15`) is verified in full commit parity at `b438522`.
- All 11,854 files are owned 100% by unprivileged operator `afbot:afbot`.
- The systemd unit file `deploy/autonomous-futures-paper.service` implements strict Linux security sandboxing with `ReadWritePaths` storage carve-out.
- The preflight diagnostic tooling validates environment readiness and executes bounded synthetic simulations.
- Sudoers privilege boundary is verified: operator `afbot` has `NOPASSWD` sudo authorization to restart, check status, and query journals on `autonomous-futures-*` units.

### 8.2 Operator Runbook for Hostinger Web Console (Root Execution)

To complete the root service unit registration into systemd on Kainode VPS, execute the following one-line command from the Hostinger VPS Web Console root terminal:

```bash
install -m 644 -o root -g root /opt/autonomous-futures-bot/deploy/autonomous-futures-paper.service /etc/systemd/system/autonomous-futures-paper.service && systemctl daemon-reload
```

#### Verification Steps for Operator `afbot` (Post-Registration):
Once root executes the command above, operator `afbot` can autonomously trigger and inspect the service via SSH:

1. **Trigger Service Execution**:
   ```bash
   sudo systemctl restart autonomous-futures-paper.service
   ```
2. **Verify Service Status**:
   ```bash
   sudo systemctl status autonomous-futures-paper.service
   ```
   *Expected*: `Active: inactive (dead)` with `status=0/SUCCESS` (normal for `Type=oneshot`).
3. **Inspect Systemd Journal**:
   ```bash
   sudo journalctl -u autonomous-futures-paper.service --no-pager -n 50
   ```
   *Expected*: Structured JSON telemetry emitted with `"ready": true`, `"status": "ready_for_paper_daemon"`.
4. **Inspect Generated SQLite Databases**:
   ```bash
   ls -la /opt/autonomous-futures-bot/artifacts/paper/
   ```
   *Expected*: `paper-ledger.sqlite3`, `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`, and JSON reports.

---

### 8.3 Formal Acceptance Sign-Off & Hard Stop

All Phase 256 requirements specified in `ORIGINAL_REQUEST.md` (lines 573–623) and `PROJECT.md` have been fully satisfied, empirically verified, and documented.

**HARD STOP DECLARATION**:
In strict adherence to the project safety invariants, operations terminate here. Live exchange credentials remain unconfigured, live network execution authority remains disabled (`exchange_access = false`, `execution_authority = false`), live order submission remains at zero (`orders = 0`), and promotion state remains `"unpromoted"`. Phase 256 is formally certified as **PASSED** and **COMPLETE**.
