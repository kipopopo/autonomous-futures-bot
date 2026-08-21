# Phase 43 Verification — Kainode SSH/UFW hardening

## Scope

Phase 43 applies the approved two-session SSH/UFW hardening sequence to Kainode. No application secret, service, scheduler, or live transport was installed.

## Before state

```text
UFW: inactive
PermitRootLogin: yes
PasswordAuthentication: yes
PubkeyAuthentication: yes
```

## Hardening applied

```text
admin user: afbot-admin
admin key login: verified in fresh session
admin sudo: non-interactive sudo verified
UFW: enabled
UFW incoming: deny by default
UFW outgoing: allow by default
SSH allow rule: TCP/22 only
PermitRootLogin: no
PasswordAuthentication: no
KbdInteractiveAuthentication: no
PubkeyAuthentication: yes
```

The original root session was not used as the recovery path after the change; a new `afbot-admin` key session was opened and verified before completion.

## Host baseline

```text
host: 147.79.18.15
hostname: kipopopo
OS: Ubuntu 24.04.4 LTS
NTP: synchronized
unattended-upgrades: active
failed systemd units: none
systemd-creds: present, encryption supported
```

## Application safety

```text
project service: none
project timer: none
live secrets installed: no
.env on VPS: absent
live transport enabled: no
live order: 0
```

## Verification

```text
Local locked suite:      629 passed
Local Ruff/format/mypy:  passed
Local uv lock:           passed
Local git diff:          clean
Remote admin key login:  passed
Remote UFW verification: passed
Remote sshd -T:          passed
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (historical bounded testnet evidence only)
live_enabled=false
network_allowed=false
new_actions_allowed=false
```

Secret-manager staging and any production service remain separate boundaries. No live credential was transferred in Phase 43.
