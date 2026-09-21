import { describe, expect, it } from 'vitest'

import {
  calculateBackoff,
  getTelemetryWebSocketUrl,
  INITIAL_RECONNECT_DELAY_MS,
  INITIAL_TELEMETRY_STATE,
  MAX_RECONNECT_DELAY_MS,
  MAX_SPECTRAL_RADIUS_HISTORY,
  parseTelemetryEnvelope,
  updateRollingHistory,
} from './websocket'

describe('websocket library', () => {
  describe('getTelemetryWebSocketUrl', () => {
    it('uses custom envUrl when provided', () => {
      const custom = 'ws://api.example.com:9000/ws/telemetry'
      expect(getTelemetryWebSocketUrl(custom)).toBe(custom)
    })

    it('falls back to default host when in node environment', () => {
      const url = getTelemetryWebSocketUrl()
      expect(url).toBe('ws://127.0.0.1:8000/ws/telemetry')
    })
  })

  describe('calculateBackoff', () => {
    it('returns base delay on 0th attempt', () => {
      expect(calculateBackoff(0)).toBe(INITIAL_RECONNECT_DELAY_MS)
      expect(calculateBackoff(-1)).toBe(INITIAL_RECONNECT_DELAY_MS)
    })

    it('calculates exponential backoff for subsequent attempts', () => {
      expect(calculateBackoff(1)).toBe(2000)
      expect(calculateBackoff(2)).toBe(4000)
      expect(calculateBackoff(3)).toBe(8000)
    })

    it('caps delay at MAX_RECONNECT_DELAY_MS', () => {
      expect(calculateBackoff(10)).toBe(MAX_RECONNECT_DELAY_MS)
      expect(calculateBackoff(20)).toBe(MAX_RECONNECT_DELAY_MS)
    })
  })

  describe('updateRollingHistory', () => {
    it('appends new finite numbers', () => {
      const initial = [0.4, 0.5]
      const updated = updateRollingHistory(initial, 0.6)
      expect(updated).toEqual([0.4, 0.5, 0.6])
    })

    it('ignores non-finite values (NaN, Infinity)', () => {
      const initial = [0.4, 0.5]
      expect(updateRollingHistory(initial, NaN)).toEqual(initial)
      expect(updateRollingHistory(initial, Infinity)).toEqual(initial)
    })

    it('caps array to maxCapacity (default 60 points)', () => {
      let buffer: number[] = []
      for (let i = 0; i < 70; i++) {
        buffer = updateRollingHistory(buffer, i)
      }
      expect(buffer.length).toBe(MAX_SPECTRAL_RADIUS_HISTORY)
      expect(buffer[0]).toBe(10) // 70 - 60 = 10
      expect(buffer[buffer.length - 1]).toBe(69)
    })
  })

  describe('parseTelemetryEnvelope', () => {
    it('parses valid envelope JSON correctly', () => {
      const json = JSON.stringify({
        type: 'hawkes_metrics',
        timestamp: '2026-09-21T06:35:00.000000Z',
        data: { spectral_radius: '0.4500' },
        paper_safe_metadata: {
          execution_authority: false,
          paper_safe: true,
          zero_drift_verified: true,
          drift_usdt: '0E-8',
        },
      })
      const envelope = parseTelemetryEnvelope(json)
      expect(envelope).not.toBeNull()
      expect(envelope?.type).toBe('hawkes_metrics')
      expect(envelope?.paper_safe_metadata.execution_authority).toBe(false)
      expect(envelope?.paper_safe_metadata.paper_safe).toBe(true)
    })

    it('returns null on malformed JSON or invalid schema', () => {
      expect(parseTelemetryEnvelope('not a json')).toBeNull()
      expect(parseTelemetryEnvelope('123')).toBeNull()
      expect(parseTelemetryEnvelope(JSON.stringify({ message: 'missing type' }))).toBeNull()
    })
  })

  describe('INITIAL_TELEMETRY_STATE', () => {
    it('has correct fail-closed paper safe defaults', () => {
      expect(INITIAL_TELEMETRY_STATE.status).toBe('DISCONNECTED')
      expect(INITIAL_TELEMETRY_STATE.isConnected).toBe(false)
      expect(INITIAL_TELEMETRY_STATE.paperSafe).toBe(true)
      expect(INITIAL_TELEMETRY_STATE.isSupercritical).toBe(false)
      expect(INITIAL_TELEMETRY_STATE.driftUsdt).toBe('0E-8')
      expect(INITIAL_TELEMETRY_STATE.spectralRadiusHistory).toEqual([])
    })
  })
})
