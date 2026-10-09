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
  // 1. Penyelidikan & Model (Research & Modeling)
  {
    id: 'phase-250',
    phaseNumber: 'Fasa 250',
    title: 'Pencipta Hipotesis & Pendaftaran (Creator)',
    description: 'Pendaftaran strategi hipotesis kuantitatif dan kelayakan calon DAG.',
    route: '#/creator',
    category: 'research',
    categoryLabel: 'Penyelidikan & Model',
    badgeText: 'Hypothesis Registry',
  },
  {
    id: 'phase-253',
    phaseNumber: 'Fasa 253',
    title: 'Kesediaan & Latihan Model (Learner)',
    description: 'Pengesahan latihan model, semakan kualiti, dan metrik pembelajaran.',
    route: '#/learner',
    category: 'research',
    categoryLabel: 'Penyelidikan & Model',
    badgeText: 'Model Learning',
  },
  {
    id: 'phase-298',
    phaseNumber: 'Fasa 298',
    title: 'Perlombongan Strategi Kuantitatif (Mining)',
    description: 'Penjanaan hipotesis kuantitatif, penapisan OOS, dan pengesahan statistik.',
    route: '#/mining',
    category: 'research',
    categoryLabel: 'Penyelidikan & Model',
    badgeText: 'Hypothesis Mining',
  },
  {
    id: 'phase-304',
    phaseNumber: 'Fasa 304',
    title: 'Penentukuran Avellaneda-Stoikov (Calibration)',
    description: 'Adaptasi parameter pasaran mikrostruktur secara masa nyata.',
    route: '#/calibration',
    category: 'research',
    categoryLabel: 'Penyelidikan & Model',
    badgeText: 'Adaptive Parameters',
  },
  {
    id: 'phase-305',
    phaseNumber: 'Fasa 305',
    title: 'Ensembel Alfa Pelbagai Jangkamasa (Ensemble)',
    description: 'Pengadunan meta-dasar multi-horizon dan gabungan isyarat alfa.',
    route: '#/ensemble',
    category: 'research',
    categoryLabel: 'Penyelidikan & Model',
    badgeText: 'Alpha Blending',
  },
  {
    id: 'phase-306',
    phaseNumber: 'Fasa 306',
    title: 'Bedah Siasat Dagangan & Evolusi Kendiri (Evolution)',
    description: 'Gelung pembelajaran tertutup menganalisis kesilapan masa & kelebihan.',
    route: '#/evolution',
    category: 'research',
    categoryLabel: 'Penyelidikan & Model',
    badgeText: 'Self-Learning Loop',
  },

  // 2. Mikrostruktur & Pasaran (Microstructure & Market)
  {
    id: 'phase-291',
    phaseNumber: 'Fasa 291',
    title: 'Kaskad Hawkes & Teruja-Silang (Microstructure)',
    description: 'Analisis ketoksikan aliran pesanan, radius spektral ρ, dan intensiti lompatan.',
    route: '#/microstructure',
    category: 'microstructure',
    categoryLabel: 'Mikrostruktur & Pasaran',
    badgeText: 'Hawkes Cascades',
  },
  {
    id: 'phase-292',
    phaseNumber: 'Fasa 292',
    title: 'Kemasukan Pasaran Abadi Awam (Live Market)',
    description: 'Harga tanda langsung, kadar pembiayaan, dan status gerbang awam.',
    route: '#/market',
    category: 'microstructure',
    categoryLabel: 'Mikrostruktur & Pasaran',
    badgeText: 'Public Perpetuals',
  },
  {
    id: 'phase-302',
    phaseNumber: 'Fasa 302',
    title: 'Pertahanan Aliran Toksik (Execution Guard)',
    description: 'Pemintasan gelinciran harga (slippage) dan pemuliharaan kecairan.',
    route: '#/guard',
    category: 'microstructure',
    categoryLabel: 'Mikrostruktur & Pasaran',
    badgeText: 'Adverse Selection',
  },

  // 3. Pengurusan Risiko & Pelaksanaan (Execution & Risk)
  {
    id: 'phase-294',
    phaseNumber: 'Fasa 294',
    title: 'Kawalan Risiko & Pemutus Litar (Risk Controls)',
    description: 'Pendedahan bertingkat, pemutus litar automatik, dan interlock.',
    route: '#/risk',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Circuit Breakers',
  },
  {
    id: 'phase-295-exec',
    phaseNumber: 'Fasa 295A',
    title: 'Pelaksanaan Kertas & Pemotongan Pesanan (Paper Execution)',
    description: 'Pemadanan pasif simulasi, hirisan pesanan mikro, dan pengesahan.',
    route: '#/execution',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Passive Matching',
  },
  {
    id: 'phase-295-act',
    phaseNumber: 'Fasa 295B',
    title: 'Pengaktifan Strategi & Interlock Veto (Activation)',
    description: 'Promosi calon strategi dengan kuasa veto masa nyata.',
    route: '#/strategy-activation',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Veto Interlocks',
  },
  {
    id: 'phase-296',
    phaseNumber: 'Fasa 296',
    title: 'Daemon Kitar Hayat Autonomi 24/7 (Lifecycle)',
    description: 'Pemantauan daemon berterusan, degupan jantung, dan transisi.',
    route: '#/lifecycle',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Lifecycle Daemon',
  },
  {
    id: 'phase-297',
    phaseNumber: 'Fasa 297',
    title: 'Ketahanan Tekanan & Suntikan Ralat (Stress)',
    description: 'Ujian ketahanan kegagalan rangkaian dan perataan kecemasan.',
    route: '#/stress',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Fault Injection',
  },
  {
    id: 'phase-299',
    phaseNumber: 'Fasa 299',
    title: 'Penyusunan Semula Risiko Pariti (Portfolio)',
    description: 'Hawkes risk-parity portfolio rebalancing dan penularan risiko.',
    route: '#/portfolio',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Risk Parity',
  },
  {
    id: 'phase-300',
    phaseNumber: 'Fasa 300',
    title: 'Gerbang Dwi-Kustodi Berperingkat (Testnet Gateway)',
    description: 'Pemisahan kuasa tandatangan dan perlindungan kunci API.',
    route: '#/testnet',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Dual-Custody',
  },
  {
    id: 'phase-301',
    phaseNumber: 'Fasa 301',
    title: 'Kurungan Dinamik & Trailing Stop (Brackets)',
    description: 'Pengurusan trailing stop, high watermark ratchet, dan kedudukan.',
    route: '#/brackets',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Trailing Stops',
  },
  {
    id: 'phase-303',
    phaseNumber: 'Fasa 303',
    title: 'Pengaturcara Gelung Tertutup (Orchestrator)',
    description: 'Orkestrasi dagangan kertas dengan semakan bukti kriptografi.',
    route: '#/orchestrator',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Paper Orchestrator',
  },
  {
    id: 'phase-307',
    phaseNumber: 'Fasa 307',
    title: 'Jambatan REST & WebSocket Testnet (Bridge)',
    description: 'Pengesahan HMAC-SHA256, pengurusan listenKey, dan penstriman akaun.',
    route: '#/testnet-bridge',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Gateway Bridge',
  },
  {
    id: 'phase-308',
    phaseNumber: 'Fasa 308',
    title: 'Suis Pemati Berbilang Pihak (Kill Switch)',
    description: 'Kuorum berbilang tandatangan, panik perkakasan, dan penutupan segera.',
    route: '#/kill-switch',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Hardware Quorum',
  },
  {
    id: 'phase-309',
    phaseNumber: 'Fasa 309',
    title: 'Pelancaran Mikro-Modal Memandu Sendiri (Production Launch)',
    description: 'Pematuhan siling $5.00 USDT, lantai tunai 75%, dan sifar drift.',
    route: '#/production-launch',
    category: 'execution',
    categoryLabel: 'Pengurusan Risiko & Pelaksanaan',
    badgeText: 'Self-Driving $5.00',
  },

  // 4. Perakaunan & Asas Data (Accounting & Foundations)
  {
    id: 'phase-295-acc',
    phaseNumber: 'Fasa 295C',
    title: 'Lejar Perakaunan Catatan Bergu (Accounting)',
    description: 'Invarian matematik sifar drift |Δ| < 10⁻¹⁵ USDT merentas semua peralihan.',
    route: '#/accounting',
    category: 'accounting',
    categoryLabel: 'Perakaunan & Asas Data',
    badgeText: 'Zero-Drift Ledger',
  },
  {
    id: 'phase-foundation',
    phaseNumber: 'Asas',
    title: 'Identiti Set Data, DAG & Bukti Merkle (Overview)',
    description: 'Pemeriksaan komponen kline, pendaftaran set data, dan hash Merkle DAG.',
    route: '#/overview',
    category: 'accounting',
    categoryLabel: 'Perakaunan & Asas Data',
    badgeText: 'Dataset Foundations',
  },
]

export interface ResearchArchiveDrawerProps {
  isOpen: boolean
  onClose: () => void
  onSelectPhase: (route: string) => void
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
                  Arkib Penyelidikan (Research Archives)
                </h2>
                <span className="badge badge-sm badge-outline font-mono border-white/20 text-white/70">
                  23 Fasa Sejarah
                </span>
              </div>
              <p className="text-xs text-white/50">
                Pemeriksaan bukti kriptografi dan telemetri terperinci bagi fasa 250 hingga 309
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="btn btn-sm btn-circle btn-ghost text-white/70 hover:text-white"
            aria-label="Tutup arkib penyelidikan"
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
              placeholder="Cari fasa, kata kunci, algoritma atau metrik…"
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
                Padam
              </button>
            )}
          </div>

          <div className="flex items-center gap-1 overflow-x-auto pb-1 sm:pb-0">
            {[
              { id: 'ALL', label: 'Semua (23)' },
              { id: 'research', label: 'Model (6)' },
              { id: 'microstructure', label: 'Pasaran (3)' },
              { id: 'execution', label: 'Risiko (12)' },
              { id: 'accounting', label: 'Lejar (2)' },
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
              Tiada fasa penyelidikan sepadan dengan carian "{searchQuery}".
            </div>
          ) : (
            filteredPhases.map((phase) => (
              <div
                key={phase.id}
                onClick={() => {
                  onSelectPhase(phase.route)
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
                    Buka Halaman
                  </span>
                  <ChevronRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.06] bg-black/40 flex items-center justify-between text-xs text-white/60 font-mono">
          <span>Semua bukti kriptografi DAG &amp; audit dikekalkan</span>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-xs btn-outline border-white/20 text-white/70 hover:text-white rounded-lg"
          >
            Tutup Arkib
          </button>
        </div>
      </div>
    </div>
  )
}
