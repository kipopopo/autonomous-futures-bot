# Phase 44 Verification — encrypted live credential staging

## Scope

Phase 44 stages the two live credential values from the ignored local `.env` into encrypted systemd credential artifacts on Kainode. Values were never printed, committed, logged, or placed in command arguments.

No service, scheduler, live transport, or order was enabled.

## Remote secret path

```text
/etc/autonomous-futures/credentials/BINANCE_LIVE_API_KEY
/etc/autonomous-futures/credentials/BINANCE_LIVE_SECRET_KEY
```

Artifacts are:

```text
root:root
mode: 600
systemd-creds host-key encrypted
```

The encrypted filename matches the embedded credential name, allowing a future unit to reference the logical names without exposing values.

## Verification

Each artifact was decrypted only into a temporary `/run` path, hashed, compared to the local source value hash, and removed immediately:

```text
BINANCE_LIVE_API_KEY:   hash match
BINANCE_LIVE_SECRET_KEY: hash match
plaintext temporary files remaining: 0
```

Additional state:

```text
VPS project .env: absent
project systemd unit: none
project timer: none
live transport: disabled
live order: 0
```

`systemd-creds` host key was initialized and encryption is supported. The tool warned that `/var/lib/systemd/credential.secret` is not on encrypted media; this remains a production hardening caveat. TPM2 availability is not being treated as a passed requirement.

## TDD/local verification

```text
Locked full suite:       629 passed
Ruff check:              passed
Ruff format:             passed
Mypy:                    161 source files clean
uv lock --check:         passed
git diff --check:        passed
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

Phase 44 only stages encrypted credentials. A future service must consume them through `LoadCredentialEncrypted=` and pass a separate production preflight before any live transport can be enabled.
