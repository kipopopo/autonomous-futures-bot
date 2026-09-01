# Phase 212 Verification — secure provider credential staging guide

## Status

**DOCUMENTATION COMPLETE / PROVIDER BLOCKED**

This phase addressed the missing operator instruction for replacing the provider credential after it was pasted into chat. No credential value was reused, printed, persisted, or transferred by the agent.

- Verification time: `2026-09-01T06:13:31Z`
- Source commit before this phase: `32edcdca05c7e00a162f7a2df82d71a4ab01c16b`
- Host: `147.79.18.15`
- SSH operator: `afbot-admin`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`

## Delivered

Updated `infrastructure/OPENCODE_CREDENTIAL_HANDLING.md` with the smallest safe operator path:

- revoke the exposed key and create a replacement in the provider console;
- enter the replacement only at a hidden local Windows Git Bash prompt;
- stream it directly to the pinned VPS command over SSH;
- encrypt it with `systemd-creds --name=opencode_api_key`;
- enforce `root:root` ownership and mode `600`;
- verify metadata only, never credential contents.

The staging command refuses an empty input and the metadata command is standalone. Both shell blocks passed `bash -n` syntax validation.

## Remote read-only verification

The existing VPS credential source was inspected without reading its bytes:

```text
path_a=present
path_b=absent
mode=600 owner=root group=root type=regular file
research_timers=0
research_units=0
credential_bytes=not_read
```

No remote credential was changed. No provider completion request was made in this phase.

## Safety state

```text
provider_completion=blocked_pending_rotation
creator_requests=0
candidates=0
oos_windows=0
qualifications=0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
```

The exposed key must be revoked/rotated by the operator. The agent will not use it. No fallback provider, retry loop, scheduler, daemon, paper runtime, testnet order, or live order was introduced.

## Credential hygiene

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]

## Next work

After the operator rotates the exposed key and stages the replacement using the documented hidden prompt, run one fresh bounded authenticated completion probe. Only a passing probe permits the next cached Creator campaign; otherwise retain the fail-closed blocker.
