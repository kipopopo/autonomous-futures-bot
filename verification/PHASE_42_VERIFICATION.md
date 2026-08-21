# Phase 42 Verification — Kainode code-only deployment

## Scope

Phase 42 deploys the paper-safe code release to Kainode and verifies it remotely. It does not install secrets, create services, enable live transport, or place orders.

## Target

```text
host: 147.79.18.15
remote hostname: kipopopo
remote user: root
remote OS: Ubuntu 24.04.4 LTS
remote kernel: Linux 6.8.0-124-generic x86_64
```

SSH host identity was verified out-of-band through the VPS console:

```text
ED25519: SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdQ
```

The pinned Plink connection used the equivalent verified MD5 fingerprint only because the installed Plink parser rejected the SHA-256 string containing `/`.

## Deployment

```text
remote path: /root/autonomous-futures-bot
release files: src/tests + pyproject.toml + uv.lock + .gitignore
release manifest: 1eb53f60c0cafe471c5321b9997a608cb1da99bab5504e16889f266a280717d2
manifest parity: local == remote
```

Excluded intentionally:

```text
.env and credentials
.git
virtualenv/cache files
SQLite/runtime databases
market-data CSV files
market-data parquet files
```

Research code/evidence text and JSON were deployed without the large local market-data datasets.

Remote runtime setup:

```text
uv: 0.12.5
managed Python: 3.14.7
locked environment: created successfully
```

## Remote verification

```text
Remote tests suite:       621 passed
Ruff check:               passed
Ruff format:              passed
Mypy:                     161 source files clean
uv lock --check:          passed
.env:                     absent
SQLite runtime DBs:       0
project systemd units:    0
project timers:           0
```

Local `tests/` collection is also 621; the eight research tests are not part of this code-only VPS package because their local market-data datasets were intentionally excluded.

Typed deployed safety defaults:

```text
LiveOrderRequest.live_enabled: false
LiveActivationToken.live_enabled: false
LiveActivationToken.network_allowed: false
```

## Production blockers

```text
UFW: inactive
live secrets: not transferred
live transport: not enabled
systemd service: not created
scheduler/timer: not created
production order: 0
```

The VPS is code-staged but not production/live-ready. Firewall hardening, secret-manager delivery, service design, and any production transport remain separate approved boundaries.

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (historical bounded testnet evidence only)
live_enabled=false
network_allowed=false
new_actions_allowed=false
```
