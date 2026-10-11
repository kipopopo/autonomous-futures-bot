import { useMemo, useState } from 'react'
import {
  Archive,
  ChevronRight,
  Search,
  X,
} from 'lucide-react'

export interface ArchivePhaseItem {
  id: string
  phaseNumber: string
  title: string
  description: string
  route: string
  category: 'research' | 'microstructure' | 'execution' | 'accounting'
  categoryLabel: string
  badgeText: string
}

export const ARCHIVE_PHASES: ArchivePhaseItem[] = [
  // 1. Research & Modeling
  {
    id: 'phase-250',
    phaseNumber: 'Phase 250',
    title: 'Hypothesis Creator & Registry (Creator)',
    description: 'Quantitative hypothesis strategy registry and DAG candidate eligibility.',
    route: '#/creator',
    category: 'research',
    categoryLabel: 'Research & Modeling',
    badgeText: 'Hypothesis Registry',
  },
  {
    id: 'phase-253',
    phaseNumber: 'Phase 253',
    title: 'Model Readiness & Training (Learner)',
    description: 'Model training verification, quality checks, and learning metrics.',
    route: '#/learner',
    category: 'research',
    categoryLabel: 'Research & Modeling',
    badgeText: 'Model Learning',
  },
  {
    id: 'phase-298',
    phaseNumber: 'Phase 298',
    title: 'Quantitative Strategy Mining (Mining)',
    description: 'Quantitative hypothesis generation, OOS filtering, and statistical validation.',
    route: '#/mining',
    category: 'research',
    categoryLabel: 'Research & Modeling',
    badgeText: 'Hypothesis Mining',
  },
  {
    id: 'phase-304',
    phaseNumber: 'Phase 304',
    title: 'Avellaneda-Stoikov Calibration (Calibration)',
    description: 'Real-time market microstructure parameter adaptation.',
    route: '#/calibration',
    category: 'research',
    categoryLabel: 'Research & Modeling',
    badgeText: 'Adaptive Parameters',
  },
  {
    id: 'phase-305',
    phaseNumber: 'Phase 305',
    title: 'Multi-Horizon Alpha Ensemble (Ensemble)',
    description: 'Multi-horizon meta-policy blending and alpha signal combination.',
    route: '#/ensemble',
    category: 'research',
    categoryLabel: 'Research & Modeling',
    badgeText: 'Alpha Blending',
  },
  {
    id: 'phase-306',
    phaseNumber: 'Phase 306',
    title: 'Trade Autopsy & Self-Evolution (Evolution)',
    description: 'Closed-loop self-learning analyzing timing error and execution edge.',
    route: '#/evolution',
    category: 'research',
    categoryLabel: 'Research & Modeling',
    badgeText: 'Self-Learning Loop',
  },

  // 2. Microstructure & Markets
  {
    id: 'phase-291',
    phaseNumber: 'Phase 291',
    title: 'Hawkes Cascades & Cross-Excitation (Microstructure)',
    description: 'Order flow toxicity analysis, spectral radius ρ, and jump intensities.',
    route: '#/microstructure',
    category: 'microstructure',
    categoryLabel: 'Microstructure & Markets',
    badgeText: 'Hawkes Cascades',
  },
  {
    id: 'phase-292',
    phaseNumber: 'Phase 292',
    title: 'Public Perpetuals Market Ingress (Live Market)',
    description: 'Real-time mark prices, funding rates, and public gateway telemetry.',
    route: '#/market',
    category: 'microstructure',
    categoryLabel: 'Microstructure & Markets',
    badgeText: 'Public Perpetuals',
  },
  {
    id: 'phase-302',
    phaseNumber: 'Phase 302',
    title: 'Toxic Flow Defense (Execution Guard)',
    description: 'Price slippage interception and liquidity preservation.',
    route: '#/guard',
    category: 'microstructure',
    categoryLabel: 'Microstructure & Markets',
    badgeText: 'Adverse Selection',
  },

  // 3. Execution & Risk Controls
  {
    id: 'phase-294',
    phaseNumber: 'Phase 294',
    title: 'Risk Controls & Circuit Breakers (Risk Controls)',
    description: 'Tiered exposure limits, automated circuit breakers, and interlocks.',
    route: '#/risk',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Circuit Breakers',
  },
  {
    id: 'phase-295-exec',
    phaseNumber: 'Phase 295A',
    title: 'Paper Execution & Order Slicing (Paper Execution)',
    description: 'Simulated passive matching, micro order slicing, and validation.',
    route: '#/execution',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Passive Matching',
  },
  {
    id: 'phase-295-act',
    phaseNumber: 'Phase 295B',
    title: 'Strategy Activation & Veto Interlocks (Activation)',
    description: 'Candidate strategy promotion with real-time veto authority.',
    route: '#/strategy-activation',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Veto Interlocks',
  },
  {
    id: 'phase-296',
    phaseNumber: 'Phase 296',
    title: 'Autonomous 24/7 Lifecycle Daemon (Lifecycle)',
    description: 'Continuous daemon supervision, heartbeats, and state transitions.',
    route: '#/lifecycle',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Lifecycle Daemon',
  },
  {
    id: 'phase-297',
    phaseNumber: 'Phase 297',
    title: 'Stress Resilience & Fault Injection (Stress)',
    description: 'Network disruption stress testing and emergency position flattening.',
    route: '#/stress',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Fault Injection',
  },
  {
    id: 'phase-299',
    phaseNumber: 'Phase 299',
    title: 'Risk Parity Rebalancing (Portfolio)',
    description: 'Hawkes risk-parity portfolio rebalancing and risk contagion mitigation.',
    route: '#/portfolio',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Risk Parity',
  },
  {
    id: 'phase-300',
    phaseNumber: 'Phase 300',
    title: 'Tiered Dual-Custody Gateway (Testnet Gateway)',
    description: 'Signing authority segregation and API key protection.',
    route: '#/testnet',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Dual-Custody',
  },
  {
    id: 'phase-301',
    phaseNumber: 'Phase 301',
    title: 'Dynamic Trailing Stop Brackets (Brackets)',
    description: 'Trailing stop governance, high-watermark ratchet, and position tracking.',
    route: '#/brackets',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Trailing Stops',
  },
  {
    id: 'phase-303',
    phaseNumber: 'Phase 303',
    title: 'Closed-Loop Orchestrator (Orchestrator)',
    description: 'Paper trading orchestration with cryptographic proof verification.',
    route: '#/orchestrator',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Paper Orchestrator',
  },
  {
    id: 'phase-307',
    phaseNumber: 'Phase 307',
    title: 'Testnet REST & WebSocket Bridge (Bridge)',
    description: 'HMAC-SHA256 authentication, listenKey lifecycle, and account streams.',
    route: '#/testnet-bridge',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Gateway Bridge',
  },
  {
    id: 'phase-308',
    phaseNumber: 'Phase 308',
    title: 'Multi-Party Kill Switch (Kill Switch)',
    description: 'Multi-signature quorum, hardware panic switch, and immediate flattening.',
    route: '#/kill-switch',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Hardware Quorum',
  },
  {
    id: 'phase-309',
    phaseNumber: 'Phase 309',
    title: 'Self-Driving Micro-Capital Launch (Production Launch)',
    description: '$5.00 USDT ceiling compliance, 75% cash floor, and zero drift.',
    route: '#/production-launch',
    category: 'execution',
    categoryLabel: 'Execution & Risk Controls',
    badgeText: 'Self-Driving $5.00',
  },

  // 4. Accounting & Foundations
  {
    id: 'phase-295-acc',
    phaseNumber: 'Phase 295C',
    title: 'Double-Entry Accounting Ledger (Accounting)',
    description: 'Mathematical zero-drift invariant |Δ| < 10⁻¹⁵ USDT across all state transitions.',
    route: '#/accounting',
    category: 'accounting',
    categoryLabel: 'Accounting & Foundations',
    badgeText: 'Zero-Drift Ledger',
  },
  {
    id: 'phase-foundation',
    phaseNumber: 'Foundations',
    title: 'Dataset Identity, DAG & Merkle Proofs (Overview)',
    description: 'Kline component inspection, dataset registration, and Merkle DAG hashes.',
    route: '#/overview',
    category: 'accounting',
    categoryLabel: 'Accounting & Foundations',
    badgeText: 'Dataset Foundations',
  },
]

export interface ResearchArchiveDrawerProps {
  isOpen: boolean
  onClose: () => void
  onSelectPhase?: (route: string) => void
}

export function ResearchArchiveDrawer({
  isOpen,
  onClose,
  onSelectPhase,
}: ResearchArchiveDrawerProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL')

  const filteredPhases = useMemo(() => {
    return ARCHIVE_PHASES.filter((phase) => {
      const matchesSearch =
        searchQuery === '' ||
        phase.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        phase.phaseNumber.toLowerCase().includes(searchQuery.toLowerCase()) ||
        phase.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        phase.badgeText.toLowerCase().includes(searchQuery.toLowerCase())

      const matchesCat =
        selectedCategory === 'ALL' || phase.category === selectedCategory

      return matchesSearch && matchesCat
    })
  }, [searchQuery, selectedCategory])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-end bg-black/80 backdrop-blur-md transition-all"
      role="dialog"
      aria-modal="true"
      aria-labelledby="archive-drawer-title"
    >
      {/* Click outside backdrop to close */}
      <div className="absolute inset-0" onClick={onClose} aria-hidden="true" />

      {/* Drawer Container */}
      <div className="relative w-full max-w-2xl h-full bg-[#0a0c12]/95 border-l border-white/[0.08] shadow-2xl flex flex-col z-10 animate-in slide-in-from-right duration-300">
        {/* Top ambient line */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />

        {/* Drawer Header */}
        <div className="p-5 border-b border-white/[0.06] flex items-center justify-between bg-black/40">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
              <Archive className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2
                  id="archive-drawer-title"
                  className="text-lg font-bold tracking-tight text-white"
                >
                  Research Archives
                </h2>
                <span className="badge badge-sm badge-outline font-mono border-white/20 text-white/70">
                  23 Historical Phases
                </span>
              </div>
              <p className="text-xs text-white/50">
                Cryptographic verification proofs and granular telemetry for Phases 250 through 309
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="btn btn-sm btn-circle btn-ghost text-white/70 hover:text-white"
            aria-label="Close research archives"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search & Filter Bar */}
        <div className="p-4 border-b border-white/[0.06] bg-black/30 flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-white/40 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search phases, keywords, algorithms, or metrics…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input input-sm w-full pl-9 font-mono text-xs rounded-xl bg-black/40 border border-white/[0.08] focus:border-cyan-500/50 text-white placeholder-white/30"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-white/40 hover:text-white"
              >
                Clear
              </button>
            )}
          </div>

          <div className="flex items-center gap-1 overflow-x-auto pb-1 sm:pb-0">
            {[
              { id: 'ALL', label: 'All (23)' },
              { id: 'research', label: 'Modeling (6)' },
              { id: 'microstructure', label: 'Markets (3)' },
              { id: 'execution', label: 'Execution & Risk (12)' },
              { id: 'accounting', label: 'Accounting (2)' },
            ].map((cat) => (
              <button
                key={cat.id}
                type="button"
                onClick={() => setSelectedCategory(cat.id)}
                className={`px-2.5 py-1 rounded-lg text-xs font-mono font-medium whitespace-nowrap transition-all ${
                  selectedCategory === cat.id
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                    : 'bg-white/[0.03] text-white/60 hover:text-white border border-white/[0.05]'
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>

        {/* List of Phases */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {filteredPhases.length === 0 ? (
            <div className="p-12 text-center text-xs text-white/40 font-mono">
              No research phases matched search query "{searchQuery}".
            </div>
          ) : (
            filteredPhases.map((phase) => (
              <div
                key={phase.id}
                onClick={() => {
                  onSelectPhase?.(phase.route)
                  onClose()
                }}
                className="group p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-cyan-500/40 hover:bg-white/[0.04] transition-all cursor-pointer flex items-center justify-between gap-3 shadow-xs"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className="badge badge-sm badge-neutral font-mono font-bold text-xs py-0.5 px-2 bg-black/60 border border-white/10 text-white">
                      {phase.phaseNumber}
                    </span>
                    <span className="text-xs font-mono font-semibold text-cyan-400">
                      {phase.badgeText}
                    </span>
                    <span className="text-[10px] text-white/40 font-mono">
                      · {phase.categoryLabel}
                    </span>
                  </div>

                  <h3 className="text-sm font-bold text-white truncate group-hover:text-cyan-300 transition-colors">
                    {phase.title}
                  </h3>

                  <p className="text-xs text-white/60 line-clamp-2 mt-0.5 leading-relaxed">
                    {phase.description}
                  </p>
                </div>

                <div className="flex items-center gap-2 text-white/30 group-hover:text-cyan-400 transition-colors shrink-0">
                  <span className="text-[11px] font-mono font-semibold hidden sm:inline">
                    Open Phase
                  </span>
                  <ChevronRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.06] bg-black/40 flex items-center justify-between text-xs text-white/60 font-mono">
          <span>All cryptographic DAG &amp; audit trail proofs preserved</span>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-xs btn-outline border-white/20 text-white/70 hover:text-white rounded-lg"
          >
            Close Archive
          </button>
        </div>
      </div>
    </div>
  )
}
