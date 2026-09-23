import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { ProductionLaunchPage } from '../production-launch-page'
import {
  buildProductionLaunchModel,
  type CanaryProductionLaunchData,
} from '../../lib/canary'

describe('ProductionLaunchPage component', () => {
  const verifiedFixture: CanaryProductionLaunchData = {
    phase: 'phase_309',
    verified: true,
    status: 'PRODUCTION_LAUNCH_VERIFIED',
    circuit_state: 'NORMAL',
    engine_state: 'MICRO_CAPITAL_ACTIVE',
    timestamp_ms: 1790200000000,
    timestamp_utc: '2026-09-23T08:00:00.000000+00:00',
    paper_safe: true,
    execution_authority: false,
    total_orders: 6,
    total_trades: 6,
    interlock_blocks_count: 0,
    intra_day_loss_usdt: 0.0,
    aggregate_exposure_usdt: 0.0,
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    candidate_allocations: [
      {
        symbol: 'BTCUSDT',
        current_price: 95000.0,
        position_qty: 0.0,
        entry_price: 0.0,
        allocated_exposure_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.02,
        total_fees_usdt: 0.002,
        trades_count: 2,
      },
      {
        symbol: 'ETHUSDT',
        current_price: 3300.0,
        position_qty: 0.0,
        entry_price: 0.0,
        allocated_exposure_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.01,
        total_fees_usdt: 0.002,
        trades_count: 2,
      },
      {
        symbol: 'SOLUSDT',
        current_price: 185.0,
        position_qty: 0.0,
        entry_price: 0.0,
        allocated_exposure_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.01,
        total_fees_usdt: 0.002,
        trades_count: 2,
      },
    ],
    recent_orders: [
      {
        order_id: 'ord-btc-01',
        symbol: 'BTCUSDT',
        side: 'BUY',
        order_type: 'LIMIT',
        price: 95000.0,
        quantity: 0.00006,
        notional_usdt: 5.70,
        status: 'FILLED',
        fill_price: 95000.0,
        fee_usdt: 0.002,
        realized_pnl_usdt: 0.0,
        timestamp_ms: 1790200000000,
      },
    ],
    confinement: {
      max_micro_order_notional_usdt: 5.0,
      max_aggregate_exposure_usdt: 25.0,
      min_cash_reserve_pct: 75.0,
      intra_day_loss_ceiling_usdt: 3.0,
      intra_day_loss_observed_usdt: 0.0,
    },
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 100.02,
      allocated_margin_usdt: 0.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: 0.02,
      total_equity_usdt: 100.02,
      total_fees_usdt: 0.006,
      total_slippage_usdt: 0.0,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 100.0,
      unencumbered_cash_verified: true,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 100.02,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.02,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e',
    phase_hash: 'phase309-local-payload-hash',
    merkle_root: '5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844',
  }

  it('renders verified production launch dashboard with all key sections', () => {
    const model = buildProductionLaunchModel(verifiedFixture)
    const html = renderToString(<ProductionLaunchPage model={model} />)

    // Header & phase badges
    expect(html).toContain('PHASE 309')
    expect(html).toContain('PRODUCTION_LAUNCH_VERIFIED')
    expect(html).toContain('PAPER-SAFE:')
    expect(html).toContain('TRUE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('ZERO-DRIFT:')
    expect(html).toContain('VERIFIED')

    // KPI cards
    expect(html).toContain('MICRO_CAPITAL_ACTIVE')
    expect(html).toContain('NORMAL')
    expect(html).toContain('6 ORDERS')
    expect(html).toContain('100.02')
    expect(html).toContain('100.0%')

    // Table content & allocations
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('SOLUSDT')

    // Architecture roadmap
    expect(html).toContain('Alpha Ensemble')
    expect(html).toContain('Auto-Evolution')
    expect(html).toContain('Testnet Bridge')
    expect(html).toContain('Kill-Switch Governance')
    expect(html).toContain('Live Production Launch')

    // Merkle DAG provenance
    expect(html).toContain('65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e')
    expect(html).toContain('5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844')
  })

  it('renders fallback model gracefully without throwing when data is null', () => {
    const model = buildProductionLaunchModel(null)
    const html = renderToString(<ProductionLaunchPage model={model} />)

    expect(html).toContain('PHASE 309')
    expect(html).toContain('UNAVAILABLE')
    expect(html).toContain('PAPER-SAFE:')
    expect(html).toContain('TRUE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
  })
})
