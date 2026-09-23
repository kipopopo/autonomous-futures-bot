import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { BracketPositionsPage } from '../bracket-positions-page'
import {
  buildBracketPositionsModel,
  type CanaryBracketPositionsData,
} from '../../lib/canary'

describe('BracketPositionsPage component', () => {
  const verifiedFixture: CanaryBracketPositionsData = {
    phase: 'phase_301',
    verified: true,
    status: 'BRACKET_POSITIONS_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1789544000000,
    timestamp_utc: '2026-09-22T08:00:00.000Z',
    paper_safe: true,
    execution_authority: false,
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    positions: [
      {
        symbol: 'BTCUSDT',
        side: 'LONG',
        size: 0.0001,
        entry_price: 50000.0,
        mark_price: 50500.0,
        notional_usdt: 5.05,
        margin_allocated_usdt: 1.68,
        unrealized_pnl_usdt: 0.05,
        realized_pnl_usdt: 0.0,
        liquidation_price_usdt: 33833.33,
        margin_ratio_pct: 3.2,
        risk_state: 'NORMAL',
        brackets_count: 1,
        last_updated_utc: '2026-09-22T08:00:00.000Z',
      },
      {
        symbol: 'ETHUSDT',
        side: 'SHORT',
        size: 0.002,
        entry_price: 2500.0,
        mark_price: 2480.0,
        notional_usdt: 4.96,
        margin_allocated_usdt: 1.65,
        unrealized_pnl_usdt: 0.04,
        realized_pnl_usdt: 0.0,
        liquidation_price_usdt: 3308.33,
        margin_ratio_pct: 3.1,
        risk_state: 'NORMAL',
        brackets_count: 1,
        last_updated_utc: '2026-09-22T08:00:00.000Z',
      },
      {
        symbol: 'SOLUSDT',
        side: 'FLAT',
        size: 0.0,
        entry_price: 0.0,
        mark_price: 150.0,
        notional_usdt: 0.0,
        margin_allocated_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.0,
        liquidation_price_usdt: 0.0,
        margin_ratio_pct: 0.0,
        risk_state: 'NORMAL',
        brackets_count: 0,
        last_updated_utc: '2026-09-22T08:00:00.000Z',
      },
    ],
    brackets: [
      {
        bracket_id: 'bracket-btc-001',
        symbol: 'BTCUSDT',
        side: 'LONG',
        parent_order_id: 'ord-btc-parent-001',
        entry_price: 50000.0,
        take_profit_price: 52500.0,
        stop_loss_trigger_price: 49250.0,
        trailing_delta_bps: 150.0,
        high_watermark: 50500.0,
        low_watermark: 50000.0,
        status: 'ACTIVE',
        oco_partner_id: 'oco-btc-sibling-001',
        created_at_utc: '2026-09-22T07:59:50.000Z',
        last_updated_utc: '2026-09-22T08:00:00.000Z',
      },
      {
        bracket_id: 'bracket-eth-002',
        symbol: 'ETHUSDT',
        side: 'SHORT',
        parent_order_id: 'ord-eth-parent-002',
        entry_price: 2500.0,
        take_profit_price: 2375.0,
        stop_loss_trigger_price: 2537.5,
        trailing_delta_bps: 150.0,
        high_watermark: 2500.0,
        low_watermark: 2480.0,
        status: 'ACTIVE',
        oco_partner_id: 'oco-eth-sibling-002',
        created_at_utc: '2026-09-22T07:59:52.000Z',
        last_updated_utc: '2026-09-22T08:00:00.000Z',
      },
    ],
    stream_events: [
      {
        event_id: 'evt-stream-001',
        event_type: 'ACCOUNT_UPDATE',
        event_time_ms: 1789544000000,
        payload_hash: 'c8f12a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f',
        latency_ms: 0.12,
        timestamp_utc: '2026-09-22T08:00:00.000Z',
      },
      {
        event_id: 'evt-stream-002',
        event_type: 'ORDER_TRADE_UPDATE',
        event_time_ms: 1789544001000,
        payload_hash: 'd9e01f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e',
        latency_ms: 0.15,
        timestamp_utc: '2026-09-22T08:00:01.000Z',
      },
    ],
    stream_metrics: {
      total_events: 2,
      mean_latency_ms: 0.135,
      max_latency_ms: 0.15,
      heartbeat_valid: true,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 96.67,
      allocated_margin: 3.33,
      unrealized_pnl: 0.09,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 96.67,
      allocated_margin_usdt: 3.33,
      unrealized_pnl_usdt: 0.09,
      realized_pnl_usdt: 0.0,
      total_equity_usdt: 100.09,
      total_fees_usdt: 0.0,
      total_slippage_usdt: 0.0,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 96.67,
      unencumbered_cash_verified: true,
    },
    upstream_hash: '25c81437dc77630dd8a143aea2056a126c16d908573d69a79676bc223fbbd14c',
    phase_hash: 'phase301_hash_mock_000000000000000000000000000000000000000000000000',
    merkle_root: 'merkle301_root_mock_0000000000000000000000000000000000000000000000',
  }

  it('renders top banner and global safety indicators', () => {
    const model = buildBracketPositionsModel(verifiedFixture)
    const html = renderToString(<BracketPositionsPage model={model} />)

    expect(html).toContain('Dynamic Position &amp; Bracket Order Management')
    expect(html).toContain('PHASE 301')
    expect(html).toContain('BRACKET_POSITIONS_VERIFIED')
    expect(html).toContain('PAPER SAFE: VERIFIED')
    expect(html).toContain('AUTHORITY: OFF')
    expect(html).toContain('ZERO DRIFT: 0.00 USDT')
  })

  it('renders KPI summary cards', () => {
    const model = buildBracketPositionsModel(verifiedFixture)
    const html = renderToString(<BracketPositionsPage model={model} />)

    expect(html).toContain('Multi-Asset Positions')
    expect(html).toContain('2 / 3 Active')
    expect(html).toContain('Bracket Orders')
    expect(html).toContain('2 Bound')
    expect(html).toContain('User Stream Ingress')
    expect(html).toContain('2 Events')
    expect(html).toContain('Cash Reserve')
    expect(html).toContain('96.7%')
  })

  it('renders Multi-Asset Position Tracker table with symbols and risk states', () => {
    const model = buildBracketPositionsModel(verifiedFixture)
    const html = renderToString(<BracketPositionsPage model={model} />)

    expect(html).toContain('Multi-Asset Position Tracker')
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('LONG')
    expect(html).toContain('SHORT')
    expect(html).toContain('FLAT')
    expect(html).toContain('3.2%')
    expect(html).toContain('3.1%')
  })

  it('renders Dynamic Bracket Orders table and watermark ratcheting', () => {
    const model = buildBracketPositionsModel(verifiedFixture)
    const html = renderToString(<BracketPositionsPage model={model} />)

    expect(html).toContain('Dynamic Bracket Orders')
    expect(html).toContain('bracket-btc-001')
    expect(html).toContain('bracket-eth-002')
    expect(html).toContain('$52500.00')
    expect(html).toContain('$49250.00')
    expect(html).toContain('$2375.00')
    expect(html).toContain('$2537.50')
  })

  it('renders Bracket Inspection detail card with OCO information', () => {
    const model = buildBracketPositionsModel(verifiedFixture)
    const html = renderToString(<BracketPositionsPage model={model} />)

    expect(html).toContain('Bracket Inspection')
    expect(html).toContain('bracket-btc-001')
    expect(html).toContain('ord-btc-parent-001')
    expect(html).toContain('oco-btc-sibling-001')
    expect(html).toContain('150 bps')
  })

  it('renders User Data Stream Ingress events and sub-500 ms SLA', () => {
    const model = buildBracketPositionsModel(verifiedFixture)
    const html = renderToString(<BracketPositionsPage model={model} />)

    expect(html).toContain('User Data Stream Ingress')
    expect(html).toContain('SLA ≤ 500 ms')
    expect(html).toContain('ACCOUNT_UPDATE')
    expect(html).toContain('ORDER_TRADE_UPDATE')
    expect(html).toContain('evt-stream-001')
    expect(html).toContain('0.12 ms')
  })

  it('renders Double-Entry Balance Governance and Merkle DAG linkage', () => {
    const model = buildBracketPositionsModel(verifiedFixture)
    const html = renderToString(<BracketPositionsPage model={model} />)

    expect(html).toContain('Double-Entry Balance Governance')
    expect(html).toContain('ZERO DRIFT VERIFIED')
    expect(html).toContain('$96.67')
    expect(html).toContain('$3.33')
    expect(html).toContain('$100.0900')
    expect(html).toContain('25c81437dc77630d...')
  })

  it('handles null/default data safely without crashing', () => {
    const defaultModel = buildBracketPositionsModel(null)
    const html = renderToString(<BracketPositionsPage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Dynamic Position &amp; Bracket Order Management')
    expect(html).toContain('PHASE 301')
    expect(html).toContain('Double-Entry Balance Governance')
  })

  it('handles raw backend live payload safely without crashing', () => {
    const rawBackendPayload = {
      verified: true,
      phase: 'phase_301',
      status: 'BRACKET_POSITIONS_VERIFIED',
      timestamp_ms: 1789544000000,
      timestamp_utc: '2026-09-22T08:00:00.000Z',
      paper_safe: true,
      execution_authority: false,
      circuit_state: 'NORMAL',
      candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
      all_positions: [
        {
          symbol: 'BTCUSDT',
          side: 'FLAT',
          size: 0.0,
          entry_price: 50000.0,
          mark_price: 50000.0,
          notional_usdt: 0.0,
          margin_allocated_usdt: 0.0,
          unrealized_pnl_usdt: 0.0,
          realized_pnl_usdt: 0.075,
          liquidation_price_usdt: 33833.33,
          margin_ratio_pct: 0.0,
          risk_state: 'NORMAL',
          brackets: [],
          last_updated_utc: '2026-09-22T17:37:13.087273+00:00',
        },
      ],
      brackets: [
        {
          bracket_id: 'brk-tp-c6b150c388',
          entry_order_id: 'cl-t2-btc-entry',
          symbol: 'BTCUSDT',
          bracket_type: 'TAKE_PROFIT_LIMIT',
          side: 'SELL',
          status: 'FILLED',
          trigger_price: 50750.0,
          limit_price: 50750.0,
          quantity: 0.0001,
          notional_usdt: 5.0,
          ratchet_watermark: 50000.0,
          callback_rate_pct: 0.008,
          created_at_utc: '2026-09-22T17:37:13.087247+00:00',
          triggered_at_utc: '2026-09-22T17:37:13.087266+00:00',
          filled_at_utc: '2026-09-22T17:37:13.087266+00:00',
          fee_usdt: 0.001,
          cancellation_reason: null,
        },
        {
          bracket_id: 'brk-tsl-0072bd195c',
          entry_order_id: 'cl-t2-btc-entry',
          symbol: 'BTCUSDT',
          bracket_type: 'TRAILING_STOP_MARKET',
          side: 'SELL',
          status: 'CANCELED',
          trigger_price: 50096.0,
          limit_price: null,
          quantity: 0.0001,
          notional_usdt: 5.0,
          ratchet_watermark: 50500.0,
          callback_rate_pct: 0.008,
          created_at_utc: '2026-09-22T17:37:13.087247+00:00',
          triggered_at_utc: null,
          filled_at_utc: null,
          fee_usdt: 0.0,
          cancellation_reason: 'OCO mutual cancellation: triggered by brk-tp-c6b150c388',
        },
      ],
      recent_events: [
        {
          event_id: 'evt-662af5e94f1c',
          event_type: 'ACCOUNT_UPDATE',
          symbol: null,
          timestamp_utc: '2026-09-22T17:37:13.087184+00:00',
          latency_ms: 0.012,
        },
      ],
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const model = buildBracketPositionsModel(rawBackendPayload as any)
    const html = renderToString(<BracketPositionsPage model={model} />)
    expect(html).toBeDefined()
    expect(html).toContain('brk-tp-c6b150c388')
    expect(html).toContain('brk-tsl-0072bd195c')
    expect(html).toContain('cl-t2-btc-entry')
  })
})
