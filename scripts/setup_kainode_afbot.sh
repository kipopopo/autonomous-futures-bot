#!/usr/bin/env bash
# ==============================================================================
# Autonomous Futures Bot - Kainode VPS Operator Provisioning Script
# Target Host: Kainode VPS (147.79.18.15) - Ubuntu 24.04 LTS (Noble Numbat)
#
# Provisions non-root operator account 'afbot':
#   - User 'afbot' with group 'afbot', shell '/bin/bash', home '/home/afbot'
#   - SSH directory /home/afbot/.ssh (mode 700, afbot:afbot)
#   - Authorized keys /home/afbot/.ssh/authorized_keys (mode 600, afbot:afbot)
#   - Pinned operator public key (ssh-ed25519 eddsa-key-20260901)
#   - Credential directory /etc/autonomous-futures/credentials (mode 750, root:afbot)
#   - Restricted sudoers drop-in /etc/sudoers.d/afbot-service (mode 0440, root:root)
#   - Verifies systemd-creds binary capability without leaking secrets
#
# Safety & Invariants:
#   - set -euo pipefail
#   - IFS=$'\n\t'
#   - EUID 0 (root) check (bypassed only under --dry-run)
#   - Zero private keys, passwords, API tokens, or exchange endpoints
# ==============================================================================
set -euo pipefail
IFS=$'\n\t'

# Parse optional arguments
DRY_RUN="${DRY_RUN:-0}"
for arg in "$@"; do
    case "${arg}" in
        --dry-run)
            DRY_RUN=1
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run]"
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option '${arg}'" >&2
            echo "Usage: $0 [--dry-run]" >&2
            exit 1
            ;;
    esac
done

# Root privilege verification
if [[ "${DRY_RUN}" != "1" ]] && [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: scripts/setup_kainode_afbot.sh must be executed as root (EUID 0)." >&2
    exit 1
fi

if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[DRY-RUN] Running in simulation mode. No host modifications will be performed."
fi

# Target identity and filesystem paths
readonly TARGET_USER="afbot"
readonly TARGET_GROUP="afbot"
readonly TARGET_SHELL="/bin/bash"
readonly TARGET_HOME="/home/afbot"

readonly SSH_DIR="${TARGET_HOME}/.ssh"
readonly AUTH_KEYS_FILE="${SSH_DIR}/authorized_keys"
readonly OPERATOR_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMJJ0UAlUCOTwKyqG0+vpNr3e7nr6trU3C3kqIQgWShY eddsa-key-20260901"

readonly CREDENTIALS_PARENT_DIR="/etc/autonomous-futures"
readonly CREDENTIALS_DIR="${CREDENTIALS_PARENT_DIR}/credentials"

readonly SUDOERS_DROPIN="/etc/sudoers.d/afbot-service"

# Stage 1: Group and user provisioning
echo "=== [1/6] Provisioning group and user ==="
if getent group "${TARGET_GROUP}" >/dev/null 2>&1; then
    echo "Group '${TARGET_GROUP}' already exists."
else
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "[DRY-RUN] Would create group '${TARGET_GROUP}'."
    else
        groupadd "${TARGET_GROUP}"
        echo "Created group '${TARGET_GROUP}'."
    fi
fi

if id -u "${TARGET_USER}" >/dev/null 2>&1; then
    echo "User '${TARGET_USER}' already exists."
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "[DRY-RUN] Would reconcile shell to '${TARGET_SHELL}' and group to '${TARGET_GROUP}' for '${TARGET_USER}'."
    else
        usermod -s "${TARGET_SHELL}" -g "${TARGET_GROUP}" "${TARGET_USER}"
        echo "Reconciled shell and group for user '${TARGET_USER}'."
    fi
else
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "[DRY-RUN] Would create user '${TARGET_USER}' with shell '${TARGET_SHELL}', home '${TARGET_HOME}', and group '${TARGET_GROUP}'."
    else
        useradd -m -g "${TARGET_GROUP}" -s "${TARGET_SHELL}" -d "${TARGET_HOME}" "${TARGET_USER}"
        echo "Created user '${TARGET_USER}'."
    fi
fi

# Stage 2: SSH directory and authorized_keys setup
echo "=== [2/6] Configuring SSH directory and authorized keys ==="
if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[DRY-RUN] Would create '${SSH_DIR}' (mode 700, owner ${TARGET_USER}:${TARGET_GROUP})."
    echo "[DRY-RUN] Would configure '${AUTH_KEYS_FILE}' (mode 600, owner ${TARGET_USER}:${TARGET_GROUP})."
    echo "[DRY-RUN] Would idempotently install pinned operator public key."
else
    mkdir -p "${SSH_DIR}"
    chmod 700 "${SSH_DIR}"
    chown "${TARGET_USER}:${TARGET_GROUP}" "${SSH_DIR}"

    touch "${AUTH_KEYS_FILE}"
    if ! grep -q -F "${OPERATOR_PUBKEY}" "${AUTH_KEYS_FILE}"; then
        if [[ -s "${AUTH_KEYS_FILE}" ]] && [[ -n "$(tail -c1 "${AUTH_KEYS_FILE}" 2>/dev/null)" ]]; then
            echo "" >> "${AUTH_KEYS_FILE}"
        fi
        echo "${OPERATOR_PUBKEY}" >> "${AUTH_KEYS_FILE}"
        echo "Installed operator public key in ${AUTH_KEYS_FILE}."
    else
        echo "Operator public key already present in ${AUTH_KEYS_FILE}."
    fi
    chmod 600 "${AUTH_KEYS_FILE}"
    chown "${TARGET_USER}:${TARGET_GROUP}" "${AUTH_KEYS_FILE}"
fi

# Stage 3: Credentials directory setup
echo "=== [3/6] Configuring credentials directory ==="
if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[DRY-RUN] Would create '${CREDENTIALS_DIR}' (mode 750, owner root:${TARGET_GROUP})."
else
    mkdir -p "${CREDENTIALS_DIR}"
    chmod 750 "${CREDENTIALS_DIR}"
    chown root:"${TARGET_GROUP}" "${CREDENTIALS_DIR}"
    echo "Configured ${CREDENTIALS_DIR} (mode 750, owner root:${TARGET_GROUP})."
fi

# Stage 4: Restricted sudoers drop-in
echo "=== [4/6] Configuring restricted sudoers drop-in ==="
if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[DRY-RUN] Would validate via visudo -cf and install '${SUDOERS_DROPIN}' (mode 0440, owner root:root)."
    echo "[DRY-RUN] Allowed commands: systemctl {restart,status} autonomous-futures-*, journalctl -u autonomous-futures-*"
else
    TMP_SUDOERS="$(mktemp /tmp/afbot-service.XXXXXX 2>/dev/null || mktemp)"
    cat << 'EOF' > "${TMP_SUDOERS}"
# Restricted service management privileges for Autonomous Futures Bot operator
# Managed by scripts/setup_kainode_afbot.sh
afbot ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart autonomous-futures-*, /usr/bin/systemctl status autonomous-futures-*, /usr/bin/journalctl -u autonomous-futures-*, /bin/systemctl restart autonomous-futures-*, /bin/systemctl status autonomous-futures-*, /bin/journalctl -u autonomous-futures-*
EOF
    chmod 440 "${TMP_SUDOERS}"
    chown root:root "${TMP_SUDOERS}" 2>/dev/null || true

    if command -v visudo >/dev/null 2>&1; then
        if ! visudo -cf "${TMP_SUDOERS}"; then
            echo "ERROR: visudo validation failed for generated sudoers configuration." >&2
            rm -f "${TMP_SUDOERS}"
            exit 1
        fi
        echo "Validated sudoers configuration with visudo -cf."
    fi

    install -m 0440 -o root -g root "${TMP_SUDOERS}" "${SUDOERS_DROPIN}" 2>/dev/null || {
        cp "${TMP_SUDOERS}" "${SUDOERS_DROPIN}"
        chmod 440 "${SUDOERS_DROPIN}"
        chown root:root "${SUDOERS_DROPIN}" 2>/dev/null || true
    }
    rm -f "${TMP_SUDOERS}"
    echo "Installed restricted sudoers rule at ${SUDOERS_DROPIN}."
fi

# Stage 5: Host capability verification
echo "=== [5/6] Verifying host systemd-creds capability ==="
if command -v systemd-creds >/dev/null 2>&1; then
    SYSTEMD_CREDS_PATH="$(command -v systemd-creds)"
    echo "Verified systemd-creds present at ${SYSTEMD_CREDS_PATH}."
    SYSTEMD_CREDS_VERSION="$(systemd-creds --version 2>&1 | head -n 1)"
    echo "Found systemd-creds version: ${SYSTEMD_CREDS_VERSION}"
else
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "[DRY-RUN] Notice: systemd-creds binary not found in current PATH."
    else
        echo "WARNING: systemd-creds binary not found in PATH." >&2
    fi
fi

# Stage 6: Summary
echo "=== [6/6] Provisioning summary ==="
if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[DRY-RUN] Simulation completed successfully with zero modifications to the host."
else
    echo "SUCCESS: Operator 'afbot' provisioned successfully on Kainode VPS."
    echo "  - User/Group: ${TARGET_USER}:${TARGET_GROUP} (shell: ${TARGET_SHELL}, home: ${TARGET_HOME})"
    echo "  - SSH Directory: ${SSH_DIR} (mode 700, owner ${TARGET_USER}:${TARGET_GROUP})"
    echo "  - Authorized Keys: ${AUTH_KEYS_FILE} (mode 600, owner ${TARGET_USER}:${TARGET_GROUP})"
    echo "  - Credentials Store: ${CREDENTIALS_DIR} (mode 750, owner root:${TARGET_GROUP})"
    echo "  - Sudoers Drop-In: ${SUDOERS_DROPIN} (mode 0440, owner root:root)"
fi
