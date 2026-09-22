import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { PortfolioRebalancingPage } from '../portfolio-rebalancing-page'
import {
  buildPortfolioRebalancingModel,
  type CanaryPortfolioRebalancingResponse,
} from '../../lib/canary'

describe('PortfolioRebalancingPage component', () => {
  const verifiedFixture: CanaryPortfolioRebalancingResponse = {
    verified: true,
    phase: 'phase_299',
    status: 'PORTFOLIO_REBALANCING_VERIFIED',
    timestamp_ms: 1789542000000,
    timestamp_utc: '2026-09-22T02:30:00.000Z',
    paper_safe: true,
    execution_authority: false,
    circuit_state: 'NORMAL',
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    allocations: [
      {
        symbol: 'BTCUSDT',
        target_weight: 0.4,
        actual_weight: 0.4,
        target_notional_usdt: 24.0,
        actual_notional_usdt: 24.0,
        allocated_margin_usdt: 12.0,
        volatility_sigma: 0.025,
        jump_intensity_lambda: 0.22,
        drift_pct: 0.0,
        rebalance_required: false,
        margin_ceiling_usdt: 25.0,
        ceiling_breached: false,
      },
      {
        symbol: 'ETHUSDT',
        target_weight: 0.35,
        actual_weight: 0.35,
        target_notional_usdt: 21.0,
        actual_notional_usdt: 21.0,
        allocated_margin_usdt: 10.5,
        volatility_sigma: 0.032,
        jump_intensity_lambda: 0.31,
        drift_pct: 0.0,
        rebalance_required: false,
        margin_ceiling_usdt: 25.0,
        ceiling_breached: false,
      },
      {
        symbol: 'SOLUSDT',
        target_weight: 0.25,
        actual_weight: 0.25,
        target_notional_usdt: 15.0,
        actual_notional_usdt: 15.0,
        allocated_margin_usdt: 7.5,
        volatility_sigma: 0.045,
        jump_intensity_lambda: 0.48,
        drift_pct: 0.0,
        rebalance_required: false,
        margin_ceiling_usdt: 25.0,
        ceiling_breached: false,
      },
    ],
    spillover_matrix: [
      {
        affected_symbol: 'ETHUSDT',
        trigger_symbol: 'BTCUSDT',
        cross_excitation_alpha: 0.22,
        decay_beta: 0.85,
        branching_ratio_gamma: 0.258,
        spillover_hazard: false,
        deallocation_triggered: false,
        freeze_dispatched: false,
      },
      {
        affected_symbol: 'BTCUSDT',
        trigger_symbol: 'ETHUSDT',
        cross_excitation_alpha: 0.15,
        decay_beta: 0.9,
        branching_ratio_gamma: 0.167,
        spillover_hazard: false,
        deallocation_triggered: false,
        freeze_dispatched: false,
      },
      {
        affected_symbol: 'SOLUSDT',
        trigger_symbol: 'BTCUSDT',
        cross_excitation_alpha: 0.28,
        decay_beta: 0.8,
        branching_ratio_gamma: 0.35,
        spillover_hazard: false,
        deallocation_triggered: false,
        freeze_dispatched: false,
      },
    ],
    contagion_guard: {
      guard_active: true,
      max_spectral_radius_rho: 0.428571,
      hazard_threshold_rho: 0.85,
      hazard_detected: false,
      source_hazard_assets: [],
      throttled_recipient_assets: [],
      capital_deallocated_usdt: 0.0,
      order_dispatch_frozen: false,
      action_taken: 'MONITORING_NOMINAL',
    },
    optimization_metrics: {
      aggregate_exposure_usdt: 60.0,
      aggregate_exposure_cap_usdt: 60.0,
      cash_reserve_usdt: 40.0,
      cash_reserve_pct: 40.0,
      cash_reserve_floor_pct: 40.0,
      max_asset_margin_usdt: 12.0,
      margin_ceiling_per_asset_usdt: 25.0,
      spectral_radius_rho: 0.428571,
      portfolio_volatility: 0.0215,
      risk_parity_herfindahl_index: 0.338,
      sharpe_ratio: 1.85,
      optimization_status: 'OPTIMAL',
    },
    rebalancing_audits: [
      {
        rebalance_id: 'reb-299-001',
        timestamp_utc: '2026-09-22T02:30:00.000Z',
        symbol: 'BTCUSDT',
        side: 'BUY',
        target_drift_pct: 2.65,
        order_chunk_notional_usdt: 4.85,
        order_chunk_qty: 0.00007,
        passive_price: 68500.0,
        execution_status: 'FILLED',
        fee_drag_usdt: 0.0009,
        slippage_absorbed_usdt: 0.0,
        exchange_filters_compliant: true,
      },
      {
        rebalance_id: 'reb-299-002',
        timestamp_utc: '2026-09-22T02:30:00.000Z',
        symbol: 'SOLUSDT',
        side: 'SELL',
        target_drift_pct: -2.75,
        order_chunk_notional_usdt: 4.9,
        order_chunk_qty: 0.032,
        passive_price: 152.5,
        execution_status: 'FILLED',
        fee_drag_usdt: 0.0009,
        slippage_absorbed_usdt: 0.0,
        exchange_filters_compliant: true,
      },
    ],
    ledger: {
      starting_equity: 100.0,
      cash: 70.0,
      allocated_margin: 30.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 70.0,
      allocated_margin_usdt: 30.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: 0.0,
      total_equity_usdt: 100.0,
      total_fees_usdt: 0.0,
      total_slippage_usdt: 0.0,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 70.0,
      unencumbered_cash_verified: true,
    },
    upstream_hash: 'b2ea1dc7053aec1ecd6dd9845d776380093b925e056b891b64c8a454a62bf837',
    phase_hash: 'f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5',
    merkle_root: 'c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9',
  }

  it('renders all safety and confinement badges', () => {
    const model = buildPortfolioRebalancingModel(verifiedFixture)
    const html = renderToString(<PortfolioRebalancingPage model={model} />)

    expect(html).toContain('PORTFOLIO REBALANCING VERIFIED')
    expect(html).toContain('PAPER-SAFE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('HAWKES RISK-PARITY')
    expect(html).toContain('ZERO-DRIFT VERIFIED')
    expect(html).toContain('SPILLOVER GUARD: ACTIVE')
  })

  it('renders Dynamic Asset Allocation & Drift Detection section with asset cards and allocations', () => {
    const model = buildPortfolioRebalancingModel(verifiedFixture)
    const html = renderToString(<PortfolioRebalancingPage model={model} />)

    expect(html).toContain('Dynamic Asset Allocation &amp; Drift Detection')
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('Target: <strong>40.0%</strong>')
    expect(html).toContain('Actual: <strong>40.0%</strong>')
    expect(html).toContain('Drift: <strong>0.0%</strong>')
    expect(html).toContain('WITHIN HYSTERESIS')
  })

  it('renders Cross-Asset Hawkes Spillover & Contagion Matrix', () => {
    const model = buildPortfolioRebalancingModel(verifiedFixture)
    const html = renderToString(<PortfolioRebalancingPage model={model} />)

    expect(html).toContain('Cross-Asset Hawkes Spillover &amp; Contagion Matrix')
    expect(html).toContain('Empirical Cross-Excitation Matrix')
    expect(html).toContain('Contagion Guard Status')
    expect(html).toContain('0.4286')
    expect(html).toContain('MONITORING_NOMINAL')
  })

  it('renders Portfolio Risk-Parity & Sharpe Optimization Metrics', () => {
    const model = buildPortfolioRebalancingModel(verifiedFixture)
    const html = renderToString(<PortfolioRebalancingPage model={model} />)

    expect(html).toContain('Portfolio Risk-Parity &amp; Sharpe Optimization Metrics')
    expect(html).toContain('Aggregate Exposure')
    expect(html).toContain('60.00 USDT')
    expect(html).toContain('Unencumbered Cash Reserve')
    expect(html).toContain('40.0%')
    expect(html).toContain('Status: OPTIMAL')
    expect(html).toContain('1.85')
  })

  it('renders Micro-Rebalancing Execution Audit Log', () => {
    const model = buildPortfolioRebalancingModel(verifiedFixture)
    const html = renderToString(<PortfolioRebalancingPage model={model} />)

    expect(html).toContain('Micro-Rebalancing Execution Audit Log')
    expect(html).toContain('reb-299-001')
    expect(html).toContain('reb-299-002')
    expect(html).toContain('4.85 USDT')
    expect(html).toContain('4.90 USDT')
    expect(html).toContain('COMPLIANT')
    expect(html).toContain('FILLED')
  })

  it('renders continuous mathematical double-entry solvency meter with strict tolerance', () => {
    const model = buildPortfolioRebalancingModel(verifiedFixture)
    const html = renderToString(<PortfolioRebalancingPage model={model} />)

    expect(html).toContain('Double-Entry Solvency Meter (|drift| &lt; 10⁻¹⁵ USDT)')
    expect(html).toContain('100.00 USDT')
    expect(html).toContain('Drift = 0.000000000000000 USDT')
    expect(html).toContain('ZERO-DRIFT VERIFIED')
    expect(html).toContain('Conservation Law: Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL')
  })

  it('renders cryptographic SHA-256 Merkle DAG provenance linking upstream Phase 298', () => {
    const model = buildPortfolioRebalancingModel(verifiedFixture)
    const html = renderToString(<PortfolioRebalancingPage model={model} />)

    expect(html).toContain('Cryptographic SHA-256 Merkle DAG Provenance')
    expect(html).toContain('Upstream Phase 298 Parent Hash:')
    expect(html).toContain('b2ea1dc7053aec1ecd6dd9845d776380093b925e056b891b64c8a454a62bf837')
    expect(html).toContain('Phase 299 Merkle Root:')
    expect(html).toContain('c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9')
    expect(html).toContain('MERKLE ROOT VERIFIED')
  })

  it('handles default/null model safely without throwing', () => {
    const defaultModel = buildPortfolioRebalancingModel(null)
    const html = renderToString(<PortfolioRebalancingPage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Phase 299 / Portfolio Risk Orchestration Plane')
    expect(html).toContain('Dynamic Asset Allocation &amp; Drift Detection')
    expect(html).toContain('Cross-Asset Hawkes Spillover &amp; Contagion Matrix')
    expect(html).toContain('Portfolio Risk-Parity &amp; Sharpe Optimization Metrics')
    expect(html).toContain('Micro-Rebalancing Execution Audit Log')
    expect(html).toContain('Double-Entry Solvency Meter (|drift| &lt; 10⁻¹⁵ USDT)')
  })
})
