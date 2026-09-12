# Learner Quality Critic Review — 2026-09-12

## Decision

One bounded provider-backed Critic review was completed for the failed
`linear_next_return` learner-quality decision. The Critic response was accepted
as strict typed evidence with advisory decision `revise`.

```text
This does not authorize training, Creator revision, qualification, promotion,
paper activation, testnet/live execution, or order routing.
```

## Model and request boundary

```text
assistant model:             GPT-5.6 Luna
assistant provider:          OpenAI Codex
assistant effort:            Medium
embedded Critic model:       gemma-4-31b-it
provider:                    Google AI Studio OpenAI-compatible endpoint
max_output_tokens:           1024
temperature:                 0.0
provider retries:            0
fallback provider:           false
```

The request was built only after loading the persisted metric evaluation,
corrected observed-only review, and failed metric-quality decision through the
shared verified readers.

```text
source decision ID:          metric-quality-decision-holdout-v4-20260912
source decision hash:        1a50b1bddb2489c55437ed98917d63a615e84dfbe907c62ef5eb90123f46643c
source decision:              failed
request critic run ID:       run-learner-quality-critic-setup2-20260912
request hash:                ccf95d89ddeb77932e7a58918c00f48a84cae9bdccc06248ba3c45f1a87d9ec1
candidate:                   cand-learner-bootstrap-20260912
candidate artifact hash:     ff820a97555add3c28a7986ac60319536bcd54ad582fc35a6e54097834f0a5ff
learner:                     learner-holdout-20260912
learner artifact hash:       10ba3cba75483d131d67748b3f69395d9426dca90e006eed9f3fe3ff0707fea7
metric evaluation:           learner-holdout-evaluation-v3-20260912
metric evaluation hash:      1867c66fd4bbdb4c2a2788d1fc9ca19ce74687a805ae70cfcfb1c23b76454596
failure reason codes:        metric_below_threshold
```

## Actual provider result

Exactly one provider request was issued by the corrected run:

```text
provider requests:           1
provider HTTP attempts:      1
HTTP status:                 200
choice count:                1
content kind:                string
content length:              484
finish reason:               stop
raw response retained:       false
```

Safe provider metadata retained in the typed evidence:

```text
content SHA-256:             8080df2179ae67526f581b7f8ca126644fe660f9e3f0181d2214a82695b93f9e
response keys:                choices, created, id, model, object, usage
```

The strict response was:

```text
Critic result:                accepted
Critic review ID:             review-learner-quality-critic-run-learner-quality-critic-setup2-20260912
Critic review hash:           b1523231b9f948e894827fa292c6a86a68350985fdef1091e6dd11b5b6c16afc
Critic decision:              revise
failure reasons preserved:    metric_below_threshold
advisory actions:             add_cross_symbol_validation
                              add_temporal_holdout
                              change_target_definition
```

The actions are bounded identifiers only. They were not executed.

## Persisted evidence

Accepted Critic evidence was written once and independently read back through
the shared typed reader:

```text
final root:                  /opt/autonomous-futures-bot/research/learner-evidence/learner-quality-critic-v2-20260912/
evidence path:               evidence/evidence.json
evidence ID:                 learner-quality-critic-evidence-holdout-v4-setup2-20260912
evidence hash:               308402cbae6f151747123b89b81d7c07cc8ece89119a3d27f15a46964517bf7f
readback:                    pass
source bytes preserved:      true
```

The evidence binds the exact source decision/request hash, review hash,
metric-evaluation hash, learner/candidate hashes, bundle/registry lineage, and
failure reasons.

## Setup correction and attempt accounting

The first transient-unit invocation did not reach the Python runner:

```text
systemd result:              exit-code
status:                      200/CHDIR
service runtime:             30ms
provider requests:           0
failure:                     host /tmp path was hidden by PrivateTmp=yes
```

Systemd journal confirmed `Changing to the requested working directory failed`.
That root was removed. A fresh setup-correction scope and Critic run ID were
used only after proving zero provider requests.

The corrected run reached the provider and persisted typed evidence, but its
runner-side in-memory equality check failed because JSON readback normalized
metadata tuples to lists. No provider retry was made. A fresh-process typed
readback verified the persisted artifact and the exact full provenance chain;
the typed evidence was then published to the final root.

## Remote operational safety

Before the provider request:

```text
host ED25519 fingerprint:    SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ
operator:                    afbot-admin (non-root SSH route)
credential source:           mode 600, root:root, regular file, size 223 bytes
scheduler:                   active before controlled pause
research timers:             0
```

The explicitly authorized scheduler pause/resume was completed:

```text
scheduler during request:    inactive
scheduler final state:       active/running
paper daemon final state:    active/running
paper MainPID:               unchanged at 815566
Critic transient unit:       not-found
temporary remote root:       absent
research timers:             0
local temporary files:       clean
```

The paper daemon was not stopped or restarted. No runtime database, candidate
registry, strategy state, or service configuration was changed.

## Safety boundary

```text
data source:                 cached_only
exchange access:             false
training calls:              0
Creator mutation:            0
candidate mutation:          0
qualification mutation:      0
promotion state:             unpromoted
paper activation:            false
execution authority:         false
testnet/live orders:          0
raw prompt persisted:        false
raw provider response:       false
credential value exposed:    false
```

A valid Critic response is advisory evidence only. `revise` is not an automatic
permission to retrain. The three returned actions must pass a separately
approved learner-training/data contract before any future execution, and no such
handoff was run here.

## Implementation and verification

Implementation commit:

```text
5de8013f468f0a845d032f6d7d3422c6f89d1a07
```

Delivered files:

```text
src/autonomous_futures/research/learner_metric_quality_critic.py
src/autonomous_futures/research/learner_metric_quality_critic_provider.py
src/autonomous_futures/research/__init__.py
 tests/unit/test_learner_metric_quality_critic.py
```

Verification:

```text
new Critic/provider/training regression: 23 passed in 1.02s
Ruff check:                             passed
Ruff format --check:                    481 files already formatted
Mypy src scripts:                       Success, 240 source files
uv lock --check:                        passed
changed-module py_compile:              passed
git diff --check:                       passed
GitHub quality for 5de8013:             success
fresh post-commit regression:           23 passed in 1.02s
```

No browser/API dogfood was applicable: this was a backend contract and one-shot
provider operation with no new HTTP service or UI surface.

## Next boundary

Stop this Critic request here. Do not automatically execute its `revise` actions.
A future step needs separate authorization for an explicit learner-training
handoff with exact causal windows and a new immutable run/evidence scope.
