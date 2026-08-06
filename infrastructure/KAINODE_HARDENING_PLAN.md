# Kainode Security Hardening Plan — Autonomous Futures Bot

## Scope

This runbook prepares the clean Kainode VPS for the project. It must be executed in phases so SSH access is verified before any root/password restriction is applied.

## Current known baseline

- Ubuntu 24.04.4 LTS
- 6 vCPU, approximately 15 GiB usable RAM, approximately 116 GiB root disk
- UFW inactive
- root SSH login enabled
- password SSH login enabled
- root authorized key absent
- no application service deployed
- no exchange credential or OpenCode credential installed

## Safe execution order

1. Confirm a local operator SSH key exists or create one with a protected passphrase.
2. Install the public key for a new non-root administrative/deploy user.
3. Open a second SSH session as that user and verify `sudo` access.
4. Install security updates and fail2ban without removing the recovery path.
5. Enable UFW default deny; allow SSH only on the approved management port and source policy.
6. Recheck the second SSH session and a fresh connection after UFW activation.
7. Disable root SSH login and password authentication only after key-based recovery is verified.
8. Reconnect in a fresh session and record the resulting baseline.
9. Only after this report passes: install the project runtime, PostgreSQL 18, and service units.

## Safety rules

- Never close the original verified root session until the new non-root key session works.
- Do not copy any API key during hardening.
- Do not open PostgreSQL publicly.
- Do not expose a dashboard port before the reverse proxy/TLS policy is defined.
- Keep a documented rollback path for `sshd`, UFW, and fail2ban changes.
- Hardening is configuration work; it is separate from application development and trading authority.

## Current status

- Plan prepared: complete.
- Read-only access preflight: complete.
- Local operator key: existing ED25519 key verified; private-key Windows ACL is limited to the operator, Administrators, and SYSTEM.
- Non-root administrative user: `afbot` created with key-only SSH and verified non-interactive sudo.
- Security packages: `ufw` and `fail2ban` installed; fail2ban active/enabled; unattended security-updates package present.
- Firewall: active; default deny incoming, allow outgoing; SSH port 22 is the only explicit inbound rule.
- SSH hardening: verified effective `PermitRootLogin=no`, `PasswordAuthentication=no`, `KbdInteractiveAuthentication=no`, `PubkeyAuthentication=yes`.
- Failed systemd units: none observed.
- Project deployment area: empty.
- Pending maintenance: package installation reported a newer kernel (`6.8.0-137-generic`) while the host is still running `6.8.0-124-generic`; reboot is deferred until an explicit maintenance window and post-reboot SSH verification plan.
- Project runtime, PostgreSQL, exchange credentials, OpenCode credentials, and application services: not installed.
