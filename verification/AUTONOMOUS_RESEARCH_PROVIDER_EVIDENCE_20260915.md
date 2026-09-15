# Autonomous Research Provider Evidence — 2026-09-15

**Date**: 2026-09-15T05:01:00Z  
**Model**: `gemma-4-31b-it` (Google AI Studio)  
**Provider Transport**: Direct OpenAI-compatible JSON endpoint  
**Policy**: `policy-research-gemma-001` (v1)  
**Policy Hash**: `d5b2e69805fdcbb47d90b1a3d6dee284141490440b0601afc4aecac63fb96348`  
**Execution Entrypoint**: `scripts/run_autonomy_provider.py`  
**Durable Evidence Root**: `data/research/durable-evidence`  

---

## 1. Summary of Authorized Provider Executions

Under explicit user authorization of the provider budget (Gemma 4 31B limits: 30 RPM, 16K TPM, 14.4K RPD with account buffer), exactly two authorized model calls were executed using the supported CLI orchestration runner:

1. **Failure Learner (`failure_analyst`)**:
   - **Research Run ID**: `run-provider-learner-live-001`
   - **Input**: Verified VWAP reclaim reversal failure memory (`249bdef5d8f5e5e619cc5386b23612044ef39f9ccb3446eb5bc03ddf872da81a`)
   - **Outcome**: `accepted` / `schema_valid`
   - **Learning ID**: `learn-deb5b2325a25cd9efcdbddd6eb58aee76c70dcb796e7d2b79dcd7a0fe9a867c1`
   - **Audit Envelope Hash**: `4ea5d07e830023b5bf2df499de022fd076135ff742ab41bc372bad58a1bd775b`
   - **Readback Verified**: `True`
   - **Requests Consumed**: `1`
   - **Learned Patterns**: `["oos_average_return_below_threshold", "oos_profit_factor_below_threshold"]`
   - **Learned Constraints**: `["preserve_all_qualification_gates"]`
   - **Novelty Dimensions**: `["entry_logic", "feature_set", "regime_filter"]`

2. **Research Planner (`hypothesis_generator`)**:
   - **Initial Attempt**: Failed strict schema due to unconstrained prompt output (`strategy_family:literal_error`, `falsification_criteria:tuple_type`, `novelty_dimensions:value_error`). Audit envelope persisted honestly (`a122a49a37f9419a2b753cabf5ee7c32a2f17193b1f5e3e8106ce2ece539b9ac`).
   - **Remediation**: `autonomy_prompts.py` updated to explicitly enumerate allowed `strategy_family` literals and enforce sorted canonical list syntax.
   - **Revalidation (`run-provider-planner-live-002`)**:
     - **Input**: Complete failure memory + durable learning artifact `learn-deb5b2325a25cd9efcdbddd6eb58aee76c70dcb796e7d2b79dcd7a0fe9a867c1`
     - **Outcome**: `accepted` / `plan_valid`
     - **Plan ID**: `plan-a54d0e5d83e6b1a5dd6996455fd880f5806670352e66755994e8c5970825fb37`
     - **Thesis Hash**: `bd2ada48822164d11724cb5f9d285044e6c2544c3ad99dd9b686b196e47de55a`
     - **Audit Envelope Hash**: `6dd4542733e92246aa9fac7692f396510b9a4c672b25e70b9c5021a20d78cba4`
     - **Readback Verified**: `True`
     - **Requests Consumed**: `1`
     - **Generated Hypothesis**: *"Applying a volatility compression filter to Donchian Channel breakouts will reduce false signals during low-volatility regimes, improving the OOS profit factor compared to naive breakouts."*
     - **Strategy Family**: `volatility_compression_breakout`
     - **Expected Regime**: `volatile_trend`
     - **Novelty Dimensions**: `["entry_logic", "feature_set", "regime_filter"]`
     - **Falsification Criteria**: `["reject if OOS average return < 0", "reject if OOS profit factor < 1.2", "reject if Sharpe ratio < 1.0"]`
     - **Forbidden Candidate IDs**: `["cand-vwap-reclaim-reversal-20260913"]`

---

## 2. Idempotency & Checkpoint Reuse Verification

Both endpoints were re-executed against their respective completed `research_run_id`s:
- `run-provider-learner-live-001`: Returned `status: reused_checkpoint`, `requests_consumed: 0`, `reused_existing: true`.
- `run-provider-planner-live-002`: Returned `status: reused_checkpoint`, `requests_consumed: 0`, `reused_existing: true`.
Zero redundant network calls or duplicate requests were made.

---

## 3. Safety & Invariant Compliance

- **Zero Secret Exposure**: All API keys resolved via environment/repo-only without logging or displaying secret values.
- **Zero Raw Provider Retention**: Raw HTTP payloads were not persisted; only typed Pydantic artifacts and sanitized hash envelopes were written.
- **Durable Storage**: All accepted artifacts (`learning/*.json`, `plans/*.json`, `audits/*.json`) are stored durably under `data/research/durable-evidence` and verified on readback.
- **No Promotion / Live / Execution Bypass**: Pure research plan generation only. No candidate was admitted to paper or live trading.
