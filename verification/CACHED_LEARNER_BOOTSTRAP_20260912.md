# Cached Learner Bootstrap — 2026-09-12

## Decision

One explicit cached-only learner bootstrap completed successfully as
**TESTING / PREPARED** evidence. It is not learner qualification, model-quality
proof, paper admission, promotion, or execution authority.

The bootstrap used the existing learner pipeline and a deterministic
`linear_next_return` baseline trainer. No production code change was needed.

## Provenance

```text
source commit:        818f7553e814334b840b1a71a4617517e4be0d54
bundle hash:          108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry hash:        ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
symbols:              BTCUSDT, ETHUSDT, SOLUSDT
training range:       2026-07-01T00:00:00Z → 2026-08-06T05:30:00Z
primary rows/symbol:  10,434
```

The runner loaded the persisted bundle and independently verified all `13`
bundle components before materializing learner inputs. Primary 5m and closed
15m context frames were passed as deep copies to the explicit trainer. The
learner input frame contained the declared causal `returns` feature and no
signal column.

## Testing artifacts

```text
candidate:            cand-learner-bootstrap-20260912
candidate hash:       ff820a97555add3c28a7986ac60319536bcd54ad582fc35a6e54097834f0a5ff
candidate state:      testing

learner:              learner-bootstrap-20260912
learner hash:         fb4c96c1baa529edebbf023f769736920a718440020eb84692bbca95cf2f8aa9
learner version:      learner-bootstrap-v1
model family:         linear_next_return
model hash:           0d53c733b7dd96346910983df2e106d0a71a70052d18fc7c287a69cf31c2f0f4
model bytes:          365

prepared run:         run-learner-bootstrap-20260912
prepared run hash:    cfff571c1bb617e34ee7d98ea0ac61a6bc2d2bea7dff5242e2ea4e254c592ded
run status:           prepared
feature IDs:          returns
```

The baseline objective is `next_bar_close_return`, using only the causal
`returns` feature with declared shift `1`. Model bytes are persisted as an
explicit testing artifact; no training metrics are attached by this boundary.

Remote evidence paths are kept outside source control:

```text
research/learner-evidence/bootstrap-20260912/candidate/candidate.json
research/learner-evidence/bootstrap-20260912/models/linear-next-return.json
research/learner-evidence/bootstrap-20260912/learner/learner.json
research/learner-evidence/bootstrap-20260912/run/prepared.json
```

## Verification

```text
learner focused regression tests: 9 passed
bundle component verification:    13 / 13 passed
candidate artifact readback:      PASS
model SHA-256 readback:            PASS
learner artifact readback:         PASS
prepared run hash readback:       PASS
candidate/learner binding:        PASS
symbols and row coverage:         PASS
temporary runner/staging root:    removed
```

The final readback confirmed the exact bundle/registry binding and preserved:

```text
learner state:        testing
run status:           prepared
training_metrics:     null
output_artifact_hash: null
data_source:           cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

## Boundary

No candidate registry entry was created. No qualification artifact, learner
quality result, paper activation, scheduler change, provider/LLM call,
authenticated exchange call, testnet order, or live order was performed.

This proves that a real explicit trainer can consume the exact immutable bundle
and produce a hash-verified testing artifact plus prepared provenance. It does
not prove that the baseline predicts usefully or that any strategy/candidate is
qualified. The next materially new learner boundary is cached learner
evaluation and quality review; it must consume these exact hashes and remain
read-only.
