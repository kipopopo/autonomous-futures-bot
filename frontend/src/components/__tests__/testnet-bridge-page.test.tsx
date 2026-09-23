import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { TestnetBridgePage } from '../testnet-bridge-page'
import {
  buildTestnetBridgeModel,
  type CanaryTestnetBridgeData,
} from '../../lib/canary'

describe('TestnetBridgePage component', () => {
  const verifiedFixture: CanaryTestnetBridgeData = {
    phase: 'phase_307',
    verified: true,
    status: 'TESTNET_BRIDGE_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1790148000000,
    timestamp_utc: '2026-09-23T07:20:00.000000+00:00',
    paper_safe: true,
    execution_authority: false,
    bridge: {
      connection_state: 'CONNECTED',
      api_key_masked: 'mock-****-7f89',
      is_mock_credentials: true,
      clock_offset_ms: 12,
      clock_skew_verified: true,
      listen_key: 'lk-testnet-live-bridge-001',
      listen_key_active: true,
    },
    performance: {
      total_orders_dispatched: 12,
      total_orders_filled: 12,
      fill_rate_pct: 100.0,
      mean_round_trip_ms: 18.5,
      mean_filter_latency_us: 14.2,
      mean_sign_latency_us: 28.6,
      max_micro_notional_usdt: 5.71,
      micro_cap_verified: true,
      lot_size_filter_verified: true,
      price_filter_verified: true,
      min_notional_verified: true,
    },
    exchange_filters: {
      BTCUSDT: {
        symbol: 'BTCUSDT',
        step_size: 0.00001,
        min_qty: 0.00001,
        max_qty: 100.0,
        tick_size: 0.1,
        min_price: 1000.0,
        max_price: 500000.0,
        min_notional_usdt: 5.0,
        max_micro_cap_usdt: 5.0,
      },
      ETHUSDT: {
        symbol: 'ETHUSDT',
        step_size: 0.001,
        min_qty: 0.001,
        max_qty: 1000.0,
        tick_size: 0.01,
        min_price: 100.0,
        max_price: 50000.0,
        min_notional_usdt: 5.0,
        max_micro_cap_usdt: 5.0,
      },
    },
    dispatched_orders_trace: [
      {
        order_id: 'ord-testnet-btc-001',
        exchange_order_id: 1001,
        candidate_id: 'cand-btcusdt-dcb-002',
        symbol: 'BTCUSDT',
        side: 'BUY',
        order_type: 'LIMIT',
        price: 95000.0,
        qty: 0.00006,
        notional_usdt: 5.70,
        lifecycle: 'FILLED',
        tau_filter_us: 14.2,
        tau_sign_us: 28.6,
        tau_dispatch_ms: 2.1,
        tau_rtt_ms: 18.5,
        fill_price: 95000.0,
        fill_qty: 0.00006,
        fee_cost_usdt: 0.001,
        timestamp_ms: 1790148000000,
        error_code: null,
      },
    ],
    user_data_events_trace: [
      {
        event_id: 'evt-testnet-001',
        event_type: 'ORDER_TRADE_UPDATE',
        listen_key: 'lk-testnet-live-bridge-001',
        symbol: 'BTCUSDT',
        order_id: 'ord-testnet-btc-001',
        order_status: 'FILLED',
        balance_delta_usdt: 0.05,
        margin_delta_usdt: 0.0,
        timestamp_ms: 1790148000000,
      },
    ],
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 100.12,
      allocated_margin_usdt: 0.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: 0.12,
      total_equity_usdt: 100.12,
      total_fees_usdt: 0.01,
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
      cash: 100.12,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.12,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '818fd82458a8fb19420dd0179c8f78b0c273e5d2a71b1968b083d20f99e23dbe',
    phase_hash: 'phase307-local-hash',
    merkle_root: '4eb405de6cdc48e26fddaa4a2ed8bd91ef9e0843a4b71cfd0cb643a15e7ceb16',
  }

  it('renders verified testnet bridge dashboard with all key sections', () => {
    const model = buildTestnetBridgeModel(verifiedFixture)
    const html = renderToString(<TestnetBridgePage model={model} />)

    // Header & phase badges
    expect(html).toContain('PHASE 307')
    expect(html).toContain('TESTNET_BRIDGE_VERIFIED')
    expect(html).toContain('PAPER-SAFE:')
    expect(html).toContain('TRUE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
    expect(html).toContain('ZERO-DRIFT:')
    expect(html).toContain('VERIFIED')

    // KPI cards
    expect(html).toContain('CONNECTED')
    expect(html).toContain('mock-****-7f89')
    expect(html).toContain('12 ms')
    expect(html).toContain('100.0%')
    expect(html).toContain('18.5')
    expect(html).toContain('14.2')
    expect(html).toContain('28.6')
    expect(html).toContain('100.12')

    // Exchange filters
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')

    // Dispatched orders
    expect(html).toContain('ord-testnet-btc-001')
    expect(html).toContain('FILLED')

    // User data stream events
    expect(html).toContain('evt-testnet-001')
    expect(html).toContain('ORDER_TRADE_UPDATE')

    // Merkle provenance
    expect(html).toContain('4eb405de6cdc48e26fddaa4a2ed8bd91ef9e0843a4b71cfd0cb643a15e7ceb16')
  })

  it('renders fallback model gracefully without throwing when data is null', () => {
    const model = buildTestnetBridgeModel(null)
    const html = renderToString(<TestnetBridgePage model={model} />)

    expect(html).toContain('PHASE 307')
    expect(html).toContain('UNAVAILABLE')
    expect(html).toContain('PAPER-SAFE:')
    expect(html).toContain('TRUE')
    expect(html).toContain('EXECUTION AUTHORITY: OFF')
  })
})
