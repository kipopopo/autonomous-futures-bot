# Phase 208 Verification — bounded experimental-family campaign

## Runtime

```text
assistant runtime: GPT-5.6 Luna
assistant provider: OpenAI Codex
embedded Creator model: deepseek-v4-flash
```

## Scope

One bounded DOGEUSDT cached research campaign was prepared for the new `experimental` family:

```text
exact pushed source commit 7638226
→ encrypted one-shot OpenCode Creator request
→ strict dsl_version=2 + bounded risk guard
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

The campaign was bound to the existing immutable DOGEUSDT 5m dataset:

```text
rows:                 105120
bundle hash:          30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3
dataset registry hash:17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
OOS windows planned:  4
forbidden IDs:        51
```

The final one-shot unit used `LoadCredentialEncrypted` for the provider credential, ran as `afbot-admin`, and did not load exchange credentials or call exchange endpoints.

## Actual result

```text
research run:         run-doge-experimental-032
Creator run:          doge-creator-experimental-032
provider requests:    1
provider HTTP attempts:1
Creator decision:     rejected
reason:               provider_transport_error
accepted candidates:  0
OOS windows evaluated:0
qualification:        not created
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260901-032
```

Persisted trial readback:

```text
decision:             rejected
reason:               provider_transport_error
evidence hash:        501e890b3679ad96eec9c8c786cd644c40afa42f8b818ec82c3159ad2ef9ed26
```

Independent readback found no candidate, OOS, or qualification entries. No candidate ID or raw provider response was persisted.

Two earlier temporary-runner corrections reached the provider but stopped before persistence; their raw responses were not retained. The final persisted invocation above is the only invocation represented by the durable batch summary.

## Safety and cleanup

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
live_enabled=false
exchange_access=false
orders=0
research timers/services=0
transient systemd unit=removed
temporary VPS source/runner=removed
local temporary source/runner=removed
```

## Verification

```text
SSH account: afbot-admin
host:        kipopopo
source:      7638226 == origin/main
remote trial/summary readback: passed
remote cleanup:                passed
```

## Conclusion

The risk-aware cached qualification path is wired and fail-closed, but this campaign did not reach candidate evaluation because the bounded Creator transport failed. No profitability, qualification, paper-readiness, testnet-readiness, or live-readiness claim follows. The next attempt requires an explicit provider transport recovery; no automatic retry or fallback was used.
