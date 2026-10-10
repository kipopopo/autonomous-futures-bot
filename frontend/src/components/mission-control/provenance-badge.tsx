export type ProvenanceSource = 'LIVE EXCHANGE' | 'DAEMON 24/7' | 'RESEARCH ARTIFACT / SIMULATION'

export interface ProvenanceBadgeProps {
  source: ProvenanceSource
  className?: string
  tooltip?: string
}

export function ProvenanceBadge({ source, className = '', tooltip }: ProvenanceBadgeProps) {
  if (source === 'LIVE EXCHANGE') {
    return (
      <span
        title={tooltip || 'Data langsung dari Binance Futures USDⓈ-M exchange API'}
        className={`inline-flex items-center gap-1.5 text-[10px] font-mono font-bold uppercase tracking-wider py-0.5 px-2 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 shadow-[0_0_8px_rgba(16,185,129,0.15)] ${className}`}
        data-testid="provenance-badge-live-exchange"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        LIVE EXCHANGE
      </span>
    )
  }

  if (source === 'DAEMON 24/7') {
    return (
      <span
        title={tooltip || 'Telemetri langsung dari daemon perdagangan Autonomous Futures di Linux VPS'}
        className={`inline-flex items-center gap-1.5 text-[10px] font-mono font-bold uppercase tracking-wider py-0.5 px-2 rounded-md bg-cyan-500/10 text-cyan-400 border border-cyan-500/25 shadow-[0_0_8px_rgba(6,182,212,0.15)] ${className}`}
        data-testid="provenance-badge-daemon-24-7"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
        DAEMON 24/7
      </span>
    )
  }

  return (
    <span
      title={tooltip || 'Artifak penyelidikan & simulasi berasaskan model sejarah (Phases 250-309)'}
      className={`inline-flex items-center gap-1.5 text-[10px] font-mono font-bold uppercase tracking-wider py-0.5 px-2 rounded-md bg-purple-500/10 text-purple-400 border border-purple-500/25 shadow-[0_0_8px_rgba(168,85,247,0.15)] ${className}`}
      data-testid="provenance-badge-research-artifact"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
      RESEARCH ARTIFACT / SIMULATION
    </span>
  )
}
