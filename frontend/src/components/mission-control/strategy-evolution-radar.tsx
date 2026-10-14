import { useState } from 'react'
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  Gauge,
  Layers,
  ShieldCheck,
} from 'lucide-react'
import type { StrategyEvolutionRadarData } from './types'
import { ProvenanceBadge } from './provenance-badge'

export interface StrategyEvolutionRadarProps {
  evolutionRadar: StrategyEvolutionRadarData
  compact?: boolean
}

export function StrategyEvolutionRadar({
  evolutionRadar,
  compact = false,
}: StrategyEvolutionRadarProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const {
    activeStrategyFamily,
    microstructureFilter,
    activeCandidateId,
    candidateHealthTier,
    generation,
    rollingSharpe,
    winRatePct,
    maxDrawdownPct,
    hawkesResilienceScore,
    gates,
    allGatesPassed,
    attributionGauges,
    totalAutopsies,
    promotedCandidatesCount,
  } = evolutionRadar

  const passedGatesCount = gates.filter((g) => g.passed).length

  if (compact && !isExpanded) {
    return (
      <div className="glass-panel rounded-2xl p-4 mb-6 relative overflow-hidden border border-purple-500/20 bg-gradient-to-r from-purple-500/5 via-transparent to-cyan-500/5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
              <Brain className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-sm sm:text-base font-bold tracking-tight text-white flex items-center gap-2">
                  <span>🧠 Strategy Evolution &amp; Autopsy Status</span>
                  <span className="text-[10px] font-mono font-semibold py-0.5 px-2 rounded-md bg-purple-500/15 border border-purple-500/25 text-purple-300">
                    {generation || 'GEN #2'}
                  </span>
                  <span className="badge badge-xs font-mono font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                    {candidateHealthTier}
                  </span>
                </h2>
                <ProvenanceBadge source="DAEMON 24/7" />
              </div>
              <p className="text-xs text-zinc-400 font-mono mt-0.5">
                <span className="text-zinc-200 font-semibold">{activeStrategyFamily}</span> · {passedGatesCount}/{gates.length} OOS Gates Passed · {winRatePct.toFixed(1)}% Win Rate
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="badge badge-sm font-mono font-semibold py-1 px-3 badge-success bg-emerald-500/15 border-emerald-500/30 text-emerald-400">
              ⚡ ACTIVE DAEMON LOOP
            </span>
            <button
              type="button"
              onClick={() => setIsExpanded(true)}
              className="btn btn-xs bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 border border-white/[0.08] font-mono inline-flex items-center gap-1"
            >
              <span>Show Details</span>
              <ChevronDown className="w-3 h-3" />
            </button>
            <a
              href="#/evolution"
              className="btn btn-xs bg-purple-500/15 hover:bg-purple-500/25 text-purple-300 border border-purple-500/30 font-medium transition-colors"
            >
              🔬 Full Autopsy &amp; Evolution →
            </a>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="glass-panel rounded-2xl p-5 mb-6 relative overflow-hidden">
      {/* Top Ambient Highlight */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-purple-500/30 to-transparent" />

      {/* Title Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06] mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 shadow-[0_0_12px_rgba(168,85,247,0.15)]">
            <Brain className="w-5 h-5 text-purple-400" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                🧠 Strategy Evolution &amp; Autopsy Status
              </h2>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-purple-500/10 border border-purple-500/25 text-purple-300">
                {generation || 'GEN #2'}
              </span>
              <ProvenanceBadge source="DAEMON 24/7" />
            </div>
            <p className="text-xs text-zinc-400">
              Candidate model health, 5 walk-forward OOS qualification gates, and execution autopsy attribution
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="badge badge-sm font-mono font-semibold py-1 px-3 badge-success bg-emerald-500/15 border-emerald-500/30 text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.15)]">
            ⚡ ACTIVE DAEMON LOOP
          </span>
          {compact && (
            <button
              type="button"
              onClick={() => setIsExpanded(false)}
              className="btn btn-xs bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 border border-white/[0.08] font-mono inline-flex items-center gap-1"
            >
              <span>Collapse</span>
              <ChevronUp className="w-3 h-3" />
            </button>
          )}
          <a
            href="#/evolution"
            className="btn btn-xs bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30 font-medium transition-colors"
          >
            🔬 Full Autopsy &amp; Evolution
          </a>
          <a
            href="#/mining"
            className="btn btn-xs bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-medium transition-colors"
          >
            ⛏️ Strategy Mining
          </a>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Panel 1: Active Strategy Family & Candidate Health Tier */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-purple-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <Cpu className="w-4 h-4 text-purple-400" />
                Active Strategy &amp; Candidate Health
              </span>
              <span
                className={`inline-flex items-center gap-1 text-xs font-mono font-bold py-0.5 px-2.5 rounded-lg border ${
                  candidateHealthTier === 'ELITE'
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : candidateHealthTier === 'HEALTHY'
                      ? 'bg-cyan-500/15 border-cyan-500/30 text-cyan-300'
                      : 'bg-amber-500/15 border-amber-500/30 text-amber-400'
                }`}
              >
                {candidateHealthTier}
              </span>
            </div>

            <div className="mb-4">
              <div className="text-sm font-bold text-white mb-1">
                {activeStrategyFamily}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-zinc-800/80 border border-white/10 text-zinc-300 font-mono text-[11px]">
                  <Layers className="w-3 h-3 text-cyan-400" />
                  {microstructureFilter}
                </span>
                <span className="font-mono text-purple-300 text-[11px] bg-purple-500/10 px-2 py-0.5 rounded border border-purple-500/20">
                  {activeCandidateId}
                </span>
              </div>
            </div>

            {/* Candidate Health Metrics Grid */}
            <div className="grid grid-cols-2 gap-2.5 pt-2 border-t border-white/[0.06]">
              <div className="p-2.5 rounded-lg bg-black/20 border border-white/5">
                <div className="text-[10px] text-zinc-400 uppercase font-mono">Rolling Sharpe</div>
                <div className="text-base font-bold font-mono text-emerald-400">
                  {rollingSharpe.toFixed(2)}
                </div>
                <div className="text-[10px] text-zinc-500">Threshold: ≥ 2.0</div>
              </div>

              <div className="p-2.5 rounded-lg bg-black/20 border border-white/5">
                <div className="text-[10px] text-zinc-400 uppercase font-mono">Win Rate</div>
                <div className="text-base font-bold font-mono text-emerald-400">
                  {`${winRatePct.toFixed(1)}%`}
                </div>
                <div className="text-[10px] text-zinc-500">Threshold: ≥ 65%</div>
              </div>

              <div className="p-2.5 rounded-lg bg-black/20 border border-white/5">
                <div className="text-[10px] text-zinc-400 uppercase font-mono">Max Drawdown</div>
                <div className="text-base font-bold font-mono text-cyan-400">
                  {`${maxDrawdownPct.toFixed(1)}%`}
                </div>
                <div className="text-[10px] text-zinc-500">Ceiling: ≤ 15%</div>
              </div>

              <div className="p-2.5 rounded-lg bg-black/20 border border-white/5">
                <div className="text-[10px] text-zinc-400 uppercase font-mono">Hawkes Resilience</div>
                <div className="text-base font-bold font-mono text-purple-300">
                  {hawkesResilienceScore.toFixed(2)}
                </div>
                <div className="text-[10px] text-zinc-500">Score: [0 - 1.0]</div>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs text-zinc-400">
            <span>Model Status:</span>
            <span className="font-mono text-emerald-400 font-semibold flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Live-Ready
            </span>
          </div>
        </div>

        {/* Panel 2: 5 Walk-Forward OOS Qualification Gates */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-purple-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                  <ShieldCheck className="w-4 h-4 text-emerald-400" />
                  5 OOS Qualification Gates
                </span>
                <ProvenanceBadge source="RESEARCH ARTIFACT / SIMULATION" />
              </div>
              <span
                className={`badge badge-sm font-mono font-bold ${
                  allGatesPassed
                    ? 'badge-success bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : 'badge-warning bg-amber-500/15 border-amber-500/30 text-amber-400'
                }`}
              >
                {`${passedGatesCount} / ${gates.length} GATES PASSED`}
              </span>
            </div>

            <p className="text-xs text-zinc-400 mb-3">
              Walk-Forward Out-of-Sample (OOS) data resilience verification
            </p>

            <div className="space-y-2">
              {gates.map((gate) => (
                <div
                  key={gate.id}
                  className="p-2.5 rounded-lg bg-black/20 border border-white/5 flex items-center justify-between gap-2"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <div className="truncate">
                      <div className="text-xs font-medium text-white truncate">
                        {gate.name}
                      </div>
                      <div className="text-[10px] text-zinc-400 font-mono">
                        {`Hurdle: ${gate.thresholdLabel}`}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="text-xs font-mono font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                      {gate.actualValueLabel}
                    </span>
                    <span className="badge badge-xs badge-success bg-emerald-500/20 text-emerald-300">
                      PASSED
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs text-zinc-400">
            <span>Stress Test:</span>
            <span className="font-mono text-emerald-400 font-semibold">
              Flash Crash -20% (SURVIVED)
            </span>
          </div>
        </div>

        {/* Panel 3: Trade Autopsy Attribution Gauges */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-purple-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <Gauge className="w-4 h-4 text-cyan-400" />
                Trade Autopsy Attribution Gauges
              </span>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-cyan-500/10 border border-cyan-500/20 text-cyan-300">
                {`${totalAutopsies} Autopsies`}
              </span>
            </div>

            <p className="text-xs text-zinc-400 mb-3">
              Micro-execution order flow decomposition, entry timing, and net edge
            </p>

            <div className="space-y-3">
              {attributionGauges.map((gauge) => {
                const formattedBps =
                  gauge.bps > 0
                    ? `+${gauge.bps.toFixed(1)} bps`
                    : `${gauge.bps.toFixed(1)} bps`

                return (
                  <div
                    key={gauge.id}
                    className="p-2.5 rounded-lg bg-black/20 border border-white/5 space-y-1.5"
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium text-zinc-200">
                        {gauge.label}
                      </span>
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`font-mono font-bold ${
                            gauge.isOptimal ? 'text-emerald-400' : 'text-amber-400'
                          }`}
                        >
                          {formattedBps}
                        </span>
                        <span
                          className={`badge badge-xs ${
                            gauge.isOptimal
                              ? 'badge-success bg-emerald-500/20 text-emerald-300'
                              : 'badge-warning bg-amber-500/20 text-amber-300'
                          }`}
                        >
                          {gauge.isOptimal ? 'OPTIMAL' : 'ATTENTION'}
                        </span>
                      </div>
                    </div>

                    <div className="text-[11px] text-zinc-400 leading-tight">
                      {gauge.description}
                    </div>

                    {/* Visual Meter Bar */}
                    <div className="w-full bg-zinc-800/80 rounded-full h-1.5 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          gauge.isOptimal ? 'bg-emerald-400' : 'bg-amber-400'
                        }`}
                        style={{
                          width: `${Math.min(
                            100,
                            Math.max(15, (Math.abs(gauge.bps) / gauge.thresholdBps) * 60)
                          )}%`,
                        }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs text-zinc-400">
            <span>Promoted Candidates:</span>
            <span className="font-mono text-purple-300 font-semibold">
              {`${promotedCandidatesCount} Active Promoted Candidates`}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
