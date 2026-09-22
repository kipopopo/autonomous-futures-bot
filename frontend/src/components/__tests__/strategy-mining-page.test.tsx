import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { StrategyMiningPage } from '../strategy-mining-page'
import {
  buildStrategyMiningModel,
  type CanaryStrategyMiningResponse,
} from '../../lib/canary'

describe('StrategyMiningPage component', () => {
  const verifiedFixture: CanaryStrategyMiningResponse = {
    verified: true,
    phase: 'phase_298',
    status: 'STRATEGY_MINING_VERIFIED',
    timestamp_ms: 1789538400000,
    timestamp_utc: '2026-09-22T01:30:22.000Z',
    paper_safe: true,
    execution_authority: false,
    circuit_state: 'NORMAL',
    active_candidates: ['cand-btcusdt-dcb-002', 'cand-ethusdt-dcb-003', 'cand-solusdt-rgb-001'],
    candidates: [
      {
        candidate_id: 'cand-btcusdt-dcb-002',
        symbol: 'BTCUSDT',
        family: 'DonchianBreakout',
        lookback: 24,
        zscore_threshold: 1.6,
        stop_atr_multiplier: 2.2,
        return_pct: 4.25,
        drawdown_pct: 6.8,
        profit_factor: 1.45,
        trade_count: 18,
        resilience_passed: true,
        qualified: true,
        status: 'ADMITTED',
      },
      {
        candidate_id: 'cand-ethusdt-dcb-003',
        symbol: 'ETHUSDT',
        family: 'DonchianBreakout',
        lookback: 20,
        zscore_threshold: 1.5,
        stop_atr_multiplier: 2.0,
        return_pct: 3.65,
        drawdown_pct: 7.2,
        profit_factor: 1.38,
        trade_count: 15,
        resilience_passed: true,
        qualified: true,
        status: 'ADMITTED',
      },
      {
        candidate_id: 'cand-solusdt-rgb-001',
        symbol: 'SOLUSDT',
        family: 'RegimeVolatilityBreakout',
        lookback: 16,
        zscore_threshold: 1.7,
        stop_atr_multiplier: 2.4,
        return_pct: 5.12,
        drawdown_pct: 8.4,
        profit_factor: 1.52,
        trade_count: 22,
        resilience_passed: true,
        qualified: true,
        status: 'ADMITTED',
      },
    ],
    mutations: [
      {
        mutation_id: 'mut-dcb-001',
        generation: 1,
        parent_candidate_id: 'cand-btcusdt-dcb-001',
        mutated_candidate_id: 'cand-btcusdt-dcb-002',
        family: 'DonchianBreakout',
        parameter_diffs: { lookback: [20, 24], zscore_threshold: [1.5, 1.6] },
        seed: 42,
        timestamp_utc: '2026-09-22T01:30:22.000Z',
      },
    ],
    gate_metrics: {
      gate_names: [
        'Walk-Forward OOS Average Return (>= 0.0%)',
        'Walk-Forward OOS Worst Drawdown (<= 15.0%)',
        'Walk-Forward OOS Profit Factor (>= 1.05)',
        'Minimum OOS Trade Count (>= 5 trades)',
        'Microstructure Resilience Gate (Flash Crash -20% & Spread 10%)',
      ],
      thresholds: {
        min_return_pct: 0.0,
        max_drawdown_pct: 15.0,
        min_profit_factor: 1.05,
        min_trade_count: 5,
        resilience_required: true,
      },
      passing_counts: {
        return_gate: 3,
        drawdown_gate: 3,
        profit_factor_gate: 3,
        trade_count_gate: 3,
        resilience_gate: 3,
      },
      rejection_counts: {},
      total_evaluated: 3,
      total_passed: 3,
      total_rejected: 0,
    },
    hot_reload: {
      reloaded_at_utc: '2026-09-22T01:30:22.000Z',
      previous_version: 2,
      new_version: 3,
      registry_hash: '9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b',
      reload_status: 'ADMITTED_AND_HOT_RELOADED',
      process_restarted: false,
      open_trades_mutated: false,
    },
    hypotheses: [
      {
        hypothesis_id: 'hyp-dcb-001',
        parent_id: null,
        family: 'DonchianBreakout',
        symbol: 'BTCUSDT',
        generation: 1,
        mutation_type: 'LOOKBACK_SHIFT',
        parameters: { lookback: 24, zscore_threshold: 1.6 },
        status: 'QUALIFIED',
        timestamp_utc: '2026-09-22T01:30:22.000Z',
      },
      {
        hypothesis_id: 'hyp-rgb-001',
        parent_id: null,
        family: 'RegimeVolatilityBreakout',
        symbol: 'ETHUSDT',
        generation: 1,
        mutation_type: 'VOLATILITY_THRESHOLD',
        parameters: { lookback: 20, zscore_threshold: 1.5 },
        status: 'QUALIFIED',
        timestamp_utc: '2026-09-22T01:30:22.000Z',
      },
      {
        hypothesis_id: 'hyp-msm-001',
        parent_id: null,
        family: 'MicrostructureMomentum',
        symbol: 'SOLUSDT',
        generation: 1,
        mutation_type: 'OFI_SENSITIVITY',
        parameters: { lookback: 16, zscore_threshold: 1.8 },
        status: 'QUALIFIED',
        timestamp_utc: '2026-09-22T01:30:22.000Z',
      },
    ],
    search_space: [
      {
        param_name: 'lookback_window',
        family: 'DonchianBreakout',
        min_value: 10,
        max_value: 60,
        current_value: 20,
        optimal_value: 24,
        unit: 'bars',
      },
      {
        param_name: 'entry_zscore',
        family: 'RegimeVolatilityBreakout',
        min_value: 1.0,
        max_value: 3.0,
        current_value: 1.5,
        optimal_value: 1.65,
        unit: 'σ',
      },
      {
        param_name: 'ofi_threshold',
        family: 'MicrostructureMomentum',
        min_value: 0.1,
        max_value: 0.9,
        current_value: 0.4,
        optimal_value: 0.55,
        unit: 'ratio',
      },
    ],
    feature_heatmaps: [
      {
        feature_name: 'hawkes_jump_intensity_lambda',
        symbol: 'BTCUSDT',
        correlation_score: 0.78,
        importance_weight: 0.85,
        mutation_sensitivity: 0.62,
      },
      {
        feature_name: 'spectral_radius_rho',
        symbol: 'BTCUSDT',
        correlation_score: 0.82,
        importance_weight: 0.91,
        mutation_sensitivity: 0.74,
      },
      {
        feature_name: 'order_flow_imbalance_ofi',
        symbol: 'ETHUSDT',
        correlation_score: 0.69,
        importance_weight: 0.78,
        mutation_sensitivity: 0.58,
      },
      {
        feature_name: 'rolling_volatility_sigma',
        symbol: 'SOLUSDT',
        correlation_score: 0.74,
        importance_weight: 0.82,
        mutation_sensitivity: 0.65,
      },
    ],
    oos_scorecards: [
      {
        candidate_id: 'cand-btcusdt-dcb-002',
        symbol: 'BTCUSDT',
        family: 'DonchianBreakout',
        return_pct: 4.25,
        worst_drawdown_pct: 6.8,
        profit_factor: 1.45,
        trade_count: 18,
        stress_survived: true,
        gates_passed_count: 5,
        all_gates_passed: true,
        qualified: true,
        admission_status: 'ADMITTED',
      },
      {
        candidate_id: 'cand-ethusdt-dcb-003',
        symbol: 'ETHUSDT',
        family: 'DonchianBreakout',
        return_pct: 3.65,
        worst_drawdown_pct: 7.2,
        profit_factor: 1.38,
        trade_count: 15,
        stress_survived: true,
        gates_passed_count: 5,
        all_gates_passed: true,
        qualified: true,
        admission_status: 'ADMITTED',
      },
      {
        candidate_id: 'cand-solusdt-rgb-001',
        symbol: 'SOLUSDT',
        family: 'RegimeVolatilityBreakout',
        return_pct: 5.12,
        worst_drawdown_pct: 8.4,
        profit_factor: 1.52,
        trade_count: 22,
        stress_survived: true,
        gates_passed_count: 5,
        all_gates_passed: true,
        qualified: true,
        admission_status: 'ADMITTED',
      },
    ],
    hot_reload_logs: [
      {
        event_id: 'event-hr-298-001',
        candidate_id: 'cand-btcusdt-dcb-002',
        symbol: 'BTCUSDT',
        manifest_version: 3,
        registry_hash: '9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b',
        reloaded_at_utc: '2026-09-22T01:30:22.000Z',
        status: 'ADMITTED_AND_HOT_RELOADED',
        process_restarted: false,
        open_trades_mutated: false,
      },
      {
        event_id: 'event-hr-298-002',
        candidate_id: 'cand-ethusdt-dcb-003',
        symbol: 'ETHUSDT',
        manifest_version: 3,
        registry_hash: '9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b',
        reloaded_at_utc: '2026-09-22T01:30:22.000Z',
        status: 'ADMITTED_AND_HOT_RELOADED',
        process_restarted: false,
        open_trades_mutated: false,
      },
    ],
    ledger: {
      starting_equity: 100.0,
      cash: 100.0,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 100.0,
      allocated_margin_usdt: 0.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: 0.0,
      total_equity_usdt: 100.0,
      total_fees_usdt: 0.0,
      total_slippage_usdt: 0.0,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 100.0,
      unencumbered_cash_verified: true,
    },
    upstream_hash: '257f83f794465f3b89bfd9dbc25a2bf949d9fe315ecd97e2108c027ca3475668',
    phase_hash: 'e8f7a6b5c4d3e2f1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7',
    merkle_root: '7f8e9d0c1b2a3f4e5d6c7b8a9f0e1d2c3b4a5f6e7d8c9b0a1f2e3d4c5b6a7f8e',
  }

  it('renders all safety and confinement badges', () => {
    const model = buildStrategyMiningModel(verifiedFixture)
    const html = renderToString(<StrategyMiningPage model={model} />)

    expect(html).toContain('STRATEGY MINING VERIFIED')
    expect(html).toContain('PAPER-SAFE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('OOS 5-GATE PROMOTION')
    expect(html).toContain('ZERO-DRIFT VERIFIED')
  })

  it('renders Strategy Hypothesis Tree & Mutation Lineage with generations and families', () => {
    const model = buildStrategyMiningModel(verifiedFixture)
    const html = renderToString(<StrategyMiningPage model={model} />)

    expect(html).toContain('Strategy Hypothesis Tree &amp; Mutation Lineage')
    expect(html).toContain('hyp-dcb-001')
    expect(html).toContain('DonchianBreakout')
    expect(html).toContain('hyp-rgb-001')
    expect(html).toContain('RegimeVolatilityBreakout')
    expect(html).toContain('hyp-msm-001')
    expect(html).toContain('MicrostructureMomentum')
    expect(html).toContain('LOOKBACK_SHIFT')
    expect(html).toContain('VOLATILITY_THRESHOLD')
    expect(html).toContain('OFI_SENSITIVITY')
  })

  it('renders Live Parameter Search Space & Feature Heatmaps', () => {
    const model = buildStrategyMiningModel(verifiedFixture)
    const html = renderToString(<StrategyMiningPage model={model} />)

    expect(html).toContain('Parameter Search Space Boundaries')
    expect(html).toContain('lookback_window')
    expect(html).toContain('entry_zscore')
    expect(html).toContain('ofi_threshold')

    expect(html).toContain('Causal Feature Sensitivity &amp; Heatmaps')
    expect(html).toContain('hawkes_jump_intensity_lambda')
    expect(html).toContain('spectral_radius_rho')
    expect(html).toContain('order_flow_imbalance_ofi')
    expect(html).toContain('rolling_volatility_sigma')
  })

  it('renders OOS Gate Scorecards & Auto-Admission Status with 5 qualification gates', () => {
    const model = buildStrategyMiningModel(verifiedFixture)
    const html = renderToString(<StrategyMiningPage model={model} />)

    expect(html).toContain('Out-of-Sample (OOS) Gate Scorecards &amp; Auto-Admission Status')
    expect(html).toContain('OOS Average Return')
    expect(html).toContain('OOS Worst Drawdown')
    expect(html).toContain('OOS Profit Factor')
    expect(html).toContain('Min OOS Trade Count')
    expect(html).toContain('Microstructure Resilience')

    expect(html).toContain('cand-btcusdt-dcb-002')
    expect(html).toContain('+4.25%')
    expect(html).toContain('6.80%')
    expect(html).toContain('1.45')
    expect(html).toContain('cand-ethusdt-dcb-003')
    expect(html).toContain('cand-solusdt-rgb-001')
    expect(html).toContain('Survived')
    expect(html).toContain('ADMITTED')
  })

  it('renders Zero-Downtime Hot-Reload Activity Log with manifest versioning and immutability', () => {
    const model = buildStrategyMiningModel(verifiedFixture)
    const html = renderToString(<StrategyMiningPage model={model} />)

    expect(html).toContain('Zero-Downtime Candidate Hot-Reload Activity Log')
    expect(html).toContain('Manifest 2 → 3')
    expect(html).toContain('ADMITTED_AND_HOT_RELOADED')
    expect(html).toContain('0 Restarts')
    expect(html).toContain('Preserved')
    expect(html).toContain('event-hr-298-001')
    expect(html).toContain('event-hr-298-002')
    expect(html).toContain('IMMUTABLE')
  })

  it('renders continuous mathematical double-entry solvency meter and conservation law', () => {
    const model = buildStrategyMiningModel(verifiedFixture)
    const html = renderToString(<StrategyMiningPage model={model} />)

    expect(html).toContain('Double-Entry Solvency Meter (|drift| &lt; 10⁻¹⁵ USDT)')
    expect(html).toContain('100.00 USDT')
    expect(html).toContain('RESERVE BUFFER VERIFIED')
    expect(html).toContain('|drift| &lt; 10⁻¹⁵ USDT')
    expect(html).toContain('Drift = 0.000000000000000 USDT')
    expect(html).toContain('Conservation Law: Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL')
  })

  it('renders cryptographic SHA-256 Merkle DAG provenance linking upstream Phase 297', () => {
    const model = buildStrategyMiningModel(verifiedFixture)
    const html = renderToString(<StrategyMiningPage model={model} />)

    expect(html).toContain('Cryptographic SHA-256 Merkle DAG Provenance')
    expect(html).toContain('Upstream Phase 297 Parent Hash:')
    expect(html).toContain('257f83f794465f3b89bfd9dbc25a2bf949d9fe315ecd97e2108c027ca3475668')
    expect(html).toContain('Phase 298 Merkle Root:')
    expect(html).toContain('7f8e9d0c1b2a3f4e5d6c7b8a9f0e1d2c3b4a5f6e7d8c9b0a1f2e3d4c5b6a7f8e')
    expect(html).toContain('MERKLE ROOT VERIFIED')
  })

  it('handles default/null model safely without throwing', () => {
    const defaultModel = buildStrategyMiningModel(null)
    const html = renderToString(<StrategyMiningPage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Phase 298 / Strategy Auto-Evolution &amp; Mining Plane')
    expect(html).toContain('Strategy Hypothesis Tree &amp; Mutation Lineage')
    expect(html).toContain('Live Parameter Search Space &amp; Feature Sensitivity Heatmaps')
    expect(html).toContain('Out-of-Sample (OOS) Gate Scorecards &amp; Auto-Admission Status')
    expect(html).toContain('Zero-Downtime Candidate Hot-Reload Activity Log')
    expect(html).toContain('Double-Entry Solvency Meter (|drift| &lt; 10⁻¹⁵ USDT)')
  })
})
