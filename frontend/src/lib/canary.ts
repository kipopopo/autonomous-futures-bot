export interface CanarySummaryResponse {
  verified: boolean
  phase: string
  daemon_status: string
  description: string
  manifest_version: number
  staged_manifest_hash: string
  candidates: string[]
  timestamp_utc: string
  circuit_state: string
  compliance: Record<string, boolean>
  daemon_stats: Record<string, string>
  order_stats: {
    interlock_blocks_count?: number
    total_fees_usdt?: string
    total_orders_cancelled?: number
    total_orders_filled?: number
    total_orders_placed?: number
    total_orders_rejected?: number
    total_slippage_usdt?: string
  }
  heartbeat_stats: {
    max_allowed_age_ms?: number
    stale_heartbeat_breaches?: number
    total_heartbeats_recorded?: number
  }
  error_stats: Record<string, number>
  artifact_hashes: Record<string, string>
  tracks_summary: Record<string, unknown>
}

export interface HawkesSnapshot {
  record_id: number
  track_id: string
  symbol: string
  timestamp_utc: string
  jump_intensity: string
  branching_ratio: string
  spectral_radius: string
  self_excitation_alpha: string
  cross_excitation_json: string
  cascade_state: string
  regime: string
  pacing_interval_ms: number
  limit_offset_cushion_bps: string
  full_branching_matrix_json: string
}

export interface CanaryHawkesResponse {
  verified: boolean
  phase: string
  timestamp_utc: string
  candidates: string[]
  snapshots: HawkesSnapshot[]
  current_regime: string
  max_spectral_radius: number
  max_jump_intensity: number
}

export interface Heartbeat {
  record_id: number
  track_id: string
  server_time_ms: number
  local_time_ms: number
  latency_ms: number
  clock_skew_ms: number
  status: string
  is_healthy: boolean
  details: string
  timestamp_utc: string
}

export interface InterlockEvent {
  event_id: string
  timestamp_utc: string
  track_id: string
  interlock_type: string
  allowed: boolean
  symbol: string | null
  notional_usdt: string | null
  details: string
}

export interface CanaryRiskResponse {
  verified: boolean
  phase: string
  circuit_state: string
  aggregate_exposure_cap_usdt: string
  individual_micro_notional_cap_usdt: string
  intra_phase_loss_ceiling_usdt: string
  max_allowed_heartbeat_age_ms: number
  heartbeats: Heartbeat[]
  interlock_events: InterlockEvent[]
  total_interlock_blocks: number
}

export interface BalanceSnapshot {
  snapshot_id: string
  timestamp_utc: string
  track_id: string
  cash_usdt: string
  allocated_margin_usdt: string
  unrealized_pnl_usdt: string
  realized_pnl_usdt: string
  starting_equity_usdt: string
  drift_usdt: string
  zero_balance_drift: boolean
  trigger_event: string
}

export interface DaemonTrack {
  track_id: string
  track_name: string
  status: string
  starting_equity_usdt: string
  final_cash_usdt: string
  allocated_margin_usdt: string
  unrealized_pnl_usdt: string
  realized_pnl_usdt: string
  total_fees_usdt: string
  total_slippage_usdt: string
  drift_usdt: string
  zero_balance_drift: boolean
  orders_placed_count: number
  orders_filled_count: number
  orders_cancelled_count: number
  orders_rejected_count: number
  interlock_blocks_count: number
}

export interface CanaryAccountingResponse {
  verified: boolean
  phase: string
  starting_capital_usdt: string
  final_cash_usdt: string
  final_equity_usdt: string
  realized_pnl_usdt: string
  allocated_margin_usdt: string
  unrealized_pnl_usdt: string
  total_fees_usdt: string
  total_slippage_usdt: string
  drift_usdt: string
  zero_balance_drift: boolean
  tracks: DaemonTrack[]
  recent_balance_snapshots: BalanceSnapshot[]
}

export interface CanaryDashboardData {
  summary: CanarySummaryResponse | null
  hawkes: CanaryHawkesResponse | null
  risk: CanaryRiskResponse | null
  accounting: CanaryAccountingResponse | null
  error: string | null
}

export interface MicrostructureModel {
  phase: string
  candidates: string[]
  currentRegime: string
  maxSpectralRadius: number
  maxJumpIntensity: number
  isSupercritical: boolean
  isHawkesElevated: boolean
  snapshots: HawkesSnapshot[]
  latestBySymbol: Record<string, HawkesSnapshot>
}

export interface RiskModel {
  phase: string
  circuitState: string
  exposureCapUsdt: string
  microCapUsdt: string
  lossCeilingUsdt: string
  maxHeartbeatAgeMs: number
  latestHeartbeat: Heartbeat | null
  totalBlocks: number
  recentInterlocks: InterlockEvent[]
}

export interface AccountingModel {
  phase: string
  startingCapital: string
  finalCash: string
  finalEquity: string
  realizedPnl: string
  allocatedMargin: string
  totalFees: string
  drift: string
  isZeroDrift: boolean
  tracks: DaemonTrack[]
  snapshots: BalanceSnapshot[]
}

export function buildMicrostructureModel(data: CanaryHawkesResponse | null): MicrostructureModel {
  if (!data) {
    return {
      phase: '—',
      candidates: [],
      currentRegime: 'UNKNOWN',
      maxSpectralRadius: 0,
      maxJumpIntensity: 0,
      isSupercritical: false,
      isHawkesElevated: false,
      snapshots: [],
      latestBySymbol: {},
    }
  }

  const latestBySymbol: Record<string, HawkesSnapshot> = {}
  for (const item of data.snapshots) {
    latestBySymbol[item.symbol] = item
  }

  const isSupercritical = data.max_spectral_radius >= 1.0 || data.current_regime.includes('SUPERCRITICAL')
  const isHawkesElevated = data.max_spectral_radius >= 0.85 || data.current_regime.includes('SEVERE')

  return {
    phase: data.phase,
    candidates: data.candidates,
    currentRegime: data.current_regime,
    maxSpectralRadius: data.max_spectral_radius,
    maxJumpIntensity: data.max_jump_intensity,
    isSupercritical,
    isHawkesElevated,
    snapshots: data.snapshots,
    latestBySymbol,
  }
}

export function buildRiskModel(data: CanaryRiskResponse | null): RiskModel {
  if (!data) {
    return {
      phase: '—',
      circuitState: 'UNKNOWN',
      exposureCapUsdt: '—',
      microCapUsdt: '—',
      lossCeilingUsdt: '—',
      maxHeartbeatAgeMs: 500,
      latestHeartbeat: null,
      totalBlocks: 0,
      recentInterlocks: [],
    }
  }

  const latestHeartbeat = data.heartbeats.length > 0 ? data.heartbeats[data.heartbeats.length - 1] : null

  return {
    phase: data.phase,
    circuitState: data.circuit_state,
    exposureCapUsdt: data.aggregate_exposure_cap_usdt,
    microCapUsdt: data.individual_micro_notional_cap_usdt,
    lossCeilingUsdt: data.intra_phase_loss_ceiling_usdt,
    maxHeartbeatAgeMs: data.max_allowed_heartbeat_age_ms,
    latestHeartbeat,
    totalBlocks: data.total_interlock_blocks,
    recentInterlocks: data.interlock_events,
  }
}

export function buildAccountingModel(data: CanaryAccountingResponse | null): AccountingModel {
  if (!data) {
    return {
      phase: '—',
      startingCapital: '—',
      finalCash: '—',
      finalEquity: '—',
      realizedPnl: '—',
      allocatedMargin: '—',
      totalFees: '—',
      drift: '—',
      isZeroDrift: false,
      tracks: [],
      snapshots: [],
    }
  }

  return {
    phase: data.phase,
    startingCapital: data.starting_capital_usdt,
    finalCash: data.final_cash_usdt,
    finalEquity: data.final_equity_usdt,
    realizedPnl: data.realized_pnl_usdt,
    allocatedMargin: data.allocated_margin_usdt,
    totalFees: data.total_fees_usdt,
    drift: data.drift_usdt,
    isZeroDrift: data.zero_balance_drift,
    tracks: data.tracks,
    snapshots: data.recent_balance_snapshots,
  }
}
