import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { StrategyActivationPage } from '../strategy-activation-page'
import {
  buildStrategyActivationModel,
  type CanaryStrategyActivationResponse,
} from '../../lib/canary'

describe('StrategyActivationPage component', () => {
  const verifiedFixture: CanaryStrategyActivationResponse = {
    verified: true,
    phase: 'phase_295',
    status: 'STREAMING',
    timestamp_ms: 1789447964946,
    paper_safe: true,
    execution_authority: false,
    candidates: [
      {
        candidate_id: 'cand-btcusdt-dcb-002',
        symbol: 'BTCUSDT',
        status: 'PROMOTED',
        average_return_pct: 0.045,
        worst_drawdown_pct: 0.021,
        profit_factor: 1.85,
        trade_count: 42,
        window_count: 5,
        qualified: true,
      },
      {
        candidate_id: 'cand-ethusdt-dcb-003',
        symbol: 'ETHUSDT',
        status: 'PROMOTED',
        average_return_pct: 0.038,
        worst_drawdown_pct: 0.019,
        profit_factor: 1.72,
        trade_count: 36,
        window_count: 5,
        qualified: true,
      },
      {
        candidate_id: 'cand-solusdt-rgb-001',
        symbol: 'SOLUSDT',
        status: 'PROMOTED',
        average_return_pct: 0.052,
        worst_drawdown_pct: 0.028,
        profit_factor: 1.91,
        trade_count: 51,
        window_count: 5,
        qualified: true,
      },
    ],
    signals: [
      {
        signal_id: 'sig-btcusdt-001',
        candidate_id: 'cand-btcusdt-dcb-002',
        timestamp_ms: 1789447964900,
        symbol: 'BTCUSDT',
        side: 'BUY',
        order_type: 'LIMIT',
        limit_price: '65200.00',
        notional_usdt: 4.50,
        client_order_id: 'ord-b-01',
      },
      {
        signal_id: 'sig-ethusdt-001',
        candidate_id: 'cand-ethusdt-dcb-003',
        timestamp_ms: 1789447964910,
        symbol: 'ETHUSDT',
        side: 'BUY',
        order_type: 'LIMIT',
        limit_price: '2650.00',
        notional_usdt: 4.80,
        client_order_id: 'ord-e-01',
      },
    ],
    vetoes: {
      hawkes_supercritical: false,
      gateway_heartbeat_stale: false,
      margin_headroom_breach: false,
      clock_skew_breach: false,
      intra_phase_loss_lockout: false,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 95.5,
      allocated_margin: 4.5,
      unrealized_pnl: 0.05,
      realized_pnl: 0.02,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '3f04f21a64c4c23db2be92c10b47fe7343e2646271c66299b9cf9c63fb93cb89',
    phase_hash: '2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae',
    child_orders_count: 12,
    fills_count: 11,
    circuit_state: 'NORMAL',
  }

  it('renders all safety and verification badges', () => {
    const model = buildStrategyActivationModel(verifiedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    expect(html).toContain('STRATEGY ACTIVATION VERIFIED')
    expect(html).toContain('PAPER-SAFE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('ROUND_DOWN ≤ 5.00 USDT')
  })

  it('renders candidate scorecard grid with all promoted candidates', () => {
    const model = buildStrategyActivationModel(verifiedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    // Check candidate IDs
    expect(html).toContain('cand-btcusdt-dcb-002')
    expect(html).toContain('cand-ethusdt-dcb-003')
    expect(html).toContain('cand-solusdt-rgb-001')

    // Check symbols
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('SOLUSDT')

    // Check promotion badge
    expect(html).toContain('PROMOTED')

    // Check metrics are rendered
    expect(html).toContain('0.045')
    expect(html).toContain('0.038')
    expect(html).toContain('0.052')
    expect(html).toContain('1.8500')
    expect(html).toContain('1.7200')
    expect(html).toContain('1.9100')
    expect(html).toContain('PASSED ALL GATES')
  })

  it('renders fail-closed veto interlock cards in clear status', () => {
    const model = buildStrategyActivationModel(verifiedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    expect(html).toContain('Hawkes Supercritical')
    expect(html).toContain('Gateway Heartbeat')
    expect(html).toContain('Margin Headroom')
    expect(html).toContain('Loss Budget Ceiling')
    expect(html).toContain('NORMAL')
  })

  it('renders veto interlocks in tripped state when veto is active', () => {
    const trippedFixture: CanaryStrategyActivationResponse = {
      ...verifiedFixture,
      circuit_state: 'TRIPPED',
      vetoes: {
        hawkes_supercritical: true,
        gateway_heartbeat_stale: true,
        margin_headroom_breach: true,
        intra_phase_loss_lockout: true,
      },
    }
    const model = buildStrategyActivationModel(trippedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    expect(html).toContain('VETO ACTIVE')
    expect(html).toContain('STALE HEARTBEAT')
    expect(html).toContain('HEADROOM BREACH')
    expect(html).toContain('TRIPPED')
  })

  it('renders mathematical double-entry zero-drift balance gauge', () => {
    const model = buildStrategyActivationModel(verifiedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    expect(html).toContain('Double-Entry Zero-Drift Balance Ledger')
    expect(html).toContain('Starting Equity')
    expect(html).toContain('100.00')
    expect(html).toContain('Final Cash')
    expect(html).toContain('95.50')
    expect(html).toContain('Allocated Margin')
    expect(html).toContain('4.50')
    expect(html).toContain('Mathematical Drift')
    expect(html).toContain('Zero Drift Verified')
    expect(html).toContain('10⁻¹⁵ USDT')
  })

  it('renders child order slicing summary and micro-notional discipline', () => {
    const model = buildStrategyActivationModel(verifiedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    expect(html).toContain('Micro Child Slicing &amp; Provenance')
    expect(html).toContain('Generated Slices')
    expect(html).toContain('12')
    expect(html).toContain('Passive Fills')
    expect(html).toContain('11')
    expect(html).toContain('ROUND_DOWN')
    expect(html).toContain('5.00 USDT')
  })

  it('renders cryptographic Merkle DAG provenance linking Phase 294', () => {
    const model = buildStrategyActivationModel(verifiedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    expect(html).toContain('Cryptographic SHA-256 Merkle DAG Chain')
    expect(html).toContain('Phase 295 Root')
    expect(html).toContain('Upstream Phase 294')
    expect(html).toContain('DAG Verified')
  })

  it('renders candidate signals timeline table', () => {
    const model = buildStrategyActivationModel(verifiedFixture)
    const html = renderToString(<StrategyActivationPage model={model} />)

    expect(html).toContain('Promoted Strategy Signals &amp; Parent Orders Timeline')
    expect(html).toContain('sig-btcusdt-001')
    expect(html).toContain('sig-ethusdt-001')
    expect(html).toContain('65200.00')
    expect(html).toContain('2650.00')
  })

  it('handles default/null model safely without throwing', () => {
    const defaultModel = buildStrategyActivationModel(null)
    const html = renderToString(<StrategyActivationPage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Phase 295 / Strategy Activation Plane')
    expect(html).toContain('cand-btcusdt-dcb-002')
    expect(html).toContain('cand-ethusdt-dcb-003')
    expect(html).toContain('cand-solusdt-rgb-001')
    expect(html).toContain('No active parent signals in current view.')
  })
})
