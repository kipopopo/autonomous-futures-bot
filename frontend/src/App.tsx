import { Component, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  LockKeyhole,
  Menu,
  Radio,
  Receipt,
  RefreshCw,
  ShieldCheck,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react'

import { ExecutiveDashboard } from '@/components/mission-control/executive-dashboard'
import { buildExecutiveDashboardModel } from '@/components/mission-control/adapter'
import { ExecutivePositionsPage } from '@/components/executive-positions-page'
import { ExecutiveTradesPage } from '@/components/executive-trades-page'
import { ExecutiveSafetyPage } from '@/components/executive-safety-page'
import { ResearchArchiveDrawer } from '@/components/mission-control/research-archive-drawer'

import { AccountingPage } from '@/components/accounting-page'
import { CreatorPage } from '@/components/creator-page'
import { ExecutionPage } from '@/components/execution-page'
import { LearnerPage } from '@/components/learner-page'
import { LifecyclePage } from '@/components/lifecycle-page'
import { LiveMarketPage } from '@/components/live-market-page'
import { MicrostructurePage } from '@/components/microstructure-page'
import { RiskPage } from '@/components/risk-page'
import { StrategyActivationPage } from '@/components/strategy-activation-page'
import { StressPage } from '@/components/stress-page'
import { StrategyMiningPage } from '@/components/strategy-mining-page'
import { PortfolioRebalancingPage } from '@/components/portfolio-rebalancing-page'
import { TestnetGatewayPage } from '@/components/testnet-gateway-page'
import { BracketPositionsPage } from '@/components/bracket-positions-page'
import { ExecutionGuardPage } from '@/components/execution-guard-page'
import { OrchestratorPage } from '@/components/orchestrator-page'
import { CalibrationPage } from '@/components/calibration-page'
import { EnsemblePage } from '@/components/ensemble-page'
import { EvolutionPage } from '@/components/evolution-page'
import { TestnetBridgePage } from '@/components/testnet-bridge-page'
import { KillSwitchPage } from '@/components/kill-switch-page'
import { ProductionLaunchPage } from '@/components/production-launch-page'
import { fetchCanaryDashboardData, fetchOverviewData } from '@/lib/api'
import { useTelemetryWebSocket, type ConnectionStatus } from '@/lib/websocket'
import {
  buildAccountingModel,
  buildAutoEvolutionModel,
  buildAutonomousLifecycleModel,
  buildBracketPositionsModel,
  buildCalibrationModel,
  buildEnsembleModel,
  buildExecutionGuardModel,
  buildLiveMarketModel,
  buildMicrostructureModel,
  buildOrchestratorModel,
  buildPaperExecutionModel,
  buildPortfolioRebalancingModel,
  buildRiskModel,
  buildStrategyActivationModel,
  buildStrategyMiningModel,
  buildStressFaultInjectionModel,
  buildTestnetGatewayModel,
  buildTestnetBridgeModel,
  buildKillSwitchModel,
  buildProductionLaunchModel,
  type CanaryDashboardData,
} from '@/lib/canary'
import { buildCreatorModel } from '@/lib/creator'
import { buildLearnerModel } from '@/lib/learner'
import { buildQualificationModel } from '@/lib/qualification'
import {
  buildOverviewModel,
  type DashboardApiData,
  type OverviewModel,
} from '@/lib/dashboard'
import { pageFromHash, isArchivePage, type DashboardPage } from '@/lib/navigation'
import './App.css'

const EMPTY_API_DATA: DashboardApiData = {
  health: null,
  bundle: null,
  components: null,
}

const EMPTY_CANARY_DATA: CanaryDashboardData = {
  summary: null,
  hawkes: null,
  risk: null,
  accounting: null,
  liveMarket: null,
  paperExecution: null,
  strategyActivation: null,
  autonomousLifecycle: null,
  stressFaultInjection: null,
  strategyMining: null,
  portfolioRebalancing: null,
  testnetGateway: null,
  bracketPositions: null,
  executionGuard: null,
  orchestrator: null,
  calibration: null,
  ensemble: null,
  evolution: null,
  testnetBridge: null,
  killSwitch: null,
  productionLaunch: null,
  error: null,
}

type LoadState = 'loading' | 'ready' | 'error'

function formatMyt(value: string | Date | null): string {
  if (!value) return '—'
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-MY', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kuala_Lumpur',
    timeZoneName: 'short',
  }).format(date)
}

function statusFor(state: LoadState, model: OverviewModel, hasCanary: boolean): {
  label: string
  tone: 'verified' | 'warning' | 'error'
  icon: LucideIcon
} {
  if (state === 'loading') return { label: 'VERIFYING TELEMETRY', tone: 'warning', icon: Clock3 }
  if (model.verification === 'verified' || hasCanary) {
    return { label: 'VERIFIED', tone: 'verified', icon: CheckCircle2 }
  }
  return { label: 'NO VERIFIED DATA', tone: 'error', icon: AlertTriangle }
}

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: unknown) {
    console.error('ErrorBoundary caught rendering error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <section className="alert alert-error shadow-xl my-6">
          <AlertTriangle className="h-6 w-6" />
          <div>
            <h3 className="font-bold text-base">Rendering Notice</h3>
            <p className="text-xs opacity-90">
              {this.state.error?.message || 'An unexpected rendering error occurred.'}
            </p>
          </div>
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            Retry
          </button>
        </section>
      )
    }
    return this.props.children
  }
}

function SafetyRail({
  state,
  model,
  hasCanary,
  telemetryStatus,
}: {
  state: LoadState
  model: OverviewModel
  hasCanary: boolean
  telemetryStatus?: ConnectionStatus
}) {
  const status = statusFor(state, model, hasCanary)
  const StatusIcon = status.icon
  return (
    <section className="flex flex-wrap items-center justify-between gap-3 p-3.5 mb-6 rounded-2xl bg-base-200 border border-base-300 shadow-sm" aria-label="Safety and verification status">
      <div className="flex flex-wrap items-center gap-2">
        <div className="badge badge-success gap-1.5 py-3 px-3 font-semibold text-xs tracking-wide">
          <ShieldCheck size={15} aria-hidden="true" />
          <span>PAPER-SAFE</span>
        </div>
        <div className="badge badge-info gap-1.5 py-3 px-3 font-semibold text-xs tracking-wide">
          <LockKeyhole size={14} aria-hidden="true" />
          <span>READ-ONLY</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        {telemetryStatus === 'STREAMING' ? (
          <div className="badge badge-success gap-1.5 py-3 px-3 font-semibold text-xs tracking-wide shadow-sm">
            <Radio size={14} className="animate-pulse" aria-hidden="true" />
            <span>STREAMING</span>
          </div>
        ) : telemetryStatus === 'RECONNECTING' ? (
          <div className="badge badge-warning gap-1.5 py-3 px-3 font-semibold text-xs tracking-wide shadow-sm">
            <RefreshCw size={14} className="animate-spin" aria-hidden="true" />
            <span>RECONNECTING</span>
          </div>
        ) : (
          <div className="badge badge-ghost opacity-60 gap-1.5 py-3 px-3 font-semibold text-xs tracking-wide">
            <Radio size={14} aria-hidden="true" />
            <span>DISCONNECTED</span>
          </div>
        )}
        <div
          className={`badge ${
            status.tone === 'verified'
              ? 'badge-success'
              : status.tone === 'warning'
                ? 'badge-warning'
                : 'badge-error'
          } gap-1.5 py-3 px-3 font-semibold text-xs`}
          aria-live="polite"
        >
          <StatusIcon size={14} aria-hidden="true" />
          <span>{status.label}</span>
        </div>
        <div className="badge badge-outline badge-error font-mono text-[11px] font-bold tracking-wider py-3 px-3">
          EXECUTION AUTHORITY: OFF
        </div>
      </div>
    </section>
  )
}

function App() {
  const telemetry = useTelemetryWebSocket()
  const [page, setPage] = useState<DashboardPage>(() => (
    typeof window === 'undefined' ? 'overview' : pageFromHash(window.location.hash)
  ))
  const [state, setState] = useState<LoadState>('loading')
  const [apiData, setApiData] = useState<DashboardApiData>(EMPTY_API_DATA)
  const [canaryData, setCanaryData] = useState<CanaryDashboardData>(EMPTY_CANARY_DATA)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null)

  const model = useMemo(() => buildOverviewModel(apiData), [apiData])
  const creatorModel = useMemo(() => buildCreatorModel(apiData), [apiData])
  const qualificationModel = useMemo(() => buildQualificationModel(apiData), [apiData])
  const learnerModel = useMemo(() => buildLearnerModel(apiData), [apiData])
  const microstructureModel = useMemo(() => buildMicrostructureModel(canaryData.hawkes), [canaryData.hawkes])
  const riskModel = useMemo(() => buildRiskModel(canaryData.risk), [canaryData.risk])
  const accountingModel = useMemo(() => buildAccountingModel(canaryData.accounting), [canaryData.accounting])
  const liveMarketModel = useMemo(() => buildLiveMarketModel(canaryData.liveMarket), [canaryData.liveMarket])
  const paperExecutionModel = useMemo(
    () => buildPaperExecutionModel(canaryData.paperExecution ?? null),
    [canaryData.paperExecution]
  )
  const strategyActivationModel = useMemo(
    () => buildStrategyActivationModel(canaryData.strategyActivation ?? null),
    [canaryData.strategyActivation]
  )
  const autonomousLifecycleModel = useMemo(
    () => buildAutonomousLifecycleModel(canaryData.autonomousLifecycle ?? null),
    [canaryData.autonomousLifecycle]
  )
  const stressModel = useMemo(
    () => buildStressFaultInjectionModel(canaryData.stressFaultInjection ?? null),
    [canaryData.stressFaultInjection]
  )
  const strategyMiningModel = useMemo(
    () => buildStrategyMiningModel(canaryData.strategyMining ?? null),
    [canaryData.strategyMining]
  )
  const portfolioRebalancingModel = useMemo(
    () => buildPortfolioRebalancingModel(canaryData.portfolioRebalancing ?? null),
    [canaryData.portfolioRebalancing]
  )
  const testnetGatewayModel = useMemo(
    () => buildTestnetGatewayModel(canaryData.testnetGateway ?? null),
    [canaryData.testnetGateway]
  )
  const bracketPositionsModel = useMemo(
    () => buildBracketPositionsModel(canaryData.bracketPositions ?? null),
    [canaryData.bracketPositions]
  )
  const executionGuardModel = useMemo(
    () => buildExecutionGuardModel(canaryData.executionGuard ?? null),
    [canaryData.executionGuard]
  )
  const orchestratorModel = useMemo(
    () => buildOrchestratorModel(canaryData.orchestrator ?? null),
    [canaryData.orchestrator]
  )
  const calibrationModel = useMemo(
    () => buildCalibrationModel(canaryData.calibration ?? null),
    [canaryData.calibration]
  )
  const ensembleModel = useMemo(
    () => buildEnsembleModel(canaryData.ensemble ?? null),
    [canaryData.ensemble]
  )
  const autoEvolutionModel = useMemo(
    () => buildAutoEvolutionModel(canaryData.evolution ?? null),
    [canaryData.evolution]
  )
  const testnetBridgeModel = useMemo(
    () => buildTestnetBridgeModel(canaryData.testnetBridge ?? null),
    [canaryData.testnetBridge]
  )
  const killSwitchModel = useMemo(
    () => buildKillSwitchModel(canaryData.killSwitch ?? null),
    [canaryData.killSwitch]
  )
  const productionLaunchModel = useMemo(
    () => buildProductionLaunchModel(canaryData.productionLaunch ?? null),
    [canaryData.productionLaunch]
  )

  const [isArchiveDrawerOpen, setIsArchiveDrawerOpen] = useState(false)
  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false)

  const executiveModel = useMemo(
    () =>
      buildExecutiveDashboardModel(
        productionLaunchModel,
        liveMarketModel,
        bracketPositionsModel,
        microstructureModel,
        telemetry,
        lastFetchedAt,
      ),
    [
      productionLaunchModel,
      liveMarketModel,
      bracketPositionsModel,
      microstructureModel,
      telemetry,
      lastFetchedAt,
    ],
  )

  const loadData = useCallback(async () => {
    setState('loading')
    setErrorMessage(null)
    const [overviewResult, canaryResult] = await Promise.allSettled([
      fetchOverviewData(),
      fetchCanaryDashboardData(),
    ])
    const nextOverview = overviewResult.status === 'fulfilled' ? overviewResult.value : EMPTY_API_DATA
    const nextCanary = canaryResult.status === 'fulfilled' ? canaryResult.value : EMPTY_CANARY_DATA

    setApiData(nextOverview)
    setCanaryData(nextCanary)
    setLastFetchedAt(new Date())

    const hasData = Boolean(
      nextOverview.health?.status === 'ok' ||
      nextCanary.summary?.verified ||
      nextCanary.hawkes?.verified ||
      nextCanary.risk?.verified ||
      nextCanary.accounting?.verified ||
      nextCanary.liveMarket?.verified ||
      nextCanary.paperExecution?.verified ||
      nextCanary.strategyActivation?.verified ||
      nextCanary.autonomousLifecycle?.verified ||
      nextCanary.stressFaultInjection?.verified ||
      nextCanary.strategyMining?.verified ||
      nextCanary.portfolioRebalancing?.verified ||
      nextCanary.testnetGateway?.verified ||
      nextCanary.bracketPositions?.verified ||
      nextCanary.executionGuard?.verified ||
      nextCanary.orchestrator?.verified ||
      nextCanary.calibration?.verified ||
      nextCanary.ensemble?.verified ||
      nextCanary.evolution?.verified ||
      nextCanary.testnetBridge?.verified
    )

    if (hasData) {
      setState('ready')
    } else {
      setState('error')
      setErrorMessage(
        overviewResult.status === 'rejected'
          ? (overviewResult.reason instanceof Error ? overviewResult.reason.message : 'API unavailable')
          : 'No verified telemetry is currently active'
      )
    }
  }, [])

  useEffect(() => {
    let ignore = false
    void Promise.allSettled([fetchOverviewData(), fetchCanaryDashboardData()])
      .then(([overviewResult, canaryResult]) => {
        if (!ignore) {
          const nextOverview = overviewResult.status === 'fulfilled' ? overviewResult.value : EMPTY_API_DATA
          const nextCanary = canaryResult.status === 'fulfilled' ? canaryResult.value : EMPTY_CANARY_DATA

          setApiData(nextOverview)
          setCanaryData(nextCanary)
          setLastFetchedAt(new Date())

          const hasData = Boolean(
            nextOverview.health?.status === 'ok' ||
            nextCanary.summary?.verified ||
            nextCanary.hawkes?.verified ||
            nextCanary.risk?.verified ||
            nextCanary.accounting?.verified ||
            nextCanary.liveMarket?.verified ||
            nextCanary.paperExecution?.verified ||
            nextCanary.strategyActivation?.verified ||
            nextCanary.autonomousLifecycle?.verified ||
            nextCanary.stressFaultInjection?.verified ||
            nextCanary.strategyMining?.verified ||
            nextCanary.portfolioRebalancing?.verified ||
            nextCanary.testnetGateway?.verified ||
            nextCanary.bracketPositions?.verified ||
            nextCanary.executionGuard?.verified ||
            nextCanary.orchestrator?.verified ||
            nextCanary.calibration?.verified ||
            nextCanary.ensemble?.verified ||
            nextCanary.evolution?.verified
          )

          if (hasData) {
            setState('ready')
          } else {
            setState('error')
            setErrorMessage(
              overviewResult.status === 'rejected'
                ? (overviewResult.reason instanceof Error ? overviewResult.reason.message : 'API unavailable')
                : 'No verified telemetry is currently active'
            )
          }
        }
      })
    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => {
    const handleHashChange = () => setPage(pageFromHash(window.location.hash))
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  // Auto-refresh interval (10 seconds) for continuous live market pricing and telemetry
  useEffect(() => {
    const timer = setInterval(() => {
      void fetchCanaryDashboardData().then((nextCanary) => {
        if (nextCanary) {
          setCanaryData(nextCanary)
          setLastFetchedAt(new Date())
        }
      })
    }, 10000)
    return () => clearInterval(timer)
  }, [])

  const hasCanary = Boolean(
    canaryData.summary?.verified ||
    canaryData.hawkes?.verified ||
    canaryData.paperExecution?.verified ||
    canaryData.strategyActivation?.verified ||
    canaryData.autonomousLifecycle?.verified ||
    canaryData.stressFaultInjection?.verified ||
    canaryData.strategyMining?.verified ||
    canaryData.portfolioRebalancing?.verified ||
    canaryData.testnetGateway?.verified ||
    canaryData.bracketPositions?.verified ||
    canaryData.executionGuard?.verified ||
    canaryData.orchestrator?.verified ||
    canaryData.calibration?.verified ||
    canaryData.ensemble?.verified ||
    canaryData.evolution?.verified ||
    canaryData.testnetBridge?.verified ||
    canaryData.killSwitch?.verified ||
    canaryData.productionLaunch?.verified
  )
  const isOverviewPage = page === 'overview'
  const isPositionsPage = page === 'positions'
  const isTradesPage = page === 'trades'
  const isSafetyPage = page === 'safety'
  const isArchive = isArchivePage(page)

  const isMarketPage = page === 'market'
  const isCreatorPage = page === 'creator'
  const isLearnerPage = page === 'learner'
  const isMicrostructurePage = page === 'microstructure'
  const isRiskPage = page === 'risk'
  const isAccountingPage = page === 'accounting'
  const isExecutionPage = page === 'execution'
  const isActivationPage = page === 'strategy-activation'
  const isLifecyclePage = page === 'lifecycle'
  const isStressPage = page === 'stress'
  const isMiningPage = page === 'mining'
  const isPortfolioPage = page === 'portfolio'
  const isTestnetPage = page === 'testnet'
  const isBracketsPage = page === 'brackets'
  const isGuardPage = page === 'guard'
  const isOrchestratorPage = page === 'orchestrator'
  const isCalibrationPage = page === 'calibration'
  const isEnsemblePage = page === 'ensemble'
  const isEvolutionPage = page === 'evolution'
  const isTestnetBridgePage = page === 'testnet-bridge'
  const isKillSwitchPage = page === 'kill-switch'
  const isProductionPage = page === 'production' || page === 'production-launch'

  return (
    <div className="app-shell bg-transparent text-white min-h-screen">
      {/* Mobile Top Header (< 768px) */}
      <div className="md:hidden flex items-center justify-between p-3.5 bg-[#090b10]/90 backdrop-blur-xl border-b border-white/[0.06] sticky top-0 z-30">
        <div className="flex items-center gap-2.5">
          <div className="brand-mark w-8 h-8 text-xs font-bold" aria-hidden="true">AF</div>
          <div>
            <strong className="text-xs font-bold text-white block leading-tight">
              Autonomous Futures
            </strong>
            <span className="text-[10px] text-zinc-400 font-mono">
              Trading Mission Control
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="badge badge-success badge-xs py-1 px-2 font-mono font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
            ACTIVE 24/7
          </span>
          <button
            type="button"
            onClick={() => setIsMobileDrawerOpen(!isMobileDrawerOpen)}
            className="btn btn-xs btn-ghost btn-circle text-white/70 hover:text-white"
            aria-label="Toggle navigation menu"
          >
            {isMobileDrawerOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>

      {/* Mobile Slide-down Drawer Menu */}
      {isMobileDrawerOpen && (
        <div className="md:hidden p-4 bg-[#090b10]/95 backdrop-blur-2xl border-b border-white/[0.08] space-y-2 z-20 animate-in slide-in-from-top duration-200">
          <a
            href="#overview"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isOverviewPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            🚀 Dashboard Utama
          </a>
          <a
            href="#/positions"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isPositionsPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            📊 Pasaran &amp; Posisi
          </a>
          <a
            href="#/trades"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isTradesPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            ⚡ Log Perdagangan
          </a>
          <a
            href="#/safety"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isSafetyPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            🛡️ Kawalan Keselamatan
          </a>
          <button
            type="button"
            onClick={() => {
              setIsMobileDrawerOpen(false)
              setIsArchiveDrawerOpen(true)
            }}
            className="w-full text-left p-2.5 rounded-xl text-xs font-semibold text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-between"
          >
            <span>📁 Arkib Penyelidikan (23 Fasa)</span>
            <Archive size={15} />
          </button>
        </div>
      )}

      {/* Desktop Executive Sidebar */}
      <aside className="sidebar bg-[#090b10]/80 border-r border-white/[0.06] backdrop-blur-2xl" aria-label="Primary navigation">
        <div className="brand-mark" aria-hidden="true">AF</div>
        <div className="sidebar-brand">
          <strong className="text-sm font-bold text-white tracking-tight">Autonomous<br />Futures</strong>
          <span className="text-xs text-zinc-400 font-mono">Trading Mission Control</span>
        </div>

        <nav className="flex flex-col gap-1.5">
          <a
            className={`nav-item ${isOverviewPage ? 'nav-item-active' : ''}`}
            href="#overview"
            aria-current={isOverviewPage ? 'page' : undefined}
          >
            <Zap size={18} className="text-primary" aria-hidden="true" />
            <span className="font-semibold">🚀 Dashboard Utama</span>
          </a>
          <a
            className={`nav-item ${isPositionsPage ? 'nav-item-active' : ''}`}
            href="#/positions"
            aria-current={isPositionsPage ? 'page' : undefined}
          >
            <Radio size={18} className="text-cyan-400" aria-hidden="true" />
            <span className="font-semibold">📊 Pasaran &amp; Posisi</span>
          </a>
          <a
            className={`nav-item ${isTradesPage ? 'nav-item-active' : ''}`}
            href="#/trades"
            aria-current={isTradesPage ? 'page' : undefined}
          >
            <Receipt size={18} className="text-emerald-400" aria-hidden="true" />
            <span className="font-semibold">⚡ Log Perdagangan</span>
          </a>
          <a
            className={`nav-item ${isSafetyPage ? 'nav-item-active' : ''}`}
            href="#/safety"
            aria-current={isSafetyPage ? 'page' : undefined}
          >
            <ShieldCheck size={18} className="text-emerald-400" aria-hidden="true" />
            <span className="font-semibold">🛡️ Kawalan Keselamatan</span>
          </a>

          {/* Research Archive Trigger */}
          <div className="pt-3 mt-2 border-t border-base-300/80">
            <button
              type="button"
              onClick={() => setIsArchiveDrawerOpen(true)}
              className={`nav-item justify-between w-full text-left cursor-pointer ${
                isArchive ? 'nav-item-active' : ''
              }`}
            >
              <div className="flex items-center gap-2">
                <Archive size={17} className="text-primary" aria-hidden="true" />
                <span className="font-medium">📁 Arkib Penyelidikan</span>
              </div>
              <span className="badge badge-xs badge-primary font-mono py-1 px-1.5 font-bold">
                23 Fasa
              </span>
            </button>
          </div>
        </nav>

        <div className="sidebar-footer border-t border-base-300">
          <div className="flex items-center justify-between">
            <span className="sidebar-label font-mono">PHASE 311</span>
            <span className="badge badge-success badge-xs py-1.5 px-2 font-mono font-semibold">
              Mission Control
            </span>
          </div>
        </div>
      </aside>

      <main className="main-content" id="overview">
        {/* Archive Notice Bar when visiting historical phase */}
        {isArchive && (
          <div className="rounded-2xl bg-base-200/90 border border-primary/30 p-4 mb-6 shadow-md flex flex-wrap items-center justify-between gap-3 font-mono text-xs">
            <div className="flex items-center gap-2.5 text-base-content">
              <div className="p-2 rounded-xl bg-primary/10 text-primary">
                <Archive className="w-4 h-4" />
              </div>
              <div>
                <span className="font-bold text-primary block">
                  📁 Arkib Penyelidikan Sejarah ({page.toUpperCase()})
                </span>
                <span className="text-[11px] text-base-content/60">
                  Paparan fasa kajian terdahulu (Phases 250-309). Semua bukti kriptografi DAG &amp; lejar audit dikekalkan.
                </span>
              </div>
            </div>
            <a
              href="#overview"
              className="btn btn-sm btn-primary rounded-xl gap-1.5 font-semibold text-xs shadow-sm"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Kembali ke Dashboard Utama</span>
            </a>
          </div>
        )}

        {/* Page Header (Only for Historical Archive Pages) */}
        {isArchive && (
          <header className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-base-300 mb-6">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
                Autonomous Futures / Arkib Penyelidikan / {page}
              </p>
              <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight mt-1 text-base-content">
                {isProductionPage
                  ? 'Canary Production: Live Production Launch & Micro-Capital Self-Driving'
                  : isKillSwitchPage
                  ? 'Canary Kill-Switch: Capital Safety Governance & Quorum Panic'
                  : isTestnetBridgePage
                  ? 'Canary Testnet Bridge: Live API Integration & Solvency Ledger'
                  : isEvolutionPage
                  ? 'Canary Evolution: Strategy Autopsy & Self-Learning Daemon'
                  : isEnsemblePage
                  ? 'Canary Ensemble: Multi-Horizon Alpha Blending Engine'
                  : isCalibrationPage
                  ? 'Canary Calibration: Self-Calibrating Parameter Adaptation'
                  : isOrchestratorPage
                  ? 'Canary Orchestrator: Closed-Loop Paper Trading Orchestrator'
                  : isGuardPage
                  ? 'Canary Adverse Selection Guard: Toxic Flow Defense'
                  : isBracketsPage
                  ? 'Canary Bracket Orders & Positions: Dynamic Trailing Stops'
                  : isTestnetPage
                  ? 'Canary Testnet Gateway: Dual-Custody Pre-Dispatch Filters'
                  : isPortfolioPage
                  ? 'Canary Portfolio Rebalancing: Hawkes Risk-Parity Engine'
                  : isMiningPage
                  ? 'Canary Strategy Mining: Hypothesis Formulation & OOS'
                  : isStressPage
                  ? 'Canary Stress Resilience: Fault Injection & Flattening'
                  : isLifecyclePage
                  ? 'Canary Mission Control: 24/7 Lifecycle Daemon'
                  : isMarketPage
                  ? 'Live Market Ingress: Public Perpetuals Depth'
                  : isCreatorPage
                  ? 'Creator: Quantitative Hypothesis Registry'
                  : isLearnerPage
                  ? 'Learner: Model Learning Readiness'
                  : isMicrostructurePage
                  ? 'Microstructure: Hawkes Cascades & Execution Hazard'
                  : isRiskPage
                  ? 'Risk Controls: Stepped Exposure & Circuit Breakers'
                  : isAccountingPage
                  ? 'Accounting Ledger: Double-Entry Mathematical Drift'
                  : isExecutionPage
                  ? 'Paper Execution: Passive Matching & Child Slicing'
                  : isActivationPage
                  ? 'Strategy Activation: Promoted Candidates & Veto Interlock'
                  : 'Overview'}
              </h1>
            </div>
            <button
              className="btn btn-primary btn-sm gap-2 shadow font-semibold"
              type="button"
              onClick={() => void loadData()}
              disabled={state === 'loading'}
            >
              <RefreshCw size={15} className={state === 'loading' ? 'animate-spin' : undefined} aria-hidden="true" />
              <span>{state === 'loading' ? 'Verifying…' : 'Refresh verified data'}</span>
            </button>
          </header>
        )}

        {/* Safety Rail for Archive Pages */}
        {isArchive && (
          <SafetyRail
            state={state}
            model={model}
            hasCanary={hasCanary}
            telemetryStatus={telemetry.status}
          />
        )}

        {errorMessage && (
          <div className="alert alert-warning shadow-lg mb-6" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <div>
              <strong className="block font-bold">Verification Notice</strong>
              <span className="text-sm opacity-90">{errorMessage}</span>
            </div>
          </div>
        )}

        {/* Executive Landing Page (Dashboard Utama - R1 to R4) */}
        {isOverviewPage && state === 'ready' && (
          <ExecutiveDashboard
            model={executiveModel}
            onRefresh={() => void loadData()}
            isLoading={false}
          />
        )}

        {state === 'loading' && (
          <section className="card bg-base-200 border border-base-300 shadow-xl p-8 text-center my-6" aria-live="polite">
            <div className="flex flex-col items-center justify-center gap-3">
              <span className="loading loading-ring loading-lg text-primary" aria-hidden="true" />
              <h2 className="text-lg font-bold">Menyelaras data &amp; telemetri langsung</h2>
              <p className="text-sm text-base-content/70 max-w-md">
                Menghubungkan ke perkhidmatan telemetri read-only bagi status kesihatan, baki lejar catatan bergu, dan isyarat strategi.
              </p>
            </div>
          </section>
        )}

        {state === 'error' && (
          <section className="alert alert-warning shadow-lg my-6" role="status">
            <AlertTriangle size={24} className="text-warning" aria-hidden="true" />
            <div>
              <h2 className="font-bold text-base">Tiada set data disahkan tersedia pada masa ini.</h2>
              <p className="text-sm opacity-80">Segar semula setelah API sedia ada diakses. Data yang belum disahkan kekal tersembunyi demi keselamatan.</p>
            </div>
          </section>
        )}

        <ErrorBoundary key={page}>
          {/* Executive Subpages (R5) */}
          {isPositionsPage && state === 'ready' && (
            <ExecutivePositionsPage
              positions={executiveModel.positions}
              bracketPositionsModel={bracketPositionsModel}
              liveMarketModel={liveMarketModel}
            />
          )}
          {isTradesPage && state === 'ready' && (
            <ExecutiveTradesPage orders={executiveModel.orders} />
          )}
          {isSafetyPage && state === 'ready' && (
            <ExecutiveSafetyPage
              productionLaunchModel={productionLaunchModel}
              riskModel={riskModel}
              killSwitchModel={killSwitchModel}
            />
          )}

          {/* Historical Canary Pages (Phases 250-309 Preserved in Full) */}
          {isMarketPage && state === 'ready' && <LiveMarketPage model={liveMarketModel} />}
          {isCreatorPage && state === 'ready' && <CreatorPage model={creatorModel} qualification={qualificationModel} />}
          {isLearnerPage && state === 'ready' && <LearnerPage model={learnerModel} />}
          {isMicrostructurePage && state === 'ready' && (
            <MicrostructurePage model={microstructureModel} telemetry={telemetry} />
          )}
          {isRiskPage && state === 'ready' && <RiskPage model={riskModel} />}
          {isAccountingPage && state === 'ready' && <AccountingPage model={accountingModel} />}
          {isExecutionPage && state === 'ready' && <ExecutionPage model={paperExecutionModel} />}
          {isActivationPage && state === 'ready' && <StrategyActivationPage model={strategyActivationModel} />}
          {isLifecyclePage && state === 'ready' && <LifecyclePage model={autonomousLifecycleModel} />}
          {isStressPage && state === 'ready' && <StressPage model={stressModel} />}
          {isMiningPage && state === 'ready' && <StrategyMiningPage model={strategyMiningModel} />}
          {isPortfolioPage && state === 'ready' && <PortfolioRebalancingPage model={portfolioRebalancingModel} />}
          {isTestnetPage && state === 'ready' && <TestnetGatewayPage model={testnetGatewayModel} />}
          {isBracketsPage && state === 'ready' && <BracketPositionsPage model={bracketPositionsModel} />}
          {isGuardPage && state === 'ready' && <ExecutionGuardPage model={executionGuardModel} />}
          {isOrchestratorPage && state === 'ready' && <OrchestratorPage model={orchestratorModel} />}
          {isCalibrationPage && state === 'ready' && <CalibrationPage model={calibrationModel} />}
          {isEnsemblePage && state === 'ready' && <EnsemblePage model={ensembleModel} />}
          {isEvolutionPage && state === 'ready' && <EvolutionPage model={autoEvolutionModel} />}
          {isTestnetBridgePage && state === 'ready' && <TestnetBridgePage model={testnetBridgeModel} />}
          {isKillSwitchPage && state === 'ready' && <KillSwitchPage model={killSwitchModel} />}
          {isProductionPage && state === 'ready' && <ProductionLaunchPage model={productionLaunchModel} />}
        </ErrorBoundary>

        <footer className="page-footer border-t border-base-300 mt-8 pt-4">
          <span className="text-xs text-base-content/60">Autonomous Futures Bot · Perdagangan Eksekutif 24/7 · PAPER-SAFE</span>
          <span className="text-xs font-mono text-base-content/60">{lastFetchedAt ? `Diselaraskan ${formatMyt(lastFetchedAt)}` : 'Diselaraskan —'}</span>
        </footer>
      </main>

      {/* Mobile Bottom Navigation Bar (< 768px) */}
      <nav className="mobile-bottom-nav md:hidden" aria-label="Mobile Navigation">
        <a
          href="#overview"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isOverviewPage ? 'text-primary font-bold' : 'text-base-content/60'
          }`}
        >
          <Zap size={18} />
          <span>Utama</span>
        </a>
        <a
          href="#/positions"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isPositionsPage ? 'text-cyan-400 font-bold' : 'text-base-content/60'
          }`}
        >
          <Radio size={18} />
          <span>Posisi</span>
        </a>
        <a
          href="#/trades"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isTradesPage ? 'text-emerald-400 font-bold' : 'text-base-content/60'
          }`}
        >
          <Receipt size={18} />
          <span>Log</span>
        </a>
        <a
          href="#/safety"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isSafetyPage ? 'text-emerald-400 font-bold' : 'text-base-content/60'
          }`}
        >
          <ShieldCheck size={18} />
          <span>Keselamatan</span>
        </a>
        <button
          type="button"
          onClick={() => setIsArchiveDrawerOpen(true)}
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isArchive ? 'text-primary font-bold' : 'text-base-content/60'
          }`}
        >
          <Archive size={18} />
          <span>Arkib</span>
        </button>
      </nav>

      {/* Collapsible Research Archive Drawer/Modal */}
      <ResearchArchiveDrawer
        isOpen={isArchiveDrawerOpen}
        onClose={() => setIsArchiveDrawerOpen(false)}
        onSelectPhase={(route) => {
          window.location.hash = route
          setIsArchiveDrawerOpen(false)
        }}
      />
    </div>
  )
}

export default App
