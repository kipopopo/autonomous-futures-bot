# Learner Page — Metric-Quality Qualification Evidence Override

## Information architecture

Add one distinct card under the existing Learner page:

```text
Metric-quality qualification evidence
├─ verification state: VERIFIED | UNAVAILABLE | INTEGRITY UNAVAILABLE
├─ qualification outcome: QUALIFIED | REJECTED (evidence only)
├─ source metric-quality decision: PASSED | FAILED
├─ policy identities: source policy + qualification policy
├─ gate evidence: source-decision / minimum-windows
├─ provenance: decision, review, metric-run, evidence hashes
└─ safety state: cached-only; unpromoted; paper OFF; execution OFF
```

This card must remain distinct from legacy `Learner qualification evidence`: the former derives from the persisted metric-quality decision chain; the latter is an independent quality-review qualification contract.

## Copy rules

- `QUALIFIED` means only this explicit metric-quality qualification evidence passed its own gates. It does **not** mean promoted, paper-active, live, executable, or profitable.
- `REJECTED` is valid persisted evidence, not an error.
- `UNAVAILABLE` means the API returned no configured artifact (`404`); render no inferred decision or metric.
- `INTEGRITY UNAVAILABLE` means the API returned an integrity failure (`503`); render no source artifact details or inferred decision.

## Component behavior

- Reuse the existing evidence-card layout, typography, HSL tokens, and no-motion behavior.
- Use a text badge plus semantic color for `QUALIFIED`/`REJECTED`; status text must remain understandable without color.
- Render exact persisted decimals/identifiers/hashes only; do not calculate or aggregate a metric in the browser.
- Render all source timestamps in MYT/GMT+8.
- The only interaction remains the existing global read-only refresh button.
