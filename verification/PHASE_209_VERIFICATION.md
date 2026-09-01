# Phase 209 Verification — OpenCode Provider Transport Recovery Boundary

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase tested recovery of the bounded OpenCode Creator path after the Phase 208 provider transport rejection. The provider path was not stable for the full Creator request, so the pipeline stopped before candidate generation, cached OOS evaluation, qualification, promotion, paper activation, or execution.

- Verification time: `2026-09-01T04:49:58Z`
- Source commit used for the remote runner: `b1aa0760c9eece833db5a1aaa10193d0fc2d25ae`
- Host: `147.79.18.15`
- Remote operator: `afbot-admin`
- Requested family: `experimental`
- Provider: `opencode`
- Model: `deepseek-v4-flash`
- Dataset: cached DOGEUSDT 365-day bundle
- Cached rows: `105120`
- Planned OOS windows: `4`
- Forbidden candidate IDs: `51`

## Transport diagnostics

Diagnostics were bounded and recorded only safe status, shape, timing, and type metadata. No credential value, authorization header, raw provider response, or private payload was printed or persisted.

1. Provider DNS/TLS reachability passed through both default routing and IPv4. The no-secret `/models` request reached the provider, and the no-secret completion POST returned the expected unauthorized response.
2. Encrypted credential delivery passed in a transient non-root unit using the canonical runtime name `opencode_api_key`. The runtime credential file was present; its value was not read into output.
3. An authenticated `/models` probe succeeded. The catalog contained `deepseek-v4-flash`; the catalog count was `63`.
4. A minimal authenticated JSON completion succeeded with a 2xx response, JSON object, choices, and string content.
5. The exact Creator payload was approximately `3901` characters. One direct exact-payload probe at `temperature=0.0`, `max_tokens=2048` succeeded in `21.8s` with valid JSON and `1554` response bytes.
6. A direct exact-payload probe at `temperature=0.2`, `max_tokens=2048` returned a provider 5xx after approximately `135.0s`.
7. A direct exact-payload probe at `temperature=0.0`, `max_tokens=2048`, with a `240s` read timeout ended as `ReadTimeout` after `240.8s`.

Conclusion: credentials, model availability, endpoint reachability, and JSON request shape were verified. Full Creator completion latency/availability remained unstable at the provider boundary.

## Durable campaign evidence

Each scope was isolated and read back through the typed evidence reader. Each has one provider request and one rejected trial. No candidate, OOS, or qualification artifact was created.

| Scope | `max_output_tokens` | Provider requests | HTTP attempts | Trial decision | Reason | Trial evidence hash |
|---|---:|---:|---:|---|---|---|
| `creator-batch-20260901-033` | 4096 | 1 | 1 | `rejected` | `provider_transport_error` | `ef450770b4150f4a4b14f3a9361a17e341f7fedf960676049f21b61f58eb8bd0` |
| `creator-batch-20260901-034` | 4096 | 1 | 1 | `rejected` | `provider_transport_error` | `e071c4be70605bb3d8e3487a14fe8f27873de711b228b112034f2e26948b65e5` |
| `creator-batch-20260901-035` | 2048 | 1 | 1 | `rejected` | `provider_transport_error` | `2e6fc7124fcff65efb321c5a079c931719bc24984a0b0febf1053fe14b1e3d2c` |
| `creator-batch-20260901-036` | 2048 | 1 | 1 | `rejected` | `provider_transport_error` | `9ddd23f7399924c29e36195756c2397c0e1b9bd04faeb4d94e019fb300ac9cfa` |

Durable evidence roots:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260901-033
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260901-034
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260901-035
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260901-036
```

All four roots were owned by `afbot-admin:afbot-admin` with mode `750`.

## Safety and negative assertions

Readback confirmed for every scope:

```text
candidate_entries=[]
oos_entries=[]
qualification_entries=[]
exchange_access=false
execution_authority=false
orders=0
paper_activation=false
promotion_state=unpromoted
```

Remote verification also confirmed:

```text
transient_units=0
research_timers=0
remote_temp_cleanup=true
local_temp_cleanup=true
```

No provider fallback, automatic retry loop, exchange access, paper activation, testnet order, live order, scheduler, daemon, or persistent service was started.

## Decision

The provider transport recovery gate remains **blocked**. The evidence does not support a candidate qualification claim and gives no promotion or execution authority.

The next permitted step is a fresh bounded provider probe after the provider-side latency/5xx condition is resolved. Do not add a fallback model or unattended retry loop merely to make the campaign complete.
