import React, { Component, Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  Brain,
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
import { PairDetailPage } from '@/components/pair-detail-page'
import { buildExecutiveDashboardModel } from '@/components/mission-control/adapter'
import { ExecutivePositionsPage } from '@/components/executive-positions-page'
import { ExecutiveTradesPage } from '@/components/executive-trades-page'
import { ExecutiveSafetyPage } from '@/components/executive-safety-page'
import { ResearchArchiveDrawer } from '@/components/mission-control/research-archive-drawer'
import { ProvenanceBadge } from '@/components/mission-control/provenance-badge'

import { EvolutionPage } from '@/components/evolution-page'

const AccountingPage = React.lazy(() => import('@/components/accounting-page').then((m) => ({ default: m.AccountingPage })))
const CreatorPage = React.lazy(() => import('@/components/creator-page').then((m) => ({ default: m.CreatorPage })))
const ExecutionPage = React.lazy(() => import('@/components/execution-page').then((m) => ({ default: m.ExecutionPage })))
const LearnerPage = React.lazy(() => import('@/components/learner-page').then((m) => ({ default: m.LearnerPage })))
const LifecyclePage = React.lazy(() => import('@/components/lifecycle-page').then((m) => ({ default: m.LifecyclePage })))
const LiveMarketPage = React.lazy(() => import('@/components/live-market-page').then((m) => ({ default: m.LiveMarketPage })))
const MicrostructurePage = React.lazy(() => import('@/components/microstructure-page').then((m) => ({ default: m.MicrostructurePage })))
const RiskPage = React.lazy(() => import('@/components/risk-page').then((m) => ({ default: m.RiskPage })))
const StrategyActivationPage = React.lazy(() => import('@/components/strategy-activation-page').then((m) => ({ default: m.StrategyActivationPage })))
const StressPage = React.lazy(() => import('@/components/stress-page').then((m) => ({ default: m.StressPage })))
const StrategyMiningPage = React.lazy(() => import('@/components/strategy-mining-page').then((m) => ({ default: m.StrategyMiningPage })))
const PortfolioRebalancingPage = React.lazy(() => import('@/components/portfolio-rebalancing-page').then((m) => ({ default: m.PortfolioRebalancingPage })))
const TestnetGatewayPage = React.lazy(() => import('@/components/testnet-gateway-page').then((m) => ({ default: m.TestnetGatewayPage })))
const BracketPositionsPage = React.lazy(() => import('@/components/bracket-positions-page').then((m) => ({ default: m.BracketPositionsPage })))
const ExecutionGuardPage = React.lazy(() => import('@/components/execution-guard-page').then((m) => ({ default: m.ExecutionGuardPage })))
const OrchestratorPage = React.lazy(() => import('@/components/orchestrator-page').then((m) => ({ default: m.OrchestratorPage })))
const CalibrationPage = React.lazy(() => import('@/components/calibration-page').then((m) => ({ default: m.CalibrationPage })))
const EnsemblePage = React.lazy(() => import('@/components/ensemble-page').then((m) => ({ default: m.EnsemblePage })))
const TestnetBridgePage = React.lazy(() => import('@/components/testnet-bridge-page').then((m) => ({ default: m.TestnetBridgePage })))
const KillSwitchPage = React.lazy(() => import('@/components/kill-switch-page').then((m) => ({ default: m.KillSwitchPage })))
const ProductionLaunchPage = React.lazy(() => import('@/components/production-launch-page').then((m) => ({ default: m.ProductionLaunchPage })))

import {
  fetchPrimaryTelemetry,
  fetchArchiveDataForPage,
  type LiveMarketPricesResponse,
} from '@/lib/api'
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
import { pageFromHash, isArchivePage, getPairSymbolFromHash, type DashboardPage } from '@/lib/navigation'
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
  executionStatus: null,
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
  const [currentPairSymbol, setCurrentPairSymbol] = useState<string>(() => (
    typeof window === 'undefined' ? 'SOLUSDT' : (getPairSymbolFromHash(window.location.hash) || 'SOLUSDT')
  ))
  const [state, setState] = useState<LoadState>('loading')
  const [apiData, setApiData] = useState<DashboardApiData>(EMPTY_API_DATA)
  const [canaryData, setCanaryData] = useState<CanaryDashboardData>(EMPTY_CANARY_DATA)
  const [liveMarketPrices, setLiveMarketPrices] = useState<LiveMarketPricesResponse | null>(null)
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
        autoEvolutionModel,
        strategyMiningModel,
        canaryData.executionStatus ?? null,
        liveMarketPrices?.btc_macro ?? null,
        null,
        liveMarketPrices,
      ),
    [
      productionLaunchModel,
      liveMarketModel,
      bracketPositionsModel,
      microstructureModel,
      telemetry,
      lastFetchedAt,
      autoEvolutionModel,
      strategyMiningModel,
      canaryData.executionStatus,
      liveMarketPrices?.btc_macro,
      liveMarketPrices,
    ],
  )

  const loadData = useCallback(async () => {
    setState('loading')
    setErrorMessage(null)

    const isArchive = isArchivePage(page)
    const isSafety = page === 'safety'

    const [telemetryResult, archiveResult] = await Promise.allSettled([
      fetchPrimaryTelemetry(),
      isArchive || isSafety ? fetchArchiveDataForPage(page) : Promise.resolve(null),
    ])

    let hasData = false

    if (telemetryResult.status === 'fulfilled' && telemetryResult.value) {
      const telemetry = telemetryResult.value
      setCanaryData((prev) => ({
        ...prev,
        executionStatus: telemetry.executionStatus ?? prev.executionStatus,
        evolution: telemetry.evolution ?? prev.evolution,
      }))
      if (telemetry.liveMarketPrices) {
        setLiveMarketPrices(telemetry.liveMarketPrices)
      }
      if (telemetry.executionStatus || telemetry.liveMarketPrices || telemetry.evolution) {
        hasData = true
      }
    }

    if (archiveResult.status === 'fulfilled' && archiveResult.value) {
      const archive = archiveResult.value
      if (archive.canary) {
        setCanaryData((prev) => ({ ...prev, ...archive.canary }))
      }
      if (archive.apiData) {
        setApiData((prev) => ({ ...prev, ...archive.apiData }))
      }
      hasData = true
    }

    setLastFetchedAt(new Date())

    if (hasData) {
      setState('ready')
    } else {
      setState('error')
      setErrorMessage(
        telemetryResult.status === 'rejected'
          ? (telemetryResult.reason instanceof Error ? telemetryResult.reason.message : 'API unavailable')
          : 'No verified telemetry is currently active'
      )
    }
  }, [page])

  useEffect(() => {
    let ignore = false
    const isArchive = isArchivePage(page)
    const isSafety = page === 'safety'

    void Promise.allSettled([
      fetchPrimaryTelemetry(),
      isArchive || isSafety ? fetchArchiveDataForPage(page) : Promise.resolve(null),
    ]).then(([telemetryResult, archiveResult]) => {
      if (!ignore) {
        let hasData = false

        if (telemetryResult.status === 'fulfilled' && telemetryResult.value) {
          const telemetry = telemetryResult.value
          setCanaryData((prev) => ({
            ...prev,
            executionStatus: telemetry.executionStatus ?? prev.executionStatus,
            evolution: telemetry.evolution ?? prev.evolution,
          }))
          if (telemetry.liveMarketPrices) {
            setLiveMarketPrices(telemetry.liveMarketPrices)
          }
          if (telemetry.executionStatus || telemetry.liveMarketPrices || telemetry.evolution) {
            hasData = true
          }
        }

        if (archiveResult.status === 'fulfilled' && archiveResult.value) {
          const archive = archiveResult.value
          if (archive.canary) {
            setCanaryData((prev) => ({ ...prev, ...archive.canary }))
          }
          if (archive.apiData) {
            setApiData((prev) => ({ ...prev, ...archive.apiData }))
          }
          hasData = true
        }

        setLastFetchedAt(new Date())

        if (hasData) {
          setState('ready')
        } else {
          setState('error')
          setErrorMessage(
            telemetryResult.status === 'rejected'
              ? (telemetryResult.reason instanceof Error ? telemetryResult.reason.message : 'API unavailable')
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
    const handleHashChange = () => {
      setPage(pageFromHash(window.location.hash))
      const sym = getPairSymbolFromHash(window.location.hash)
      if (sym) {
        setCurrentPairSymbol(sym)
      }
    }
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  // Auto-refresh interval (10 seconds) for continuous live market pricing and telemetry
  useEffect(() => {
    const timer = setInterval(() => {
      void fetchPrimaryTelemetry().then((telemetry) => {
        if (telemetry) {
          setCanaryData((prev) => ({
            ...prev,
            executionStatus: telemetry.executionStatus ?? prev.executionStatus,
            evolution: telemetry.evolution ?? prev.evolution,
          }))
          if (telemetry.liveMarketPrices) {
            setLiveMarketPrices(telemetry.liveMarketPrices)
          }
          setLastFetchedAt(new Date())
        }
      })
    }, 10000)
    return () => clearInterval(timer)
  }, [])

  // On-demand archive data fetch when navigating to an archive page or safety view
  useEffect(() => {
    if (isArchivePage(page) || page === 'safety') {
      void fetchArchiveDataForPage(page).then((result) => {
        if (result) {
          if (result.canary) {
            setCanaryData((prev) => ({ ...prev, ...result.canary }))
          }
          if (result.apiData) {
            setApiData((prev) => ({ ...prev, ...result.apiData }))
          }
          setState('ready')
        }
      })
    }
  }, [page])

  const hasCanary = Boolean(
    canaryData.executionStatus?.verified ||
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
  const isPairPage = page === 'pair'
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
            🚀 Executive Overview
          </a>
          <a
            href="#/positions"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isPositionsPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            📊 Live Positions &amp; Markets
          </a>
          <a
            href="#/trades"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isTradesPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            ⚡ Trade Log &amp; Executions
          </a>
          <a
            href="#/safety"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isSafetyPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            🛡️ Risk Controls &amp; Solvency
          </a>
          <a
            href="#/evolution"
            onClick={() => setIsMobileDrawerOpen(false)}
            className={`block p-2.5 rounded-xl text-xs font-semibold ${
              isEvolutionPage ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30' : 'text-zinc-300 hover:text-white'
            }`}
          >
            🧠 Strategy Evolution &amp; Autopsy
          </a>
          <button
            type="button"
            onClick={() => {
              setIsMobileDrawerOpen(false)
              setIsArchiveDrawerOpen(true)
            }}
            className="w-full text-left p-2.5 rounded-xl text-xs font-semibold text-cyan-400 bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-between"
          >
            <span>📁 Research Archives (23 Phases)</span>
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
            <span className="font-semibold">🚀 Executive Overview</span>
          </a>
          <a
            className={`nav-item ${isPositionsPage ? 'nav-item-active' : ''}`}
            href="#/positions"
            aria-current={isPositionsPage ? 'page' : undefined}
          >
            <Radio size={18} className="text-cyan-400" aria-hidden="true" />
            <span className="font-semibold">📊 Live Positions &amp; Markets</span>
          </a>
          <a
            className={`nav-item ${isTradesPage ? 'nav-item-active' : ''}`}
            href="#/trades"
            aria-current={isTradesPage ? 'page' : undefined}
          >
            <Receipt size={18} className="text-emerald-400" aria-hidden="true" />
            <span className="font-semibold">⚡ Trade Log &amp; Executions</span>
          </a>
          <a
            className={`nav-item ${isSafetyPage ? 'nav-item-active' : ''}`}
            href="#/safety"
            aria-current={isSafetyPage ? 'page' : undefined}
          >
            <ShieldCheck size={18} className="text-emerald-400" aria-hidden="true" />
            <span className="font-semibold">🛡️ Risk Controls &amp; Solvency</span>
          </a>
          <a
            className={`nav-item ${isEvolutionPage ? 'nav-item-active' : ''}`}
            href="#/evolution"
            aria-current={isEvolutionPage ? 'page' : undefined}
          >
            <Brain size={18} className="text-purple-400" aria-hidden="true" />
            <span className="font-semibold">🧠 Strategy Evolution &amp; Autopsy</span>
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
                <span className="font-medium">📁 Research Archives</span>
              </div>
              <span className="badge badge-xs badge-primary font-mono py-1 px-1.5 font-bold">
                23 Phases
              </span>
            </button>
          </div>
        </nav>

        <div className="sidebar-footer border-t border-base-300">
          <div className="flex items-center justify-between">
            <span className="sidebar-label font-mono">PHASE 314</span>
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
            <div className="flex items-center gap-2.5 text-base-content flex-wrap">
              <div className="p-2 rounded-xl bg-primary/10 text-primary">
                <Archive className="w-4 h-4" />
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-bold text-primary block">
                    📁 Historical Research Archive ({page.toUpperCase()})
                  </span>
                  <ProvenanceBadge source="RESEARCH ARTIFACT / SIMULATION" />
                </div>
                <span className="text-[11px] text-base-content/60">
                  Historical research phase view (Phases 250-309). All cryptographic DAG proofs &amp; audit ledgers preserved.
                </span>
              </div>
            </div>
            <a
              href="#overview"
              className="btn btn-sm btn-primary rounded-xl gap-1.5 font-semibold text-xs shadow-sm"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Return to Executive Overview</span>
            </a>
          </div>
        )}

        {/* Page Header (Only for Historical Archive Pages) */}
        {isArchive && (
          <header className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-base-300 mb-6">
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
                Autonomous Futures / Research Archives / {page}
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

        {/* Executive Landing Page (Executive Overview - Simplified & Streamlined) */}
        {isOverviewPage && state === 'ready' && (
          <ExecutiveDashboard
            model={executiveModel}
            onRefresh={() => void loadData()}
            isLoading={false}
            onSelectPair={(sym) => {
              setCurrentPairSymbol(sym)
              window.location.hash = `#/pair/${sym}`
            }}
          />
        )}

        {state === 'loading' && (
          <section className="card bg-base-200 border border-base-300 shadow-xl p-8 text-center my-6" aria-live="polite">
            <div className="flex flex-col items-center justify-center gap-3">
              <span className="loading loading-ring loading-lg text-primary" aria-hidden="true" />
              <h2 className="text-lg font-bold">Synchronizing live data &amp; telemetry</h2>
              <p className="text-sm text-base-content/70 max-w-md">
                Connecting to read-only telemetry services for health status, double-entry ledger balance, and strategy signals.
              </p>
            </div>
          </section>
        )}

        {state === 'error' && (
          <section className="alert alert-warning shadow-lg my-6" role="status">
            <AlertTriangle size={24} className="text-warning" aria-hidden="true" />
            <div>
              <h2 className="font-bold text-base">No verified dataset currently available.</h2>
              <p className="text-sm opacity-80">Refresh once the API is accessible. Unverified data remains hidden for safety.</p>
            </div>
          </section>
        )}

        <ErrorBoundary key={page}>
          {/* Dedicated Pair Deep-Dive Terminal Page */}
          {isPairPage && state === 'ready' && (
            <PairDetailPage
              symbol={currentPairSymbol}
              positions={executiveModel.positions}
              pairTickers={executiveModel.pairTickers}
              orders={executiveModel.orders}
              btcMacroTrend={executiveModel.radar.btcMacroTrend}
              scalperCriteria={executiveModel.radar.scalperCriteria}
              hawkesHazard={executiveModel.radar.hawkesHazard}
              evolutionRadar={executiveModel.evolutionRadar}
              onBack={() => {
                window.location.hash = '#overview'
              }}
              onSelectPair={(sym) => {
                setCurrentPairSymbol(sym)
                window.location.hash = `#/pair/${sym}`
              }}
            />
          )}

          {/* Executive Subpages (R5) */}
          {isPositionsPage && state === 'ready' && (
            <ExecutivePositionsPage
              positions={executiveModel.positions}
              pairTickers={executiveModel.pairTickers}
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
              executionStatus={canaryData.executionStatus ?? null}
              microstructureModel={microstructureModel}
              liveMarketModel={liveMarketModel}
              latencyMs={executiveModel.kpis.latencyMs}
            />
          )}

          {/* Historical Canary Pages (Phases 250-309 Preserved in Full) */}
          <Suspense
            fallback={
              <section className="card bg-base-200 border border-base-300 shadow-xl p-8 text-center my-6" aria-live="polite">
                <div className="flex flex-col items-center justify-center gap-3">
                  <span className="loading loading-ring loading-lg text-primary" aria-hidden="true" />
                  <h2 className="text-lg font-bold">Loading Historical Research Archive</h2>
                  <p className="text-sm text-base-content/70">
                    Retrieving archived component and cryptographic proof telemetry.
                  </p>
                </div>
              </section>
            }
          >
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
            {isTestnetBridgePage && state === 'ready' && <TestnetBridgePage model={testnetBridgeModel} />}
            {isKillSwitchPage && state === 'ready' && <KillSwitchPage model={killSwitchModel} />}
            {isProductionPage && state === 'ready' && <ProductionLaunchPage model={productionLaunchModel} />}
          </Suspense>
          {isEvolutionPage && state === 'ready' && <EvolutionPage model={autoEvolutionModel} />}
        </ErrorBoundary>

        <footer className="page-footer border-t border-base-300 mt-8 pt-4">
          <span className="text-xs text-base-content/60">Autonomous Futures Bot · Executive Trading 24/7 · PAPER-SAFE</span>
          <span className="text-xs font-mono text-base-content/60">{lastFetchedAt ? `Synchronized ${formatMyt(lastFetchedAt)}` : 'Synchronized —'}</span>
        </footer>
      </main>



      {/* Mobile Bottom Navigation Bar (< 768px only) */}
      <nav className="mobile-bottom-nav md:hidden" aria-label="Mobile Navigation">
        <a
          href="#overview"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isOverviewPage ? 'text-primary font-bold' : 'text-base-content/60'
          }`}
        >
          <Zap size={18} />
          <span>Overview</span>
        </a>
        <a
          href="#/positions"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isPositionsPage ? 'text-cyan-400 font-bold' : 'text-base-content/60'
          }`}
        >
          <Radio size={18} />
          <span>Positions</span>
        </a>
        <a
          href="#/trades"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isTradesPage ? 'text-emerald-400 font-bold' : 'text-base-content/60'
          }`}
        >
          <Receipt size={18} />
          <span>Trade Log</span>
        </a>
        <a
          href="#/safety"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isSafetyPage ? 'text-emerald-400 font-bold' : 'text-base-content/60'
          }`}
        >
          <ShieldCheck size={18} />
          <span>Safety</span>
        </a>
        <a
          href="#/evolution"
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isEvolutionPage ? 'text-purple-400 font-bold' : 'text-base-content/60'
          }`}
        >
          <Brain size={18} />
          <span>Evolution</span>
        </a>
        <button
          type="button"
          onClick={() => setIsArchiveDrawerOpen(true)}
          className={`flex flex-col items-center justify-center flex-1 py-1 text-[10px] font-medium transition-colors ${
            isArchive ? 'text-primary font-bold' : 'text-base-content/60'
          }`}
        >
          <Archive size={18} />
          <span>Archives</span>
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
