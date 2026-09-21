import { describe, expect, it } from 'vitest'

import {
  buildAccountingModel,
  buildMicrostructureModel,
  buildRiskModel,
  type CanaryAccountingResponse,
  type CanaryHawkesResponse,
  type CanaryRiskResponse,
} from './canary'

describe('canary models', () => {
  describe('buildMicrostructureModel', () => {
    it('handles null data safely', () => {
      const model = buildMicrostructureModel(null)
      expect(model.phase).toBe('—')
      expect(model.currentRegime).toBe('UNKNOWN')
      expect(model.isSupercritical).toBe(false)
      expect(model.isHawkesElevated).toBe(false)
      expect(model.snapshots).toHaveLength(0)
    })

    it('processes Hawkes snapshots and detects elevated or supercritical regimes', () => {
      const fixture: CanaryHawkesResponse = {
        verified: true,
        phase: 'phase_291',
        timestamp_utc: '2026-09-21T03:29:37Z',
        candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        current_regime: 'SUPERCRITICAL_CASCADE',
        max_spectral_radius: 1.394679,
        max_jump_intensity: 1.68,
        snapshots: [
          {
            record_id: 1,
            track_id: 'track_1',
            symbol: 'BTCUSDT',
            timestamp_utc: '2026-09-21T03:29:37Z',
            jump_intensity: '0.350000',
            branching_ratio: '0.2500',
            spectral_radius: '0.491677',
            self_excitation_alpha: '0.12',
            cross_excitation_json: '{}',
            cascade_state: 'NORMAL',
            regime: 'NOMINAL',
            pacing_interval_ms: 100,
            limit_offset_cushion_bps: '0.0',
            full_branching_matrix_json: '[[0.25]]',
          },
          {
            record_id: 2,
            track_id: 'track_3',
            symbol: 'SOLUSDT',
            timestamp_utc: '2026-09-21T03:29:38Z',
            jump_intensity: '1.680000',
            branching_ratio: '1.2000',
            spectral_radius: '1.394679',
            self_excitation_alpha: '0.45',
            cross_excitation_json: '{}',
            cascade_state: 'SEVERE_PREDATORY_FRONT_RUNNING',
            regime: 'SUPERCRITICAL_CASCADE',
            pacing_interval_ms: 1000,
            limit_offset_cushion_bps: '5.0',
            full_branching_matrix_json: '[[1.20]]',
          },
        ],
      }

      const model = buildMicrostructureModel(fixture)
      expect(model.phase).toBe('phase_291')
      expect(model.isSupercritical).toBe(true)
      expect(model.isHawkesElevated).toBe(true)
      expect(model.snapshots).toHaveLength(2)
      expect(model.latestBySymbol['BTCUSDT'].regime).toBe('NOMINAL')
      expect(model.latestBySymbol['SOLUSDT'].regime).toBe('SUPERCRITICAL_CASCADE')
    })
  })

  describe('buildRiskModel', () => {
    it('handles null data safely', () => {
      const model = buildRiskModel(null)
      expect(model.phase).toBe('—')
      expect(model.circuitState).toBe('UNKNOWN')
      expect(model.latestHeartbeat).toBeNull()
      expect(model.totalBlocks).toBe(0)
    })

    it('builds risk telemetry and tracks interlocks', () => {
      const fixture: CanaryRiskResponse = {
        verified: true,
        phase: 'phase_291',
        circuit_state: 'NORMAL',
        aggregate_exposure_cap_usdt: '60.00',
        individual_micro_notional_cap_usdt: '5.00',
        intra_phase_loss_ceiling_usdt: '7.0',
        max_allowed_heartbeat_age_ms: 500,
        heartbeats: [
          {
            record_id: 1,
            track_id: 'track_1',
            server_time_ms: 1789447964946,
            local_time_ms: 1789447964946,
            latency_ms: 18.5,
            clock_skew_ms: 0.1,
            status: 'HEALTHY',
            is_healthy: true,
            details: 'Heartbeat OK',
            timestamp_utc: '2026-09-21T03:29:37Z',
          },
        ],
        interlock_events: [
          {
            event_id: 'ev-1',
            timestamp_utc: '2026-09-21T03:29:37Z',
            track_id: 'track_2',
            interlock_type: 'HAWKES_CASCADE_BURST_PACING',
            allowed: false,
            symbol: 'SOLUSDT',
            notional_usdt: '5.00',
            details: 'Order throttled by Hawkes cascade',
          },
        ],
        total_interlock_blocks: 1,
      }

      const model = buildRiskModel(fixture)
      expect(model.phase).toBe('phase_291')
      expect(model.exposureCapUsdt).toBe('60.00')
      expect(model.microCapUsdt).toBe('5.00')
      expect(model.totalBlocks).toBe(1)
      expect(model.latestHeartbeat?.status).toBe('HEALTHY')
      expect(model.latestHeartbeat?.latency_ms).toBe(18.5)
    })
  })

  describe('buildAccountingModel', () => {
    it('handles null data safely', () => {
      const model = buildAccountingModel(null)
      expect(model.phase).toBe('—')
      expect(model.isZeroDrift).toBe(false)
      expect(model.tracks).toHaveLength(0)
    })

    it('builds zero-drift double-entry verification model', () => {
      const fixture: CanaryAccountingResponse = {
        verified: true,
        phase: 'phase_291',
        starting_capital_usdt: '100.00',
        final_cash_usdt: '99.99460000',
        final_equity_usdt: '99.99460000',
        realized_pnl_usdt: '-0.00540000',
        allocated_margin_usdt: '0.0',
        unrealized_pnl_usdt: '0.0',
        total_fees_usdt: '0.010889',
        total_slippage_usdt: '0.000000',
        drift_usdt: '0E-8',
        zero_balance_drift: true,
        tracks: [
          {
            track_id: 'track_1',
            track_name: 'Ingress Replay',
            status: 'SUCCESS',
            starting_equity_usdt: '100.00',
            final_cash_usdt: '99.99460000',
            allocated_margin_usdt: '0.0',
            unrealized_pnl_usdt: '0.0',
            realized_pnl_usdt: '-0.00540000',
            total_fees_usdt: '0.00540000',
            total_slippage_usdt: '0.0',
            drift_usdt: '0E-8',
            zero_balance_drift: true,
            orders_placed_count: 9,
            orders_filled_count: 9,
            orders_cancelled_count: 0,
            orders_rejected_count: 0,
            interlock_blocks_count: 0,
          },
        ],
        recent_balance_snapshots: [
          {
            snapshot_id: 'snap-1',
            timestamp_utc: '2026-09-21T03:29:37Z',
            track_id: 'track_1',
            cash_usdt: '100.00',
            allocated_margin_usdt: '0.0',
            unrealized_pnl_usdt: '0.0',
            realized_pnl_usdt: '0.0',
            starting_equity_usdt: '100.00',
            drift_usdt: '0.00',
            zero_balance_drift: true,
            trigger_event: 'DAEMON_INITIALIZED',
          },
        ],
      }

      const model = buildAccountingModel(fixture)
      expect(model.phase).toBe('phase_291')
      expect(model.isZeroDrift).toBe(true)
      expect(model.drift).toBe('0E-8')
      expect(model.startingCapital).toBe('100.00')
      expect(model.finalCash).toBe('99.99460000')
      expect(model.tracks).toHaveLength(1)
      expect(model.snapshots).toHaveLength(1)
    })
  })
})
