/**
 * Real-time Telemetry WebSocket Subscription Hook & State Machine (Phase 293).
 *
 * Provides:
 * - Persistent WebSocket connection to `/ws/telemetry` with automatic exponential backoff.
 * - Live connection status (`STREAMING` | `RECONNECTING` | `DISCONNECTED`).
 * - 60-point rolling spectral radius ring buffer.
 * - ~5 Hz throttled state dispatcher with immediate bypass for critical alerts (rho >= 1.0).
 * - Pure helper functions for Vitest testing.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  HazardAlertData,
  HawkesLiveMetricsData,
  MicrostructureTelemetryData,
  RegimeChangeData,
  TelemetryStreamEnvelope,
} from './canary'

export type ConnectionStatus = 'STREAMING' | 'RECONNECTING' | 'DISCONNECTED'

export const MAX_SPECTRAL_RADIUS_HISTORY = 60
export const THROTTLE_INTERVAL_MS = 200 // ~5 Hz update rate
export const INITIAL_RECONNECT_DELAY_MS = 1000
export const MAX_RECONNECT_DELAY_MS = 15000

/**
 * Determine the WebSocket URL from environment or current window location.
 */
export function getTelemetryWebSocketUrl(envUrl?: string): string {
  if (envUrl && typeof envUrl === 'string' && envUrl.trim().length > 0) {
    return envUrl.trim()
  }

  if (typeof window !== 'undefined' && window.location) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host || '127.0.0.1:8000'
    return `${protocol}//${host}/ws/telemetry`
  }

  return 'ws://127.0.0.1:8000/ws/telemetry'
}

/**
 * Calculate exponential backoff with jitter and cap.
 */
export function calculateBackoff(
  attempt: number,
  baseMs = INITIAL_RECONNECT_DELAY_MS,
  maxMs = MAX_RECONNECT_DELAY_MS
): number {
  if (attempt <= 0) return baseMs
  const delay = baseMs * Math.pow(2, attempt)
  return Math.min(delay, maxMs)
}

/**
 * Update a rolling fixed-capacity history buffer (pure function).
 */
export function updateRollingHistory(
  history: number[],
  newValue: number,
  maxCapacity = MAX_SPECTRAL_RADIUS_HISTORY
): number[] {
  if (!Number.isFinite(newValue)) return history
  const next = [...history, newValue]
  if (next.length > maxCapacity) {
    return next.slice(next.length - maxCapacity)
  }
  return next
}

/**
 * Parse and validate incoming wire frame into TelemetryStreamEnvelope.
 */
export function parseTelemetryEnvelope(raw: string): TelemetryStreamEnvelope | null {
  try {
    const parsed = JSON.parse(raw) as TelemetryStreamEnvelope
    if (parsed && typeof parsed === 'object' && typeof parsed.type === 'string') {
      return parsed
    }
    return null
  } catch {
    return null
  }
}

export interface TelemetryState {
  status: ConnectionStatus
  isConnected: boolean
  lastMessageTime: string | null
  spectralRadiusHistory: number[]
  latestHawkes: HawkesLiveMetricsData | null
  latestMicrostructure: Record<string, MicrostructureTelemetryData>
  activeRegime: string
  hazardAlert: HazardAlertData | null
  recentAlerts: HazardAlertData[]
  isSupercritical: boolean
  paperSafe: boolean
  driftUsdt: string
}

export const INITIAL_TELEMETRY_STATE: TelemetryState = {
  status: 'DISCONNECTED',
  isConnected: false,
  lastMessageTime: null,
  spectralRadiusHistory: [],
  latestHawkes: null,
  latestMicrostructure: {},
  activeRegime: 'NOMINAL',
  hazardAlert: null,
  recentAlerts: [],
  isSupercritical: false,
  paperSafe: true,
  driftUsdt: '0E-8',
}

/**
 * React hook managing the real-time telemetry WebSocket connection.
 */
export function useTelemetryWebSocket(customWsUrl?: string) {
  const [state, setState] = useState<TelemetryState>(INITIAL_TELEMETRY_STATE)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptRef = useRef<number>(0)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const throttleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef<boolean>(true)

  // Mutable buffer for high-frequency incoming ticks
  const pendingUpdatesRef = useRef<{
    hawkes?: HawkesLiveMetricsData
    microstructure?: Record<string, MicrostructureTelemetryData>
    rho?: number
    regime?: string
  }>({})

  const flushPendingUpdates = useCallback(() => {
    if (!isMountedRef.current) return
    const pending = pendingUpdatesRef.current
    pendingUpdatesRef.current = {}

    setState((prev) => {
      let nextHistory = prev.spectralRadiusHistory
      if (pending.rho !== undefined) {
        nextHistory = updateRollingHistory(prev.spectralRadiusHistory, pending.rho)
      }

      return {
        ...prev,
        spectralRadiusHistory: nextHistory,
        latestHawkes: pending.hawkes ?? prev.latestHawkes,
        latestMicrostructure: pending.microstructure
          ? { ...prev.latestMicrostructure, ...pending.microstructure }
          : prev.latestMicrostructure,
        activeRegime: pending.regime ?? prev.activeRegime,
      }
    })
  }, [])

  const handleEnvelope = useCallback(
    (envelope: TelemetryStreamEnvelope) => {
      const nowUtc = envelope.timestamp || new Date().toISOString()

      if (envelope.type === 'initial_state') {
        const data = envelope.data as Record<string, unknown>
        const hawkes = data.hawkes as HawkesLiveMetricsData | undefined
        const micro = data.microstructure as Record<string, MicrostructureTelemetryData> | undefined
        const alerts = (data.recent_alerts as HazardAlertData[]) || []
        const rhoNum = hawkes?.spectral_radius ? Number(hawkes.spectral_radius) : 0.428571

        setState((prev) => ({
          ...prev,
          status: 'STREAMING',
          isConnected: true,
          lastMessageTime: nowUtc,
          spectralRadiusHistory: updateRollingHistory(prev.spectralRadiusHistory, rhoNum),
          latestHawkes: hawkes ?? prev.latestHawkes,
          latestMicrostructure: micro ?? prev.latestMicrostructure,
          activeRegime: hawkes?.regimes?.SOLUSDT ?? 'NOMINAL',
          recentAlerts: alerts.length > 0 ? alerts : prev.recentAlerts,
          isSupercritical: hawkes?.is_supercritical ?? false,
          paperSafe: envelope.paper_safe_metadata?.paper_safe ?? true,
          driftUsdt: envelope.paper_safe_metadata?.drift_usdt ?? '0E-8',
        }))
        return
      }

      if (envelope.type === 'hazard_alert') {
        // Critical alert: immediate bypass of throttle!
        const alert = envelope.data as HazardAlertData
        setState((prev) => {
          const rhoNum = Number(alert.spectral_radius)
          const nextHistory = Number.isFinite(rhoNum)
            ? updateRollingHistory(prev.spectralRadiusHistory, rhoNum)
            : prev.spectralRadiusHistory

          return {
            ...prev,
            hazardAlert: alert,
            recentAlerts: [alert, ...prev.recentAlerts].slice(0, 50),
            isSupercritical: alert.hazard_type === 'SUPERCRITICAL_CASCADE',
            spectralRadiusHistory: nextHistory,
            lastMessageTime: nowUtc,
          }
        })
        return
      }

      if (envelope.type === 'regime_change') {
        // High-priority regime change: update immediately
        const regData = envelope.data as RegimeChangeData
        const rhoNum = Number(regData.spectral_radius)
        setState((prev) => ({
          ...prev,
          activeRegime: regData.current_regime,
          spectralRadiusHistory: Number.isFinite(rhoNum)
            ? updateRollingHistory(prev.spectralRadiusHistory, rhoNum)
            : prev.spectralRadiusHistory,
          lastMessageTime: nowUtc,
        }))
        return
      }

      if (envelope.type === 'hawkes_metrics') {
        const metrics = envelope.data as HawkesLiveMetricsData
        const rhoNum = Number(metrics.spectral_radius)

        // If supercritical, bypass throttle immediately
        if (metrics.is_supercritical) {
          setState((prev) => ({
            ...prev,
            latestHawkes: metrics,
            isSupercritical: true,
            spectralRadiusHistory: updateRollingHistory(prev.spectralRadiusHistory, rhoNum),
            activeRegime: metrics.regimes?.SOLUSDT || 'SUPERCRITICAL_CASCADE',
            lastMessageTime: nowUtc,
          }))
          return
        }

        // Buffer normal ticks to prevent React VDOM thrashing
        pendingUpdatesRef.current.hawkes = metrics
        pendingUpdatesRef.current.rho = rhoNum
        pendingUpdatesRef.current.regime = metrics.regimes?.SOLUSDT || prevRegimeOrFallback(metrics)

        if (!throttleTimerRef.current) {
          throttleTimerRef.current = setTimeout(() => {
            throttleTimerRef.current = null
            flushPendingUpdates()
          }, THROTTLE_INTERVAL_MS)
        }
        return
      }

      if (envelope.type === 'microstructure_snapshot') {
        const micro = envelope.data as MicrostructureTelemetryData
        if (!pendingUpdatesRef.current.microstructure) {
          pendingUpdatesRef.current.microstructure = {}
        }
        pendingUpdatesRef.current.microstructure[micro.symbol] = micro

        if (!throttleTimerRef.current) {
          throttleTimerRef.current = setTimeout(() => {
            throttleTimerRef.current = null
            flushPendingUpdates()
          }, THROTTLE_INTERVAL_MS)
        }
      }
    },
    [flushPendingUpdates]
  )

  const connect = useCallback(() => {
    if (!isMountedRef.current) return
    const url = getTelemetryWebSocketUrl(customWsUrl)

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (!isMountedRef.current) return
        reconnectAttemptRef.current = 0
        setState((prev) => ({
          ...prev,
          status: 'STREAMING',
          isConnected: true,
        }))
      }

      ws.onmessage = (event: MessageEvent) => {
        if (!isMountedRef.current) return
        if (typeof event.data === 'string') {
          const envelope = parseTelemetryEnvelope(event.data)
          if (envelope) {
            handleEnvelope(envelope)
          }
        }
      }

      ws.onerror = () => {
        // Handled in onclose
      }

      ws.onclose = () => {
        if (!isMountedRef.current) return
        wsRef.current = null
        const attempt = reconnectAttemptRef.current + 1
        reconnectAttemptRef.current = attempt
        const delay = calculateBackoff(attempt)

        setState((prev) => ({
          ...prev,
          status: 'RECONNECTING',
          isConnected: false,
        }))

        reconnectTimeoutRef.current = setTimeout(() => {
          if (isMountedRef.current) {
            connect()
          }
        }, delay)
      }
    } catch {
      setState((prev) => ({
        ...prev,
        status: 'DISCONNECTED',
        isConnected: false,
      }))
    }
  }, [customWsUrl, handleEnvelope])

  useEffect(() => {
    isMountedRef.current = true
    connect()

    return () => {
      isMountedRef.current = false
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (throttleTimerRef.current) {
        clearTimeout(throttleTimerRef.current)
      }
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  return state
}

function prevRegimeOrFallback(metrics: HawkesLiveMetricsData): string {
  const values = Object.values(metrics.regimes || {})
  return values[0] || 'NOMINAL'
}
