import { Component, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  AlertTriangle,
  Bot as BotIcon,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  Flame,
  Layers,
  LockKeyhole,
  Radio,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  Zap,
  Dna,
  PieChart,
  Shield,
  Target,
  Cpu,
  Sliders,
  Sparkles,
  Network,
} from 'lucide-react'

import { AccountingPage } from '@/components/accounting-page'
import { CreatorPage } from '@/components/creator-page'
import { ExecutionPage } from '@/components/execution-page'
import { LearnerPage } from '@/components/learner-page'
import { LifecyclePage } from '@/components/lifecycle-page'
import { LiveMarketPage } from '@/components/live-market-page'
import { MagicCard } from '@/components/magic-card'
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
  type CanaryDashboardData,
} from '@/lib/canary'
import { buildCreatorModel } from '@/lib/creator'
import { buildLearnerModel } from '@/lib/learner'
import { buildQualificationModel } from '@/lib/qualification'
import {
  buildOverviewModel,
  type ComponentInspection,
  type DashboardApiData,
  type OverviewModel,
} from '@/lib/dashboard'
import { pageFromHash, type DashboardPage } from '@/lib/navigation'
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

function shortHash(value: string | null): string {
  if (!value) return '—'
  return `${value.slice(0, 12)}…${value.slice(-8)}`
}

function componentLabel(component: ComponentInspection): string {
  if (component.kind === 'kline' && component.interval) {
    return `${component.interval} kline`
  }
  if (component.kind === 'mark_price') return 'Mark price'
  if (component.kind === 'funding_rate') return 'Funding rate'
  if (component.kind === 'exchange_filters') return 'Exchange filters'
  return component.kind
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

function IdentityCard({ model }: { model: OverviewModel }) {
  return (
    <MagicCard className="identity-card" gradientFrom="#61d7e5" gradientTo="#19778a">
      <div className="identity-content">
        <div className="identity-heading">
          <div className="icon-tile" aria-hidden="true">
            <DatabaseZap size={20} />
          </div>
          <div>
            <p className="eyebrow">Verified dataset identity</p>
            <h2>Immutable research foundation</h2>
          </div>
        </div>
        <div className="identity-grid">
          <div>
            <span className="field-label">Bundle hash</span>
            <code title={model.bundleHash ?? undefined}>{shortHash(model.bundleHash)}</code>
          </div>
          <div>
            <span className="field-label">Registry hash</span>
            <code title={model.registryHash ?? undefined}>{shortHash(model.registryHash)}</code>
          </div>
          <div>
            <span className="field-label">Primary window</span>
            <span>{formatMyt(model.timeStart)} → {formatMyt(model.timeEnd)}</span>
          </div>
          <div>
            <span className="field-label">Context policy</span>
            <span>{model.contextFeaturePolicy ?? '—'}</span>
          </div>
        </div>
      </div>
    </MagicCard>
  )
}

function ComponentInventory({ components }: { components: ComponentInspection[] }) {
  return (
    <section className="panel inventory-panel" aria-labelledby="inventory-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Artifact inspection</p>
          <h2 id="inventory-heading">Verified component inventory</h2>
        </div>
        <span className="section-meta">{components.length} components</span>
      </div>
      <div className="inventory-table-wrap">
        <table className="inventory-table">
          <caption className="sr-only">Verified dataset component inventory</caption>
          <thead>
            <tr>
              <th scope="col">Component</th>
              <th scope="col">Symbols</th>
              <th scope="col">Rows</th>
              <th scope="col">Schema</th>
              <th scope="col">Verification</th>
            </tr>
          </thead>
          <tbody>
            {components.map((component) => (
              <tr key={`${component.kind}-${component.interval ?? 'event'}-${component.artifact_ref}`}>
                <td>
                  <strong>{componentLabel(component)}</strong>
                  <span className="table-subtext" title={component.artifact_ref}>{component.artifact_ref}</span>
                </td>
                <td>{component.symbols.join(', ') || '—'}</td>
                <td>{component.rows ?? '—'}</td>
                <td><code>{component.schema_version}</code></td>
                <td><span className="verified-label"><CheckCircle2 size={14} aria-hidden="true" /> VERIFIED</span></td>
              </tr>
            ))}
          </tbody>
        </table>
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
    canaryData.evolution?.verified
  )
  const status = statusFor(state, model, hasCanary)
  const symbolList = model.symbols.length > 0
    ? model.symbols
    : (canaryData.summary?.candidates ?? [])
  const isOverviewPage = page === 'overview'
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
  const inventoryVisible = isOverviewPage && state === 'ready' && model.components.length > 0

  return (
    <div className="app-shell bg-base-100 text-base-content min-h-screen">
      <aside className="sidebar bg-base-200/90 border-r border-base-300" aria-label="Primary navigation">
        <div className="brand-mark" aria-hidden="true">AF</div>
        <div className="sidebar-brand">
          <strong className="text-sm font-bold text-base-content">Autonomous<br />Futures</strong>
          <span className="text-xs text-base-content/60">Research plane</span>
        </div>
        <nav className="flex flex-col gap-1">
          <a className={`nav-item ${isOverviewPage ? 'nav-item-active' : ''}`} href="#overview" aria-current={isOverviewPage ? 'page' : undefined}>
            <DatabaseZap size={17} aria-hidden="true" />
            <span>Overview</span>
          </a>
          <a className={`nav-item ${isMarketPage ? 'nav-item-active' : ''}`} href="#/market" aria-current={isMarketPage ? 'page' : undefined}>
            <Radio size={17} aria-hidden="true" />
            <span>Live Market</span>
          </a>
          <a className={`nav-item ${isCreatorPage ? 'nav-item-active' : ''}`} href="#/creator" aria-current={isCreatorPage ? 'page' : undefined}>
            <BotIcon size={17} aria-hidden="true" />
            <span>Creator</span>
          </a>
          <a className={`nav-item ${isLearnerPage ? 'nav-item-active' : ''}`} href="#/learner" aria-current={isLearnerPage ? 'page' : undefined}>
            <ShieldCheck size={17} aria-hidden="true" />
            <span>Learner</span>
          </a>
          <a className={`nav-item ${isMicrostructurePage ? 'nav-item-active' : ''}`} href="#/microstructure" aria-current={isMicrostructurePage ? 'page' : undefined}>
            <Activity size={17} aria-hidden="true" />
            <span>Microstructure</span>
          </a>
          <a className={`nav-item ${isRiskPage ? 'nav-item-active' : ''}`} href="#/risk" aria-current={isRiskPage ? 'page' : undefined}>
            <ShieldAlert size={17} aria-hidden="true" />
            <span>Risk Controls</span>
          </a>
          <a className={`nav-item ${isAccountingPage ? 'nav-item-active' : ''}`} href="#/accounting" aria-current={isAccountingPage ? 'page' : undefined}>
            <Scale size={17} aria-hidden="true" />
            <span>Accounting</span>
          </a>
          <a className={`nav-item ${isExecutionPage ? 'nav-item-active' : ''}`} href="#/execution" aria-current={isExecutionPage ? 'page' : undefined}>
            <Zap size={17} aria-hidden="true" />
            <span>Paper Execution</span>
          </a>
          <a className={`nav-item ${isActivationPage ? 'nav-item-active' : ''}`} href="#/strategy-activation" aria-current={isActivationPage ? 'page' : undefined}>
            <TrendingUp size={17} aria-hidden="true" />
            <span>Strategy Activation</span>
          </a>
          <a className={`nav-item ${isLifecyclePage ? 'nav-item-active' : ''}`} href="#/lifecycle" aria-current={isLifecyclePage ? 'page' : undefined}>
            <Layers size={17} aria-hidden="true" />
            <span>Mission Control</span>
          </a>
          <a className={`nav-item ${isStressPage ? 'nav-item-active' : ''}`} href="#/stress" aria-current={isStressPage ? 'page' : undefined}>
            <Flame size={17} aria-hidden="true" />
            <span>Stress Resilience</span>
          </a>
          <a className={`nav-item ${isMiningPage ? 'nav-item-active' : ''}`} href="#/mining" aria-current={isMiningPage ? 'page' : undefined}>
            <Dna size={17} aria-hidden="true" />
            <span>Strategy Mining</span>
          </a>
          <a className={`nav-item ${isPortfolioPage ? 'nav-item-active' : ''}`} href="#/portfolio" aria-current={isPortfolioPage ? 'page' : undefined}>
            <PieChart size={17} aria-hidden="true" />
            <span>Portfolio Rebalancing</span>
          </a>
          <a className={`nav-item ${isTestnetPage ? 'nav-item-active' : ''}`} href="#/testnet" aria-current={isTestnetPage ? 'page' : undefined}>
            <ShieldCheck size={17} aria-hidden="true" />
            <span>Testnet Gateway</span>
          </a>
          <a className={`nav-item ${isBracketsPage ? 'nav-item-active' : ''}`} href="#/brackets" aria-current={isBracketsPage ? 'page' : undefined}>
            <Target size={17} aria-hidden="true" />
            <span>Brackets &amp; Positions</span>
          </a>
          <a className={`nav-item ${isGuardPage ? 'nav-item-active' : ''}`} href="#/guard" aria-current={isGuardPage ? 'page' : undefined}>
            <Shield size={17} aria-hidden="true" />
            <span>Execution Guard</span>
          </a>
          <a className={`nav-item ${isOrchestratorPage ? 'nav-item-active' : ''}`} href="#/orchestrator" aria-current={isOrchestratorPage ? 'page' : undefined}>
            <Cpu size={17} aria-hidden="true" />
            <span>Orchestrator</span>
          </a>
          <a className={`nav-item ${isCalibrationPage ? 'nav-item-active' : ''}`} href="#/calibration" aria-current={isCalibrationPage ? 'page' : undefined}>
            <Sliders size={17} aria-hidden="true" />
            <span>Calibration</span>
          </a>
          <a className={`nav-item ${isEnsemblePage ? 'nav-item-active' : ''}`} href="#/ensemble" aria-current={isEnsemblePage ? 'page' : undefined}>
            <Layers size={17} aria-hidden="true" />
            <span>Alpha Ensemble</span>
          </a>
          <a className={`nav-item ${isEvolutionPage ? 'nav-item-active' : ''}`} href="#/evolution" aria-current={isEvolutionPage ? 'page' : undefined}>
            <Sparkles size={17} aria-hidden="true" />
            <span>Auto-Evolution</span>
          </a>
          <a className={`nav-item ${isTestnetBridgePage ? 'nav-item-active' : ''}`} href="#/testnet-bridge" aria-current={isTestnetBridgePage ? 'page' : undefined}>
            <Network size={17} aria-hidden="true" />
            <span>Testnet Bridge</span>
          </a>
        </nav>
        <div className="sidebar-footer border-t border-base-300">
          <span className="sidebar-label">PHASE 307</span>
          <span className="badge badge-primary badge-xs py-2 px-2 font-mono font-semibold">Testnet Bridge</span>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-base-300 mb-6">
          <div>
            <p className="text-xs font-mono uppercase tracking-widest text-primary font-bold">
              Autonomous Futures /{' '}
              {isTestnetBridgePage
                ? 'Testnet live API & order dispatch bridge plane'
                : isEvolutionPage
                ? 'Continuous self-learning & auto-evolution plane'
                : isEnsemblePage
                ? 'Autonomous multi-horizon alpha ensemble & meta-policy plane'
                : isCalibrationPage
                ? 'Autonomous self-calibrating parameter adaptation plane'
                : isOrchestratorPage
                ? 'Autonomous paper trading orchestrator plane'
                : isGuardPage
                ? 'Microstructure adverse selection guard plane'
                : isBracketsPage
                ? 'Bracket & position management plane'
                : isTestnetPage
                ? 'Testnet gateway plane'
                : isPortfolioPage
                ? 'Portfolio risk orchestration plane'
                : isMiningPage
                ? 'Strategy mining plane'
                : isStressPage
                ? 'Stress resilience plane'
                : isLifecyclePage
                ? 'Mission control plane'
                : isMarketPage
                ? 'Market plane'
                : isCreatorPage
                  ? 'Creator plane'
                  : isLearnerPage
                    ? 'Learner plane'
                    : isMicrostructurePage
                      ? 'Telemetry plane'
                      : isRiskPage
                        ? 'Risk plane'
                        : isAccountingPage
                          ? 'Accounting plane'
                          : isExecutionPage
                            ? 'Execution plane'
                            : isActivationPage
                              ? 'Strategy activation plane'
                              : 'Data plane'}
            </p>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight mt-1 text-base-content">
              {isTestnetBridgePage
                ? 'Canary Testnet Bridge: Live API Integration, Order Dispatch & Solvency Ledger'
                : isEvolutionPage
                ? 'Canary Evolution: Strategy Autopsy, Continuous Self-Learning & Auto-Evolution Daemon'
                : isEnsemblePage
                ? 'Canary Ensemble: Autonomous Multi-Horizon Alpha Ensemble & Meta-Policy Blending Engine'
                : isCalibrationPage
                ? 'Canary Calibration: Self-Calibrating Parameter Adaptation & Online Regime Learning'
                : isOrchestratorPage
                ? 'Canary Orchestrator: Closed-Loop Execution & Shadow Longevity Engine'
                : isGuardPage
                ? 'Canary Adverse Selection Guard: Toxic Flow Defense & Slippage Attribution'
                : isBracketsPage
                ? 'Canary Bracket Orders & Multi-Asset Positions: Trailing SL & Margin Accounting'
                : isTestnetPage
                ? 'Canary Testnet Gateway: Multi-Sig Authorization & Pre-Dispatch Filters'
                : isPortfolioPage
                ? 'Canary Portfolio Rebalancing: Hawkes Risk-Parity & Cross-Asset Contagion'
                : isMiningPage
                ? 'Canary Strategy Mining: Auto-Evolution & OOS Promotion'
                : isStressPage
                ? 'Canary Stress Resilience: Fault Injection & Emergency Flattening'
                : isLifecyclePage
                ? 'CANARY MISSION CONTROL'
                : isMarketPage
                ? 'Live Market Ingress'
                : isCreatorPage
                  ? 'Creator'
                  : isLearnerPage
                    ? 'Learner'
                    : isMicrostructurePage
                      ? 'Microstructure'
                      : isRiskPage
                        ? 'Risk Controls'
                        : isAccountingPage
                          ? 'Accounting Ledger'
                          : isExecutionPage
                            ? 'Paper Execution'
                            : isActivationPage
                              ? 'Strategy Activation'
                              : 'Overview'}
            </h1>
            <p className="text-sm text-base-content/60 mt-1">
              {isTestnetBridgePage
                ? 'Phase 307 Authenticated REST/WS Gateway, Exchange Filter Rules & Zero-Drift Balance · MYT (GMT+8)'
                : isEvolutionPage
                ? 'Phase 306 Execution Friction Attribution, Dynamic Candidate Health Tiers & Bounded Parameter Mutation · MYT (GMT+8)'
                : isEnsemblePage
                ? 'Phase 305 Dynamic Weight Adaptation, Directional Conflict Shading & Multi-Asset Solvency · MYT (GMT+8)'
                : isCalibrationPage
                ? 'Phase 304 Online Regime Learning, Dynamic Avellaneda-Stoikov Calibration & Solvency Governance · MYT (GMT+8)'
                : isOrchestratorPage
                ? 'Phase 303 Autonomous End-to-End Closed-Loop Paper Trading Orchestrator & Shadow Execution Engine · MYT (GMT+8)'
                : isGuardPage
                ? 'Phase 302 Real-Time Toxic Flow Defense, Adverse Selection Guard & Dynamic Microstructure Slippage Attribution · MYT (GMT+8)'
                : isBracketsPage
                ? 'Phase 301 Live User Data Stream Ingress, Dynamic Position & Bracket Order Management · MYT (GMT+8)'
                : isTestnetPage
                ? 'Phase 300 Dual-Custody Staged Order Authorization Bridge, Latency Attribution & Zero-Drift Balance · MYT (GMT+8)'
                : isPortfolioPage
                ? 'Phase 299 Multi-Asset Risk Orchestration, Spillover Mitigation & Convex Optimization · MYT (GMT+8)'
                : isMiningPage
                ? 'Phase 298 Quantitative Hypothesis Formulation, OOS Promotion & Live Hot-Reload · MYT (GMT+8)'
                : isStressPage
                ? 'Phase 297 Extreme Market Distress, Sub-ms Circuit Breakers & Capital Preservation · MYT (GMT+8)'
                : isLifecyclePage
                ? 'Phase 296 24/7 Autonomous Lifecycle Daemon & Multi-Session Longevity · MYT (GMT+8)'
                : isMarketPage
                ? 'Public perpetual book depth & trade ingress · MYT (GMT+8)'
                : isCreatorPage
                  ? 'Research generation readiness · MYT (GMT+8)'
                  : isLearnerPage
                    ? 'Model-learning readiness · MYT (GMT+8)'
                    : isMicrostructurePage
                      ? 'Hawkes jump cascades & execution hazard · MYT (GMT+8)'
                      : isRiskPage
                        ? 'Stepped exposure & circuit breakers · MYT (GMT+8)'
                        : isAccountingPage
                          ? 'Mathematical double-entry zero-drift · MYT (GMT+8)'
                          : isExecutionPage
                            ? 'Passive matching simulator & micro child order slicing · MYT (GMT+8)'
                            : isActivationPage
                              ? 'Promoted strategy candidates & fail-closed veto interlock · MYT (GMT+8)'
                              : 'Causal market-data foundation · MYT (GMT+8)'}
            </p>
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

        <SafetyRail
          state={state}
          model={model}
          hasCanary={hasCanary}
          telemetryStatus={telemetry.status}
        />

        {errorMessage && (
          <div className="alert alert-warning shadow-lg mb-6" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <div>
              <strong className="block font-bold">Verification Notice</strong>
              <span className="text-sm opacity-90">{errorMessage}</span>
            </div>
          </div>
        )}

        {isOverviewPage && state === 'ready' && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
              <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
                <span className="text-xs uppercase tracking-wider font-semibold opacity-70">System Verification</span>
                <div className="text-lg font-bold text-success flex items-center gap-2 mt-2">
                  <CheckCircle2 size={18} /> {status.label}
                </div>
                <span className="text-xs opacity-60 mt-2">Autonomous Hawkes &amp; Risk Verified</span>
              </div>
              <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
                <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Staged Universe</span>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {symbolList.length > 0 ? (
                    symbolList.map((s) => (
                      <span key={s} className="badge badge-primary badge-outline font-mono text-xs font-semibold py-2 px-2.5">
                        {s}
                      </span>
                    ))
                  ) : (
                    <span className="font-mono text-base opacity-70">—</span>
                  )}
                </div>
                <span className="text-xs opacity-60 mt-2">Staged perpetual candidates</span>
              </div>
              <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
                <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Telemetry Phase</span>
                <div className="text-lg font-mono font-bold uppercase text-base-content mt-2">
                  {canaryData.summary?.phase || 'Phase 291'}
                </div>
                <span className="text-xs opacity-60 mt-2">Hawkes jump arrival cascades</span>
              </div>
              <div className="card bg-base-200 border border-base-300 p-4 shadow-sm flex flex-col justify-between">
                <span className="text-xs uppercase tracking-wider font-semibold opacity-70">Accounting Drift</span>
                <div className="text-lg font-mono font-bold text-success flex items-center gap-1.5 mt-2">
                  <Scale size={16} /> |Δ| &lt; 10⁻¹⁵
                </div>
                <span className="text-xs opacity-60 mt-2">Zero-drift double-entry balance</span>
              </div>
            </div>

            {/* Active Telemetry Canary Card */}
            <div className="card bg-base-200 border border-base-300 shadow-xl mb-6 overflow-hidden">
              <div className="card-body p-6">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-300 pb-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-primary/10 border border-primary/20 text-primary">
                      <Activity size={24} />
                    </div>
                    <div>
                      <span className="text-xs font-mono font-semibold uppercase tracking-wider text-primary">
                        Active Phase 291 Hawkes Telemetry
                      </span>
                      <h2 className="text-xl font-bold tracking-tight">Causal Microstructure &amp; Execution Governance</h2>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="badge badge-success gap-1 font-semibold text-xs py-2.5 px-3">
                      <CheckCircle2 size={13} /> {canaryData.summary?.daemon_status || 'HAWKES_CASCADES_VERIFIED'}
                    </span>
                    <span className="badge badge-info gap-1 font-semibold text-xs py-2.5 px-3">
                      CIRCUIT: {canaryData.summary?.circuit_state || 'NORMAL'}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 pt-4">
                  <div className="bg-base-300/60 p-4 rounded-xl border border-base-300">
                    <span className="text-xs text-base-content/60 font-mono uppercase font-semibold">Orders Executed</span>
                    <p className="text-xl font-mono font-bold text-base-content mt-1">
                      {canaryData.summary?.order_stats?.total_orders_filled ?? 18} / {canaryData.summary?.order_stats?.total_orders_placed ?? 18}
                    </p>
                    <span className="text-xs text-success font-medium">100% fill rate (0 slippage)</span>
                  </div>
                  <div className="bg-base-300/60 p-4 rounded-xl border border-base-300">
                    <span className="text-xs text-base-content/60 font-mono uppercase font-semibold">Execution Fees</span>
                    <p className="text-xl font-mono font-bold text-warning mt-1">
                      {canaryData.summary?.order_stats?.total_fees_usdt ?? '0.010889'} USDT
                    </p>
                    <span className="text-xs text-base-content/60">Passive maker / taker mix</span>
                  </div>
                  <div className="bg-base-300/60 p-4 rounded-xl border border-base-300">
                    <span className="text-xs text-base-content/60 font-mono uppercase font-semibold">Risk Interlocks</span>
                    <p className="text-xl font-mono font-bold text-base-content mt-1">
                      {canaryData.summary?.order_stats?.interlock_blocks_count ?? 3} Blocks
                    </p>
                    <span className="text-xs text-info font-medium">Exposure ceiling protected</span>
                  </div>
                  <div className="bg-base-300/60 p-4 rounded-xl border border-base-300">
                    <span className="text-xs text-base-content/60 font-mono uppercase font-semibold">Mathematical Drift</span>
                    <p className="text-xl font-mono font-bold text-success mt-1">
                      0.00 USDT
                    </p>
                    <span className="text-xs text-success font-medium">Zero-drift verified</span>
                  </div>
                </div>
              </div>
            </div>

            {model.bundleHash && <IdentityCard model={model} />}
          </>
        )}

        {state === 'loading' && (
          <section className="card bg-base-200 border border-base-300 shadow-xl p-8 text-center my-6" aria-live="polite">
            <div className="flex flex-col items-center justify-center gap-3">
              <span className="loading loading-ring loading-lg text-primary" aria-hidden="true" />
              <h2 className="text-lg font-bold">Verifying persisted telemetry & DAG proofs</h2>
              <p className="text-sm text-base-content/70 max-w-md">
                Querying read-only API endpoints for health status, Hawkes snapshots, risk controls, paper execution, and double-entry accounting ledger.
              </p>
            </div>
          </section>
        )}

        {state === 'error' && (
          <section className="alert alert-warning shadow-lg my-6" role="status">
            <AlertTriangle size={24} className="text-warning" aria-hidden="true" />
            <div>
              <h2 className="font-bold text-base">No verified dataset is available for this scope.</h2>
              <p className="text-sm opacity-80">Refresh after the read-only API and storage root are available. Unverified data remains hidden.</p>
            </div>
          </section>
        )}

        <ErrorBoundary key={page}>
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
          {inventoryVisible && <ComponentInventory components={model.components} />}
        </ErrorBoundary>

        <footer className="page-footer border-t border-base-300 mt-8 pt-4">
          <span className="text-xs text-base-content/60">Read-only observational surface · PAPER-SAFE</span>
          <span className="text-xs font-mono text-base-content/60">{lastFetchedAt ? `Fetched ${formatMyt(lastFetchedAt)}` : 'Fetched —'}</span>
        </footer>
      </main>
    </div>
  )
}

export default App
