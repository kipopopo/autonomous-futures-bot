import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { ExecutionGuardPage } from '../execution-guard-page'
import {
  buildExecutionGuardModel,
  type CanaryExecutionGuardData,
} from '../../lib/canary'

describe('ExecutionGuardPage component', () => {
  const verifiedFixture: CanaryExecutionGuardData = {
    phase: 'phase_302',
    verified: true,
    status: 'EXECUTION_GUARD_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1790126252809,
    timestamp_utc: '2026-09-23T01:17:32.809634+00:00',
    paper_safe: true,
    execution_authority: false,
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    toxicity_metrics: [
      {
        symbol: 'BTCUSDT',
        vpin: 1.0,
        kyles_lambda: 0.00001,
        hawkes_spectral_radius: 0.4,
        risk_state: 'TOXIC_RUNAWAY',
        shading_offset_bps: 25.0,
        quotes_pulled: true,
      },
      {
        symbol: 'ETHUSDT',
        vpin: 1.0,
        kyles_lambda: 0.120125,
        hawkes_spectral_radius: 0.9,
        risk_state: 'TOXIC_RUNAWAY',
        shading_offset_bps: 25.0,
        quotes_pulled: true,
      },
    ],
    shaded_quotes: [
      {
        quote_id: 'quote-btc-001',
        symbol: 'BTCUSDT',
        side: 'BUY',
        unshaded_price: 50150.0,
        shaded_price: 50150.0,
        reservation_price: 50149.99,
        shading_bps: 30.0,
        action: 'PULLED_DEFENSE',
        reason: 'Toxic flow runaway defense: VPIN=1.000 >= 0.700',
      },
      {
        quote_id: 'quote-eth-002',
        symbol: 'ETHUSDT',
        side: 'BUY',
        unshaded_price: 2375.0,
        shaded_price: 2375.0,
        reservation_price: 2374.99,
        shading_bps: 36.25,
        action: 'PULLED_DEFENSE',
        reason: 'Toxic flow runaway defense: VPIN=1.000 >= 0.700',
      },
    ],
    slippage_decompositions: [
      {
        order_id: 'child-ord-btc-001',
        symbol: 'BTCUSDT',
        side: 'BUY',
        intended_price: 50150.0,
        fill_price: 50155.0,
        total_slippage_bps: 1.0,
        delay_slippage_bps: 0.2,
        temporary_impact_bps: 0.0,
        permanent_impact_bps: 0.0,
        queue_degradation_bps: 0.8,
        is_maker: true,
        within_tolerance: true,
      },
      {
        order_id: 'child-ord-sol-002',
        symbol: 'SOLUSDT',
        side: 'BUY',
        intended_price: 150.0,
        fill_price: 150.1,
        total_slippage_bps: 6.67,
        delay_slippage_bps: 1.33,
        temporary_impact_bps: 4.74,
        permanent_impact_bps: 4.5,
        queue_degradation_bps: 0.0,
        is_maker: false,
        within_tolerance: true,
      },
    ],
    child_orders: [
      {
        order_id: 'child-ord-btc-001',
        symbol: 'BTCUSDT',
        side: 'BUY',
        intended_price: 50150.0,
        executed_price: 50155.0,
        quantity: 0.0,
        notional_usdt: 0.0,
        fee_usdt: 0.0,
        slippage_usdt: 0.0,
        status: 'FILLED',
      },
      {
        order_id: 'child-ord-sol-002',
        symbol: 'SOLUSDT',
        side: 'BUY',
        intended_price: 150.0,
        executed_price: 150.1,
        quantity: 0.03,
        notional_usdt: 4.5,
        fee_usdt: 0.00225,
        slippage_usdt: 0.003,
        status: 'FILLED',
      },
    ],
    ledger: {
      starting_equity: 100.0,
      cash: 98.52975,
      allocated_margin: 1.5,
      unrealized_pnl: 0.03,
      realized_pnl: 0.035,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 98.52975,
      allocated_margin_usdt: 1.5,
      unrealized_pnl_usdt: 0.03,
      realized_pnl_usdt: 0.035,
      total_equity_usdt: 100.05975,
      total_fees_usdt: 0.00225,
      total_slippage_usdt: 0.003,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.05975,
      cash_reserve_pct: 98.52975,
      unencumbered_cash_verified: true,
    },
    upstream_hash: '64f0c31a6763924339d1737f7ff94923b4eba22f71bb703295a045bb5e16da7a',
    phase_hash: 'a557460434cd43e8d169910f8c3ae7a259288e44be65c56fddda1a1182e09812',
    merkle_root: '5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76',
  }

  it('renders top banner and global safety indicators', () => {
    const model = buildExecutionGuardModel(verifiedFixture)
    const html = renderToString(<ExecutionGuardPage model={model} />)

    expect(html).toContain('Adverse Selection Guard &amp; Microstructure Slippage Attribution')
    expect(html).toContain('PHASE 302')
    expect(html).toContain('EXECUTION_GUARD_VERIFIED')
    expect(html).toContain('CIRCUIT: NORMAL')
    expect(html).toContain('PAPER SAFE: VERIFIED')
    expect(html).toContain('AUTHORITY: OFF')
    expect(html).toContain('ZERO DRIFT: 0.00 USDT')
  })

  it('renders KPI summary cards', () => {
    const model = buildExecutionGuardModel(verifiedFixture)
    const html = renderToString(<ExecutionGuardPage model={model} />)

    expect(html).toContain('Order Flow Toxicity')
    expect(html).toContain('DEFENSE ACTIVE')
    expect(html).toContain('Avellaneda-Stoikov')
    expect(html).toContain('25.0 bps')
    expect(html).toContain('Mean Realized Slippage')
    expect(html).toContain('3.84 bps')
    expect(html).toContain('WITHIN TOLERANCE')
    expect(html).toContain('Unencumbered Cash')
    expect(html).toContain('98.5%')
  })

  it('renders Toxicity & Adverse Selection Guard table with symbols and VPIN', () => {
    const model = buildExecutionGuardModel(verifiedFixture)
    const html = renderToString(<ExecutionGuardPage model={model} />)

    expect(html).toContain('Top-of-Book Toxicity &amp; Adverse Selection Guard')
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('1.0000')
    expect(html).toContain('0.000010')
    expect(html).toContain('0.120125')
    expect(html).toContain('0.400')
    expect(html).toContain('0.900')
    expect(html).toContain('TOXIC_RUNAWAY')
    expect(html).toContain('PULLED_DEFENSE')
  })

  it('renders Causal Slippage Attribution table with 4 orthogonal components', () => {
    const model = buildExecutionGuardModel(verifiedFixture)
    const html = renderToString(<ExecutionGuardPage model={model} />)

    expect(html).toContain('Causal Slippage Attribution Engine (4 Orthogonal Components)')
    expect(html).toContain('child-ord-btc-001')
    expect(html).toContain('child-ord-sol-002')
    expect(html).toContain('$50150.00')
    expect(html).toContain('$50155.00')
    expect(html).toContain('1.00 bps')
    expect(html).toContain('6.67 bps')
    expect(html).toContain('0.20 bps')
    expect(html).toContain('4.74 bps')
    expect(html).toContain('PASSIVE_MAKER')
    expect(html).toContain('TAKER_BRACKET')
    expect(html).toContain('PASS')
  })

  it('renders Shaded Quotes and micro child orders log', () => {
    const model = buildExecutionGuardModel(verifiedFixture)
    const html = renderToString(<ExecutionGuardPage model={model} />)

    expect(html).toContain('Avellaneda-Stoikov Shaded Quotes')
    expect(html).toContain('$50150.00')
    expect(html).toContain('+30.0 bps')
    expect(html).toContain('+36.3 bps')
    expect(html).toContain('Micro Child Orders Slicing (≤ 5.00 USDT)')
    expect(html).toContain('$4.50')
  })

  it('renders Double-Entry Balance Governance and Merkle DAG linkage', () => {
    const model = buildExecutionGuardModel(verifiedFixture)
    const html = renderToString(<ExecutionGuardPage model={model} />)

    expect(html).toContain('Double-Entry Mathematical Balance Governance &amp; Merkle Linkage')
    expect(html).toContain('ZERO DRIFT VERIFIED')
    expect(html).toContain('$98.53 USDT')
    expect(html).toContain('$1.50 USDT')
    expect(html).toContain('+$0.04')
    expect(html).toContain('64f0c31a6763924339d1737f7ff94923b4eba22f71bb703295a045bb5e16da7a')
    expect(html).toContain('5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76')
  })

  it('handles null/default data safely without crashing', () => {
    const defaultModel = buildExecutionGuardModel(null)
    const html = renderToString(<ExecutionGuardPage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Adverse Selection Guard &amp; Microstructure Slippage Attribution')
    expect(html).toContain('PHASE 302')
    expect(html).toContain('EXECUTION_GUARD_VERIFIED')
    expect(html).toContain('ZERO DRIFT: 0.00 USDT')
  })
})
