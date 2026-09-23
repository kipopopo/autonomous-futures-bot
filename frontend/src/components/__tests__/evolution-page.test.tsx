import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { EvolutionPage } from '../evolution-page'
import {
  buildAutoEvolutionModel,
  type CanaryAutoEvolutionData,
} from '../../lib/canary'

describe('EvolutionPage component', () => {
  const verifiedFixture: CanaryAutoEvolutionData = {
    phase: 'phase_306',
    verified: true,
    status: 'EVOLUTION_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1790146800000,
    timestamp_utc: '2026-09-23T07:00:00.000000+00:00',
    paper_safe: true,
    execution_authority: false,
    candidates: ['cand-btcusdt-dcb-002', 'cand-ethusdt-dcb-003', 'cand-solusdt-rgb-001'],
    performance: {
      total_autopsies_conducted: 16,
      autopsy_cause_distribution: {
        ORGANIC_ALPHA: 12,
        HAWKES_CLUSTER: 4,
      },
      mean_entry_timing_error_bps: 6.35,
      mean_hawkes_slip_drag_bps: 4.03,
      mean_adverse_selection_bps: 4.06,
      mean_realized_edge_bps: 14.86,
      health_tier_distribution: {
        ELITE: 2,
        HEALTHY: 0,
        DEGRADED: 1,
        PROBATIONARY: 0,
      },
      staged_mutations_count: 1,
      promoted_candidates_count: 1,
      realized_sharpe_ratio: 3.85,
      win_rate_pct: 81.25,
      calmar_ratio: 12.4,
      max_drawdown_pct: 0.85,
    },
    autopsies_trace: [
      {
        trade_id: 'tr-btc-001',
        candidate_id: 'cand-btcusdt-dcb-002',
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry_price: 95000.0,
        exit_price: 95250.0,
        fill_qty: 0.0001,
        entry_timing_error_bps: 1.05,
        hawkes_slip_drag_bps: 2.98,
        adverse_selection_bps: 1.0,
        realized_edge_bps: 20.19,
        gross_pnl_usdt: 0.025,
        fee_cost_usdt: 0.005,
        net_pnl_usdt: 0.02,
        cause: 'ORGANIC_ALPHA',
        timestamp_ms: 1710000000000,
      },
      {
        trade_id: 'tr-eth-001',
        candidate_id: 'cand-ethusdt-dcb-003',
        symbol: 'ETHUSDT',
        side: 'BUY',
        entry_price: 2750.0,
        exit_price: 2745.0,
        fill_qty: 0.0018,
        entry_timing_error_bps: 7.28,
        hawkes_slip_drag_bps: 7.22,
        adverse_selection_bps: 12.0,
        realized_edge_bps: -24.17,
        gross_pnl_usdt: -0.009,
        fee_cost_usdt: 0.003,
        net_pnl_usdt: -0.012,
        cause: 'HAWKES_CLUSTER',
        timestamp_ms: 1710000000000,
      },
    ],
    health_evaluations: {
      'cand-btcusdt-dcb-002': {
        candidate_id: 'cand-btcusdt-dcb-002',
        symbol: 'BTCUSDT',
        tier: 'ELITE',
        rolling_sharpe: 59.09,
        win_rate_pct: 100.0,
        max_drawdown_pct: 0.0,
        hawkes_resilience_score: 90.0,
        total_trades: 6,
        consecutive_losses: 0,
        needs_mutation: false,
      },
      'cand-ethusdt-dcb-003': {
        candidate_id: 'cand-ethusdt-dcb-003',
        symbol: 'ETHUSDT',
        tier: 'DEGRADED',
        rolling_sharpe: -5.0,
        win_rate_pct: 20.0,
        max_drawdown_pct: 0.05,
        hawkes_resilience_score: 0.0,
        total_trades: 5,
        consecutive_losses: 3,
        needs_mutation: true,
      },
    },
    mutations_trace: [
      {
        candidate_id: 'cand-ethusdt-evo-002',
        generation: 2,
        parent_candidate_id: 'cand-ethusdt-dcb-003',
        donchian_period: 24,
        atr_multiplier: 2.5,
        hawkes_intensity_threshold: 0.65,
        micro_horizon_bias: 0.3,
        mutation_rationale: 'Widened ATR stop + tight Hawkes hazard threshold',
      },
    ],
    shadow_evaluations: [
      {
        staged_candidate_id: 'cand-ethusdt-evo-002',
        parent_candidate_id: 'cand-ethusdt-dcb-003',
        symbol: 'ETHUSDT',
        shadow_ticks: 20,
        shadow_sharpe: 2.1,
        parent_sharpe: -5.0,
        improvement_pct: 100.0,
        promoted: true,
        rejection_reason: null,
      },
    ],
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 100.12,
      allocated_margin_usdt: 0.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: 0.12,
      total_equity_usdt: 100.12,
      total_fees_usdt: 0.05,
      total_slippage_usdt: 0.01,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 100.0,
      unencumbered_cash_verified: true,
    },
    upstream_hash: '0cbf6a93a5332789d5053f72e7e494b03b48ccd0ff7c62118bb339d5d905aa7c',
    phase_hash: '521bcb2f8bf0f35c8bb838419ba233bcbe72eeba6652b9710622675907511fd5',
    merkle_root: '818fd82458a8fb19420dd0179c8f78b0c273e5d2a71b1968b083d20f99e23dbe',
  }

  it('renders correctly with verified fixture data', () => {
    const model = buildAutoEvolutionModel(verifiedFixture)
    const html = renderToString(<EvolutionPage model={model} />)

    expect(html).toContain('Continuous Self-Learning Loop')
    expect(html).toContain('PHASE 306')
    expect(html).toContain('PAPER-SAFE:')
    expect(html).toContain('TRUE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('ZERO-DRIFT:')
    expect(html).toContain('VERIFIED')
  })

  it('renders candidate health tiers and indicators', () => {
    const model = buildAutoEvolutionModel(verifiedFixture)
    const html = renderToString(<EvolutionPage model={model} />)

    expect(html).toContain('cand-btcusdt-dcb-002')
    expect(html).toContain('ELITE')
    expect(html).toContain('cand-ethusdt-dcb-003')
    expect(html).toContain('DEGRADED')
    expect(html).toContain('MUTATED &amp; STAGED')
  })

  it('renders trade autopsies and friction decomposition', () => {
    const model = buildAutoEvolutionModel(verifiedFixture)
    const html = renderToString(<EvolutionPage model={model} />)

    expect(html).toContain('tr-btc-001')
    expect(html).toContain('ORGANIC_ALPHA')
    expect(html).toContain('tr-eth-001')
    expect(html).toContain('HAWKES_CLUSTER')
  })

  it('renders genetic mutations and shadow staging evaluation', () => {
    const model = buildAutoEvolutionModel(verifiedFixture)
    const html = renderToString(<EvolutionPage model={model} />)

    expect(html).toContain('cand-ethusdt-evo-002')
    expect(html).toContain('Widened ATR stop + tight Hawkes hazard threshold')
    expect(html).toContain('PROMOTED')
    expect(html).toContain('100%')
  })

  it('handles default empty state gracefully without crashing', () => {
    const model = buildAutoEvolutionModel(null)
    const html = renderToString(<EvolutionPage model={model} />)

    expect(html).toContain('Continuous Self-Learning Loop')
    expect(html).toContain('PHASE 306')
    expect(html).toContain('GEN #2')
    expect(html).toContain('0.00 &lt; 10^-15 USDT')
  })
})
