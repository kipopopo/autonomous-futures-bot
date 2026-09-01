# Phase 210 Verification — provider authorization boundary

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase performed one bounded provider recovery preflight after Phase 209. The authenticated completion gate returned HTTP 401, so the process stopped before a Creator request, candidate generation, cached OOS evaluation, qualification, promotion, paper activation, or execution.

- Verification time: `2026-09-01T05:31:23Z`
- Source commit: `a8f228fb58224bfb85c448b88175ddd3e7c2d989`
- Host: `147.79.18.15`
- SSH operator: `afbot-admin`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`
- Provider: `opencode`
- Model: `deepseek-v4-flash`

## Preconditions

The live host key matched the pinned fingerprint. The SSH route and non-interactive sudo check passed. Remote research state was clean before the probe:

```text
ssh_route=ok
identity=afbot-admin
sudo_noninteractive=ok
research_units=0
research_timers=0
provider_dns=ok
provider_http=200
github_http=200
```

The provider endpoint was reachable without credentials. An encrypted systemd credential was attached to the collected non-root probe unit without printing or persisting its value. The unit completed and was collected; no credential contents were exposed.

## Provider probe results

A credential-bearing `/models` request returned HTTP 200 in `0.741369` seconds. This is recorded as endpoint/model transport evidence only; `/models` availability is not treated as proof that completion authorization works.

A tiny authenticated JSON completion request using the pinned model, JSON response format, `temperature=0.0`, and `max_tokens=16` returned:

```text
status=401
elapsed_seconds=0.749687
curl_exit=0
```

No response body, authorization header, credential value, or raw request payload was printed or persisted. A credential-free comparison was attempted only as a diagnostic; its console classification was redacted and is not used as evidence.

## Campaign decision

The authenticated completion gate did not pass, therefore no cached Creator campaign was started:

```text
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

The HTTP 401 is an authorization/provider-contract failure at the completion boundary. It is not evidence of a valid proposal, candidate quality, OOS result, or qualification outcome. No fallback model, automatic retry loop, credential rotation, or request-body logging was used.

## Cleanup

The transient unit was collected and verified absent:

```text
transient_run_exit=0
unit_after_run=not-found
research_timers=0
```

No project service, timer, scheduler, daemon, persistent provider loop, exchange endpoint, paper runtime, testnet order, or live order was started. No local temporary runner or source archive was created.

## Credential hygiene

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]

## Conclusion

Provider recovery remains **BLOCKED**. The next permitted action is provider-side authorization/configuration repair followed by one fresh bounded completion probe. Do not run the Creator campaign, add a fallback, or introduce unattended retries while the completion gate returns HTTP 401.
