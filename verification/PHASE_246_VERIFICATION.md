# Phase 246 Verification Report: Kainode VPS afbot Provisioning & Connectivity Baseline

**Date**: 2026-09-03
**Status**: PASSED (All 6 Repository Verification Gates Clean, Provisioning Script & Unit Tests Verified, SSH Baseline Formally Characterized)
**Host Target**: Kainode VPS (`147.79.18.15`, hostname `kipopopo`, Ubuntu 24.04 LTS Noble Numbat)
**Author**: Worker Phase 246 (`worker_phase246_1`)
**Milestone**: Phase 246 (Requirement R4)

---

## 1. Executive Summary

Phase 246 delivers an idempotent, hardened provisioning script (`scripts/setup_kainode_afbot.sh`) to establish the non-root operator account `afbot` on Kainode VPS (`147.79.18.15`, Ubuntu 24.04 LTS Noble Numbat), implements a comprehensive offline unit test suite (`tests/unit/test_setup_kainode_afbot.py`), provides the authoritative Hostinger VPS Web Console operator runbook, executes safe SSH connectivity baseline probes, and verifies all 6 repository quality gates with zero secret leakage and zero exchange access.

All four core requirements of Phase 246 have been completed and verified:
1. **Kainode Operator Provisioning Script (R1)**: Delivered `scripts/setup_kainode_afbot.sh` with UNIX LF line endings, strict safety flags (`set -euo pipefail`, `IFS=$'\n\t'`), root EUID gate with `--dry-run` and `DRY_RUN=1` simulation support, idempotent user/group management, strict SSH permission boundaries (mode `700` on `~/.ssh`, mode `600` on `authorized_keys`), pinned operator public key installation with newline safety, credentials store directory (`/etc/autonomous-futures/credentials`, mode `750`, `root:afbot`), restricted sudoers drop-in (`/etc/sudoers.d/afbot-service`, mode `0440`, `root:root`) validated via `visudo -cf`, and safe `systemd-creds` capability detection.
2. **Unit Test Coverage & Syntax Validation (R2)**: Implemented 28 comprehensive unit tests in `tests/unit/test_setup_kainode_afbot.py` verifying file hygiene, UNIX LF line endings, bash strict mode flags, root EUID enforcement, permission octals (`700`, `600`, `750`, `440`), ownership directives (`afbot:afbot`, `root:afbot`, `root:root`), idempotency checks, sudoers whitelist commands, secret canary scans, dry-run CLI/env execution, static AST/regex variable declaration analysis, dynamic Stage 6 summary execution without unbound variables, and `bash -n` syntax validation.
3. **Operator Runbook & Connectivity Probes (R3)**: Specified the exact copy-paste heredoc runbook and GitHub raw curl execution command for the Hostinger VPS Web Console root shell. Conducted non-destructive live SSH connectivity probes against `afbot@147.79.18.15`, capturing the empirical baseline (exit code 1, `Permission denied (publickey)`, Packet 51 refusal) and formalizing the Before vs After provisioning state transition model.
4. **Verification Report & Repository Gates (R4)**: Documented complete verification evidence and achieved 100% clean passes across all 6 repository verification gates (`922 passed in 17.93s`, Ruff check clean, Ruff format clean, Mypy strict clean across 187 files, uv lock clean, git diff clean).

---

## 2. Deliverable 1: Kainode Operator Provisioning Script (`scripts/setup_kainode_afbot.sh`)

### 2.1 Script Architecture & Hardening Directives

The script `scripts/setup_kainode_afbot.sh` provides deterministic, repeatable provisioning for the non-root operator account on Ubuntu 24.04 LTS:
- **Interpreter**: `#!/usr/bin/env bash` ensures portable invocation across standard Linux distributions.
- **Strict Mode**: `set -euo pipefail` halts execution immediately upon command failure, unset variable expansion, or pipeline stage failure.
- **Hardened IFS**: `IFS=$'\n\t'` prevents word-splitting vulnerabilities during string expansions.
- **Execution Gate**: Verifies EUID 0 (`[[ "$(id -u)" -ne 0 ]]`) and exits with code 1 unless invoked in simulation mode (`--dry-run` or `DRY_RUN=1`).
- **Simulation Mode**: Supports `--dry-run` flag and `DRY_RUN=1` environment variable, enabling non-destructive validation and testing in unprivileged environments.
- **Line Ending & Formatting Hygiene**: Encoded strictly in UTF-8 with UNIX LF line endings (`\n`), zero CRLF carriage returns, and zero trailing whitespace.

### 2.2 Execution Stages & Idempotency Mechanics

The script executes 6 modular, defensive stages:

| Stage | Name | Target Resource | Idempotency & Safety Mechanism |
|---|---|---|---|
| **1/6** | Identity Provisioning | Group `afbot`, User `afbot` | Evaluates `getent group afbot` and `id -u afbot`. Skips creation if present; reconciles shell (`/bin/bash`), home (`/home/afbot`), and primary group (`afbot`) via `usermod`. |
| **2/6** | SSH Security | `/home/afbot/.ssh`<br>`authorized_keys` | Creates `.ssh` (mode `700`, owner `afbot:afbot`). Touches `authorized_keys` (mode `600`, owner `afbot:afbot`). Evaluates `grep -q -F` before appending; injects trailing newline if pre-existing file lacks one. |
| **3/6** | Credentials Store | `/etc/autonomous-futures/credentials` | Creates parent directories recursively (`mkdir -p`). Enforces mode `750` (`rwxr-x---`) and ownership `root:afbot`, enabling `afbot` group traversal while denying world access. |
| **4/6** | Restricted Sudoers | `/etc/sudoers.d/afbot-service` | Generates configuration into temporary file, locks permissions to `0440`, validates syntax atomically with `visudo -cf`, and installs to `/etc/sudoers.d/afbot-service` (mode `0440`, owner `root:root`). |
| **5/6** | Host Capability | `systemd-creds` | Validates binary presence via `command -v systemd-creds` and checks execution with `systemd-creds --version`. Prints no private keys or secrets. |
| **6/6** | Summary & Exit | Host Environment | Emits human-readable configuration summary and exits with code 0. |

### 2.3 Strict Permission & Ownership Specification Table

| Filesystem Path | Type | Owner:Group | Permissions (Octal) | Symbolic Mode | Security Purpose |
|---|---|---|---|---|---|
| `/home/afbot/.ssh` | Directory | `afbot:afbot` | `700` | `rwx------` | OpenSSH strict user directory boundary |
| `/home/afbot/.ssh/authorized_keys` | Regular File | `afbot:afbot` | `600` | `rw-------` | Private authorized key list; denies group and world |
| `/etc/autonomous-futures/credentials` | Directory | `root:afbot` | `750` | `rwxr-x---` | Encrypted credential store; group `afbot` traversal only |
| `/etc/sudoers.d/afbot-service` | Regular File | `root:root` | `0440` | `r--r-----` | Sudoers drop-in; strictly read-only for root and root group |

### 2.4 Operator Public Key Verification

The script installs the pinned Ed25519 public key corresponding to the operator key pair generated for Kainode VPS:
- **Public Key String**:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMJJ0UAlUCOTwKyqG0+vpNr3e7nr6trU3C3kqIQgWShY eddsa-key-20260901`
- **Key Type**: Ed25519 (256-bit)
- **Local Private Key**: `C:\Users\thaqi\.ssh\kainode_ed25519_openssh`
- **Local Public Key**: `C:\Users\thaqi\.ssh\kainode_ed25519_openssh.pub`
- **Local Public Key Fingerprint**:
  `256 SHA256:3sel/5iY8Ug04ettqbneY2uUK5UAC6CoLIYYtgrmYDE eddsa-key-20260901 (ED25519)`

### 2.5 Restricted Sudoers Rule Specification

To maintain least-privilege administrative access for automated orchestration and service monitoring, the sudoers drop-in `/etc/sudoers.d/afbot-service` defines:

```text
# Restricted service management privileges for Autonomous Futures Bot operator
# Managed by scripts/setup_kainode_afbot.sh
afbot ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart autonomous-futures-*, /usr/bin/systemctl status autonomous-futures-*, /usr/bin/journalctl -u autonomous-futures-*, /bin/systemctl restart autonomous-futures-*, /bin/systemctl status autonomous-futures-*, /bin/journalctl -u autonomous-futures-*
```

Key security attributes:
1. **Passwordless Scope (`NOPASSWD:`)**: Restricted strictly to service units matching `autonomous-futures-*`.
2. **Whitelisted Actions**: Only `restart`, `status`, and `journalctl -u` are permitted. Blanket sudo (`NOPASSWD: ALL` or `ALL=(ALL:ALL) ALL`) is strictly absent.
3. **Dual Path Specification**: Both `/usr/bin/` and `/bin/` paths are declared to accommodate Linux merged-usr filesystem aliases.
4. **Pre-Installation Validation**: The file is validated using `visudo -cf` prior to activation, preventing accidental sudo lockouts.

### 2.6 systemd-creds Capability Verification

The script detects and validates host capability for systemd encrypted credential management:
- Executes `command -v systemd-creds` to confirm binary path.
- Executes `systemd-creds --version` to verify runtime compatibility (Ubuntu 24.04 provides `systemd 255 (255.4-1ubuntu8.16)`).
- Zero secret parameters, zero decryption keys, and zero token payloads are passed or logged.

---

## 3. Deliverable 2: Unit Test Suite Coverage (`tests/unit/test_setup_kainode_afbot.py`)

### 3.1 Test Architecture & Methodology

The test suite in `tests/unit/test_setup_kainode_afbot.py` provides cross-platform, deterministic verification of the provisioning script:
- **Zero OS Modification**: Tests run safely on developer workstations (Windows 11) and CI environments without requiring root privileges or Linux kernel namespaces.
- **Static Analysis & Regex Verification**: Parses file headers, safety flags, constant definitions, idempotency conditionals, exact permission octals, and sudoers rules.
- **Static Variable Reference Analysis**: Verifies that every `$VAR` and `${VAR}` parameter expansion in the script resolves to a declared assignment (`readonly VAR=...`, `VAR=...`, `for VAR in ...`) or a standard POSIX/Bash builtin (`$0`, `$@`, `$UID`, etc.), guaranteeing zero unbound variables at the AST level.
- **Secret Canary Scanning**: Asserts the total absence of private keys (OpenSSH, RSA, PuTTY), API tokens, Google AI Studio keys (`AIzaSy...`), Binance credentials, and plaintext passwords.
- **Subprocess Execution Oracle**: Executes `bash -n` for AST/syntax validation, tests `--dry-run`, `DRY_RUN=1`, non-root rejection, and `--help` CLI behavior, and dynamically executes the Stage 6 completion summary under `bash -s` with binary stdin and `DRY_RUN=0` under `set -euo pipefail` to ensure zero unbound variable terminations.

### 3.2 Unit Test Execution Results

Command executed:
```powershell
uv run --locked pytest tests/unit/test_setup_kainode_afbot.py -v
```

Verbatim test results:
```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\thaqi\Projects\Autonomous Futures Bot\.venv\Scripts\python.exe
cachedir: .pytest_cache
hypothesis profile 'default'
rootdir: C:\Users\thaqi\Projects\Autonomous Futures Bot
configfile: pyproject.toml
plugins: anyio-4.14.2, hypothesis-6.165.2
collecting ... collected 28 items

tests/unit/test_setup_kainode_afbot.py::test_script_file_exists_and_non_empty PASSED [  3%]
tests/unit/test_setup_kainode_afbot.py::test_script_has_unix_lf_line_endings PASSED [  7%]
tests/unit/test_setup_kainode_afbot.py::test_script_has_no_trailing_whitespace PASSED [ 10%]
tests/unit/test_setup_kainode_afbot.py::test_script_has_valid_shebang PASSED [ 14%]
tests/unit/test_setup_kainode_afbot.py::test_script_enforces_strict_safety_flags PASSED [ 17%]
tests/unit/test_setup_kainode_afbot.py::test_script_root_privilege_enforcement PASSED [ 21%]
tests/unit/test_setup_kainode_afbot.py::test_script_target_identity_constants PASSED [ 25%]
tests/unit/test_setup_kainode_afbot.py::test_script_idempotent_user_and_group_management PASSED [ 28%]
tests/unit/test_setup_kainode_afbot.py::test_script_ssh_directory_permissions_and_ownership PASSED [ 32%]
tests/unit/test_setup_kainode_afbot.py::test_script_authorized_keys_permissions_and_ownership PASSED [ 35%]
tests/unit/test_setup_kainode_afbot.py::test_script_pinned_operator_public_key PASSED [ 39%]
tests/unit/test_setup_kainode_afbot.py::test_script_authorized_keys_idempotency_and_newline_safety PASSED [ 42%]
tests/unit/test_setup_kainode_afbot.py::test_script_credentials_directory_hardening PASSED [ 46%]
tests/unit/test_setup_kainode_afbot.py::test_script_sudoers_file_path_and_mode PASSED [ 50%]
tests/unit/test_setup_kainode_afbot.py::test_script_sudoers_restricted_whitelist PASSED [ 53%]
tests/unit/test_setup_kainode_afbot.py::test_script_sudoers_no_blanket_privileges PASSED [ 57%]
tests/unit/test_setup_kainode_afbot.py::test_script_sudoers_visudo_validation PASSED [ 60%]
tests/unit/test_setup_kainode_afbot.py::test_script_systemd_creds_capability_check PASSED [ 64%]
tests/unit/test_setup_kainode_afbot.py::test_canary_zero_private_keys PASSED [ 67%]
tests/unit/test_setup_kainode_afbot.py::test_canary_zero_credentials_or_passwords PASSED [ 71%]
tests/unit/test_setup_kainode_afbot.py::test_bash_syntax_check_oracle PASSED [ 75%]
tests/unit/test_setup_kainode_afbot.py::test_dry_run_execution_via_cli_flag PASSED [ 78%]
tests/unit/test_setup_kainode_afbot.py::test_dry_run_execution_via_env_var PASSED [ 82%]
tests/unit/test_setup_kainode_afbot.py::test_non_root_execution_fails_with_code_1 PASSED [ 85%]
tests/unit/test_setup_kainode_afbot.py::test_invalid_cli_option_fails_with_code_1 PASSED [ 89%]
tests/unit/test_setup_kainode_afbot.py::test_help_flag_exits_0 PASSED    [ 92%]
tests/unit/test_setup_kainode_afbot.py::test_script_all_variable_references_are_declared_or_builtin PASSED [ 96%]
tests/unit/test_setup_kainode_afbot.py::test_stage6_completion_summary_dynamic_execution_zero_unbound_vars PASSED [100%]

============================= 28 passed in 4.05s ==============================
```

**Result**: 28 passed, 0 failed, 0 warnings in 4.05 seconds.

---

## 4. Deliverable 3: Operator Web Console Runbook & Empirical SSH Baseline

### 4.1 Hostinger VPS Web Console Runbook

Because root interactive SSH access is restricted by server policy on Kainode VPS (`147.79.18.15`) and `afbot` does not yet have an authorized key installed, the initial bootstrap execution must be performed directly in the **Hostinger VPS Web Console** (root TTY terminal).

#### Method A: Self-Contained Heredoc Execution (Recommended)

Copy and paste the following complete block into the Hostinger VPS Web Console root shell:

```bash
cat << 'EOF' > /tmp/setup_kainode_afbot.sh
#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

TARGET_USER="afbot"
TARGET_GROUP="afbot"
TARGET_SHELL="/bin/bash"
TARGET_HOME="/home/afbot"
SSH_DIR="${TARGET_HOME}/.ssh"
AUTH_KEYS_FILE="${SSH_DIR}/authorized_keys"
OPERATOR_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMJJ0UAlUCOTwKyqG0+vpNr3e7nr6trU3C3kqIQgWShY eddsa-key-20260901"
CREDENTIALS_DIR="/etc/autonomous-futures/credentials"
SUDOERS_DROPIN="/etc/sudoers.d/afbot-service"

echo "=== [1/6] Provisioning group and user ==="
if ! getent group "${TARGET_GROUP}" >/dev/null 2>&1; then
    groupadd "${TARGET_GROUP}"
    echo "Created group ${TARGET_GROUP}."
else
    echo "Group ${TARGET_GROUP} already exists."
fi

if ! id -u "${TARGET_USER}" >/dev/null 2>&1; then
    useradd -m -g "${TARGET_GROUP}" -s "${TARGET_SHELL}" -d "${TARGET_HOME}" "${TARGET_USER}"
    echo "Created user ${TARGET_USER}."
else
    usermod -s "${TARGET_SHELL}" -g "${TARGET_GROUP}" "${TARGET_USER}"
    echo "Reconciled user ${TARGET_USER}."
fi

echo "=== [2/6] Configuring SSH directory and authorized keys ==="
mkdir -p "${SSH_DIR}"
chmod 700 "${SSH_DIR}"
chown "${TARGET_USER}:${TARGET_GROUP}" "${SSH_DIR}"

touch "${AUTH_KEYS_FILE}"
if ! grep -q -F "${OPERATOR_PUBKEY}" "${AUTH_KEYS_FILE}"; then
    if [[ -s "${AUTH_KEYS_FILE}" ]] && [[ -n "$(tail -c1 "${AUTH_KEYS_FILE}" 2>/dev/null)" ]]; then
        echo "" >> "${AUTH_KEYS_FILE}"
    fi
    echo "${OPERATOR_PUBKEY}" >> "${AUTH_KEYS_FILE}"
    echo "Installed operator public key."
else
    echo "Operator public key already present."
fi
chmod 600 "${AUTH_KEYS_FILE}"
chown "${TARGET_USER}:${TARGET_GROUP}" "${AUTH_KEYS_FILE}"

echo "=== [3/6] Configuring credentials directory ==="
mkdir -p "${CREDENTIALS_DIR}"
chmod 750 "${CREDENTIALS_DIR}"
chown root:"${TARGET_GROUP}" "${CREDENTIALS_DIR}"
echo "Configured ${CREDENTIALS_DIR} (mode 750, owner root:${TARGET_GROUP})."

echo "=== [4/6] Configuring restricted sudoers drop-in ==="
TMP_SUDOERS="$(mktemp /tmp/afbot-service.XXXXXX)"
cat << 'SUDO_EOF' > "${TMP_SUDOERS}"
# Restricted service management privileges for Autonomous Futures Bot operator
afbot ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart autonomous-futures-*, /usr/bin/systemctl status autonomous-futures-*, /usr/bin/journalctl -u autonomous-futures-*, /bin/systemctl restart autonomous-futures-*, /bin/systemctl status autonomous-futures-*, /bin/journalctl -u autonomous-futures-*
SUDO_EOF
chmod 440 "${TMP_SUDOERS}"
chown root:root "${TMP_SUDOERS}"

if command -v visudo >/dev/null 2>&1; then
    visudo -cf "${TMP_SUDOERS}"
    echo "Validated sudoers configuration with visudo -cf."
fi

install -m 0440 -o root -g root "${TMP_SUDOERS}" "${SUDOERS_DROPIN}"
rm -f "${TMP_SUDOERS}"
echo "Installed restricted sudoers rule at ${SUDOERS_DROPIN}."

echo "=== [5/6] Verifying host systemd-creds capability ==="
if command -v systemd-creds >/dev/null 2>&1; then
    systemd-creds --version | head -n 1
    echo "Verified systemd-creds."
else
    echo "WARNING: systemd-creds binary not found." >&2
fi

echo "=== [6/6] Provisioning summary ==="
id afbot
ls -ld "${SSH_DIR}" "${AUTH_KEYS_FILE}" "${CREDENTIALS_DIR}" "${SUDOERS_DROPIN}"
echo "SUCCESS: Kainode afbot provisioning complete."
EOF
chmod 700 /tmp/setup_kainode_afbot.sh
bash /tmp/setup_kainode_afbot.sh
rm -f /tmp/setup_kainode_afbot.sh
```

#### Method B: Raw GitHub One-Liner (Post-Merge)

Once the commit is pushed to `origin/main`:
```bash
curl -fsSL https://raw.githubusercontent.com/kipopopo/autonomous-futures-bot/main/scripts/setup_kainode_afbot.sh | sudo bash
```

#### In-Console Post-Execution Verification Commands

Run in the root console to verify immediate state:
```bash
id afbot
ls -la /home/afbot/.ssh
ls -ld /etc/autonomous-futures/credentials
cat /etc/sudoers.d/afbot-service
sudo -u afbot sudo -l
```

### 4.2 Safe SSH Connectivity Probe Specifications

All remote probes are non-destructive and use safety parameters to prevent hangs:
- `-o BatchMode=yes`: Prevents interactive password prompt fallbacks.
- `-o ConnectTimeout=5`: Bounds connection latency to 5 seconds.
- `-o StrictHostKeyChecking=accept-new`: Enforces known host key consistency while automatically recording new host keys.
- `-i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh"`: Directs OpenSSH to use the explicit operator identity.

**Windows PowerShell Probe**:
```powershell
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -i "$HOME\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "id"
```

**POSIX Bash Probe**:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -i ~/.ssh/kainode_ed25519_openssh afbot@147.79.18.15 "id"
```

### 4.3 Empirical Live Baseline (Before Remote Provisioning)

Conducted on 2026-09-03T16:01:42+08:00 from operator workstation:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -i "C:\Users\thaqi\.ssh\kainode_ed25519_openssh" afbot@147.79.18.15 "id"
```

**Verbatim Output**:
```text
afbot@147.79.18.15: Permission denied (publickey).
```
**Exit Status**: `1`

**Verbose Packet Trace (`ssh -vvv`) Evidence**:
```text
debug1: Remote protocol version 2.0, remote software version OpenSSH_9.6p1 Ubuntu-3ubuntu13.18
debug1: Host '147.79.18.15' is known and matches the ED25519 host key.
debug1: Will attempt key: C:\Users\thaqi\.ssh\kainode_ed25519_openssh ED25519 SHA256:3sel/5iY8Ug04ettqbneY2uUK5UAC6CoLIYYtgrmYDE explicit
debug1: Offering public key: C:\Users\thaqi\.ssh\kainode_ed25519_openssh ED25519 SHA256:3sel/5iY8Ug04ettqbneY2uUK5UAC6CoLIYYtgrmYDE explicit
debug3: send packet: type 50
debug2: we sent a publickey packet, wait for reply
debug3: receive packet: type 51
debug1: Authentications that can continue: publickey
debug2: we did not send a packet, disable method
debug1: No more authentication methods to try.
afbot@147.79.18.15: Permission denied (publickey).
```

**Cryptographic Deduction**:
1. Server receives Packet 50 (`SSH2_MSG_USERAUTH_REQUEST` for publickey).
2. Server immediately returns Packet 51 (`SSH2_MSG_USERAUTH_FAILURE`).
3. Zero Packet 60 (`SSH2_MSG_USERAUTH_PK_OK`) is returned. This mathematically proves that user `afbot` does not yet have this public key installed on `147.79.18.15`.
4. Web console provisioning is strictly required to install the key.

### 4.4 Before vs After Provisioning State Transition Model

| Inspection Target | Before Remote Provisioning (Current Empirical Baseline) | After Remote Provisioning (Expected Target State) |
|---|---|---|
| **Operator User** | `afbot` absent or unprovisioned | `afbot` exists (`uid >= 1000`, `gid >= 1000`, group `afbot`, shell `/bin/bash`, home `/home/afbot`) |
| **SSH Key Offer (Packet 50)** | Server returns Packet 51 (offer rejected; key unknown) | Server returns Packet 60 (`USERAUTH_PK_OK`, key recognized) |
| **Signature Verification** | Not reached | Server validates signature and returns Packet 52 (`USERAUTH_SUCCESS`) |
| **Probe Command Execution** | Fails with exit code 1 (`Permission denied (publickey)`) | Succeeds with exit code 0 (`uid=1000(afbot) gid=1000(afbot) groups=1000(afbot)`) |
| **Credentials Directory** | Absent | Present (`drwxr-x---`, mode `750`, owner `root:afbot`) |
| **Sudoers Management** | None | Restricted: `sudo systemctl {restart,status} autonomous-futures-*` without password |
| **Safety Invariants** | Zero secret leakage, `exchange_access=false`, `orders=0` | Zero secret leakage, `exchange_access=false`, `orders=0`, unpromoted state |

---

## 5. Security & Safety Invariants Verification

### 5.1 Invariants Compliance Matrix

| Invariant | Specification Requirement | Verification Status | Evidence |
|---|---|---|---|
| **Zero Secret Leakage** | Zero API keys, private keys, passwords, or tokens in code/reports | **CONFIRMED PASS** | Canary scanning across all new scripts, tests, and documentation; zero secrets found. |
| **Non-Root Target Execution** | Project services and operator sessions run as non-root `afbot` | **CONFIRMED PASS** | Script establishes non-root user `afbot` (shell `/bin/bash`, group `afbot`). |
| **Least Privilege Sudoers** | No blanket sudo access (`NOPASSWD: ALL` strictly prohibited) | **CONFIRMED PASS** | Whitelist limited strictly to project service restarts, status queries, and log inspections. |
| **Restricted Credentials Store** | Credentials directory inaccessible to unprivileged world | **CONFIRMED PASS** | Mode `750` with ownership `root:afbot` strictly enforced. |
| **Strict SSH Boundaries** | Mode `700` on `.ssh`, mode `600` on `authorized_keys` | **CONFIRMED PASS** | Enforced by script; verified by unit test assertions. |
| **Zero Exchange Access** | `exchange_access = false`, zero exchange URLs in codebase | **CONFIRMED PASS** | Script contains zero Binance or exchange endpoints. |
| **Zero Execution Authority** | `execution_authority = false`, `orders = 0` | **CONFIRMED PASS** | No trading execution logic present or invoked. |
| **Promotion State Invariant** | Promotion state remains `unpromoted` | **CONFIRMED PASS** | Staging offline research boundary maintained. |

### 5.2 Forensic Secret Leakage Audit

A comprehensive forensic search across the entire Phase 246 changeset confirms:
- **Private Key Canaries**: No instances of `BEGIN OPENSSH PRIVATE KEY`, `BEGIN RSA PRIVATE KEY`, `BEGIN PRIVATE KEY`, or PuTTY private key headers.
- **Google AI Studio Canaries**: No instances of `AIzaSy...` API keys.
- **Exchange Canaries**: No instances of `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `fapi.binance.com`, or `api.binance.com`.
- **Password Canaries**: No plaintext credentials or hardcoded secret variables.

---

## 6. Repository Verification Gates Results

All 6 repository verification gates were executed in sequence against the workspace root.

### 6.1 Gates Summary Table

| Gate | Verification Command | Target Scope | Result | Exit Code | Notes |
|---|---|---|---|---|---|
| **Gate 1** | `uv run --locked pytest -q` | Entire repository (`research/`, `tests/`) | **PASS** | `0` | **922 passed in 17.93s** (894 baseline + 28 new Phase 246 tests) |
| **Gate 2** | `uv run --locked ruff check src tests scripts` | Python linting | **PASS** | `0` | All checks passed cleanly with zero violations |
| **Gate 3** | `uv run --locked ruff format --check src tests scripts` | Formatting compliance | **PASS** | `0` | 364 files already formatted |
| **Gate 4** | `uv run --locked mypy src scripts` | Strict type checking | **PASS** | `0` | Success: no issues found in 187 source files |
| **Gate 5** | `uv lock --check` | Dependency lockfile parity | **PASS** | `0` | Resolved 67 packages in 0.94ms with zero modifications |
| **Gate 6** | `git diff --check` | Whitespace and merge conflict check | **PASS** | `0` | Clean diff with zero whitespace violations |

### 6.2 Verbatim Command Outputs for All 6 Gates

#### Gate 1: Pytest
```text
$ uv run --locked pytest -q
........................................................................ [  7%]
........................................................................ [ 15%]
........................................................................ [ 23%]
........................................................................ [ 31%]
........................................................................ [ 39%]
........................................................................ [ 46%]
........................................................................ [ 54%]
........................................................................ [ 62%]
........................................................................ [ 70%]
........................................................................ [ 78%]
........................................................................ [ 85%]
........................................................................ [ 93%]
..........................................................               [100%]
922 passed in 17.93s
```

#### Gate 2: Ruff Lint Check
```text
$ uv run --locked ruff check src tests scripts
All checks passed!
```

#### Gate 3: Ruff Format Check
```text
$ uv run --locked ruff format --check src tests scripts
364 files already formatted
```

#### Gate 4: Mypy Strict Type Check
```text
$ uv run --locked mypy src scripts
Success: no issues found in 187 source files
```

#### Gate 5: UV Lockfile Check
```text
$ uv lock --check
Resolved 67 packages in 0.94ms
```

#### Gate 6: Git Diff Check
```text
$ git diff --check
(clean exit, code 0)
```

---

## 7. Iteration 1 Forensic Audit Rejection & Iteration 2 Remediation Evidence

### 7.1 Iteration 1 Forensic Audit Finding

During independent forensic audit review (`auditor_phase246_1`), the initial Phase 246 deliverable was rejected with verdict **INTEGRITY VIOLATION**:
- **Defect Identified**: In `scripts/setup_kainode_afbot.sh` line 192 (Stage 6 summary block), the variable `${SUDOERS_FILE}` was evaluated under `set -euo pipefail`. Because the constant declared on line 66 was named `readonly SUDOERS_DROPIN="/etc/sudoers.d/afbot-service"`, `${SUDOERS_FILE}` was an unbound variable.
- **Empirical Failure Mode**: Live execution without `--dry-run` caused bash to terminate immediately at line 192 with:
  ```text
  scripts/setup_kainode_afbot.sh: line 192: SUDOERS_FILE: unbound variable
  Returncode: 1
  ```
- **Test Blind Spot**: The Iteration 1 test suite only executed `--dry-run`, `DRY_RUN=1`, or early-exit non-root gates, bypassing the non-dry-run Stage 6 summary path. `bash -n` only parses syntax/AST without evaluating variable expansions under `set -u`.

### 7.2 Root Cause Analysis

1. **Identifier Divergence**: Line 66 defined `readonly SUDOERS_DROPIN`, and lines 137, 158–164 referenced `${SUDOERS_DROPIN}`. However, line 192 referenced `${SUDOERS_FILE}` due to an inconsistent identifier name used during initial authoring of the summary block.
2. **Missing Live Summary Assertion**: Neither static variable binding analysis nor dynamic execution of the Stage 6 completion summary was present in the unit test suite.

### 7.3 Iteration 2 Remediation Actions

1. **Provisioning Script Correction (`scripts/setup_kainode_afbot.sh`)**:
   - Replaced `${SUDOERS_FILE}` with canonical `${SUDOERS_DROPIN}` at line 192.
   - Maintained strict UNIX LF line endings (`\n`), zero carriage returns, and zero trailing whitespace.
2. **Unit Test Suite Hardening (`tests/unit/test_setup_kainode_afbot.py`)**:
   - Updated `test_script_sudoers_file_path_and_mode` to explicitly assert `readonly SUDOERS_DROPIN` and assert `SUDOERS_FILE` is strictly absent from the script.
   - Added `test_script_all_variable_references_are_declared_or_builtin`: Static AST/regex analysis parsing active shell lines (filtering quoted heredocs and comments), identifying all variable assignments and loop declarations, and asserting that every `$VAR` and `${VAR}` expansion belongs to declared assignments or standard POSIX/bash builtins.
   - Added `test_stage6_completion_summary_dynamic_execution_zero_unbound_vars`: Dynamically executes the Stage 6 summary under `bash -s` with binary stdin (`input=test_script.encode("utf-8")`) under `set -euo pipefail` and `DRY_RUN=0`, asserting exit code 0 and successful summary emission.
3. **Runbook Consistency Alignment (`verification/PHASE_246_VERIFICATION.md`)**:
   - Aligned Section 4.1 Method A runbook heredoc to use `SUDOERS_DROPIN` everywhere instead of `SUDOERS_FILE` (lines 182, 238, 240, 252).
4. **Comprehensive Gate Re-Verification**:
   - All 6 repository verification gates executed and passed with 100% clean status (922 tests passed in 17.93s, zero lint violations, zero formatting issues, zero mypy type issues, lockfile verified, git diff clean).

---

## 8. Conclusion & Next Operational Steps

Phase 246 has successfully delivered the complete operator provisioning infrastructure, unit test coverage, runbook documentation, and empirical baseline verification for the Kainode VPS staging environment.

### Readiness for Phase 247:
1. **Operator Console Action**: Operator executes the Hostinger VPS Web Console runbook (Section 4.1) using root shell access.
2. **Post-Provisioning Verification**: Operator runs the safe SSH probe from workstation (`ssh -i ... afbot@147.79.18.15 "id"`), confirming transition from Packet 51 refusal to Packet 52 non-root authentication success.
3. **Phase 247 Staging Preflight**: Execute `python scripts/preflight_kainode_staging.py` over SSH under non-root account `afbot` to complete systemd encrypted credential delivery validation.
