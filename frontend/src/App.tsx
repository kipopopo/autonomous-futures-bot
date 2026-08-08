import { useCallback, useEffect, useMemo, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  Bot as BotIcon,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'

import { CreatorPage } from '@/components/creator-page'
import { MagicCard } from '@/components/magic-card'
import { fetchOverviewData } from '@/lib/api'
import { buildCreatorModel } from '@/lib/creator'
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

function statusFor(state: LoadState, model: OverviewModel): {
  label: string
  tone: 'verified' | 'warning' | 'error'
  icon: LucideIcon
} {
  if (state === 'loading') return { label: 'VERIFYING CATALOG', tone: 'warning', icon: Clock3 }
  if (model.verification === 'verified') {
    return { label: 'VERIFIED', tone: 'verified', icon: CheckCircle2 }
  }
  return { label: 'NO VERIFIED DATA', tone: 'error', icon: AlertTriangle }
}

function FactCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="fact-card">
      <p className="eyebrow">{label}</p>
      <p className="fact-value">{value}</p>
      <p className="fact-detail">{detail}</p>
    </article>
  )
}

function SafetyRail({ state, model }: { state: LoadState; model: OverviewModel }) {
  const status = statusFor(state, model)
  const StatusIcon = status.icon
  return (
    <section className="safety-rail" aria-label="Safety and verification status">
      <div className="safety-primary">
        <ShieldCheck size={18} aria-hidden="true" />
        <strong>PAPER-SAFE</strong>
        <span className="status-divider" aria-hidden="true" />
        <LockKeyhole size={16} aria-hidden="true" />
        <strong>READ-ONLY</strong>
      </div>
      <div className={`status-chip status-${status.tone}`} aria-live="polite">
        <StatusIcon size={15} aria-hidden="true" />
        <span>{status.label}</span>
      </div>
      <span className="authority-note">EXECUTION AUTHORITY: OFF</span>
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
  const [page, setPage] = useState<DashboardPage>(() => (
    typeof window === 'undefined' ? 'overview' : pageFromHash(window.location.hash)
  ))
  const [state, setState] = useState<LoadState>('loading')
  const [apiData, setApiData] = useState<DashboardApiData>(EMPTY_API_DATA)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null)
  const model = useMemo(() => buildOverviewModel(apiData), [apiData])
  const creatorModel = useMemo(() => buildCreatorModel(apiData), [apiData])
  const qualificationModel = useMemo(() => buildQualificationModel(apiData), [apiData])

  const loadData = useCallback(async () => {
    setState('loading')
    setErrorMessage(null)
    try {
      const nextData = await fetchOverviewData()
      setApiData(nextData)
      setLastFetchedAt(new Date())
      setState('ready')
    } catch (error) {
      setApiData(EMPTY_API_DATA)
      setState('error')
      setErrorMessage(error instanceof Error ? error.message : 'Verified data request failed')
    }
  }, [])

  useEffect(() => {
    void loadData()
  }, [loadData])

  useEffect(() => {
    const handleHashChange = () => setPage(pageFromHash(window.location.hash))
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  const status = statusFor(state, model)
  const symbols = model.symbols.length > 0 ? model.symbols.join(', ') : '—'
  const isCreatorPage = page === 'creator'
  const inventoryVisible = !isCreatorPage && state === 'ready' && model.components.length > 0

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand-mark" aria-hidden="true">AF</div>
        <div className="sidebar-brand">
          <strong>Autonomous<br />Futures</strong>
          <span>Research plane</span>
        </div>
        <nav>
          <a className={`nav-item ${!isCreatorPage ? 'nav-item-active' : ''}`} href="#overview" aria-current={!isCreatorPage ? 'page' : undefined}>
            <DatabaseZap size={17} aria-hidden="true" />
            <span>Overview</span>
          </a>
          <a className={`nav-item ${isCreatorPage ? 'nav-item-active' : ''}`} href="#/creator" aria-current={isCreatorPage ? 'page' : undefined}>
            <BotIcon size={17} aria-hidden="true" />
            <span>Creator</span>
          </a>
        </nav>
        <div className="sidebar-footer">
          <span className="sidebar-label">PHASE 2G</span>
          <span>Research-plane readiness</span>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="page-header">
          <div>
            <p className="eyebrow">Autonomous Futures / {isCreatorPage ? 'Creator plane' : 'Data plane'}</p>
            <h1>{isCreatorPage ? 'Creator' : 'Overview'}</h1>
            <p className="page-subtitle">{isCreatorPage ? 'Research generation readiness · MYT (GMT+8)' : 'Causal market-data foundation · MYT (GMT+8)'}</p>
          </div>
          <button className="refresh-button" type="button" onClick={() => void loadData()} disabled={state === 'loading'}>
            <RefreshCw size={16} className={state === 'loading' ? 'spin' : undefined} aria-hidden="true" />
            <span>{state === 'loading' ? 'Verifying…' : 'Refresh verified data'}</span>
          </button>
        </header>

        <SafetyRail state={state} model={model} />

        {errorMessage && (
          <div className="error-banner" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <div>
              <strong>Dataset verification failed</strong>
              <span>No unverified data is shown. {errorMessage}</span>
            </div>
          </div>
        )}

        {!isCreatorPage && (
          <>
            <section className="fact-grid" aria-label="Verified dataset summary">
              <FactCard label="Verification" value={status.label} detail={state === 'ready' ? 'Registry + artifacts verified' : 'No fallback values'} />
              <FactCard label="Symbols" value={symbols} detail="Persisted bundle universe" />
              <FactCard label="Components" value={model.componentCount?.toString() ?? '—'} detail="Bound to verified bundle" />
              <FactCard label="Intervals" value={model.primaryInterval && model.contextInterval ? `${model.primaryInterval} / ${model.contextInterval}` : '—'} detail="Primary / causal context" />
            </section>

            <IdentityCard model={model} />
          </>
        )}

        {state === 'loading' && (
          <section className="panel state-panel" aria-live="polite">
            <div className="loading-orbit" aria-hidden="true" />
            <div>
              <h2>Verifying persisted data</h2>
              <p>Reading health, bundle, registry-bound components, and content hashes.</p>
            </div>
          </section>
        )}

        {state === 'error' && (
          <section className="panel state-panel state-error" role="status">
            <AlertTriangle size={22} aria-hidden="true" />
            <div>
              <h2>No verified dataset is available for this scope.</h2>
              <p>Refresh after the read-only API and storage root are available. Unverified data remains hidden.</p>
            </div>
          </section>
        )}

        {isCreatorPage && state === 'ready' && <CreatorPage model={creatorModel} qualification={qualificationModel} />}
        {inventoryVisible && <ComponentInventory components={model.components} />}

        <footer className="page-footer">
          <span>Read-only observational surface</span>
          <span>{lastFetchedAt ? `Fetched ${formatMyt(lastFetchedAt)}` : 'Fetched —'}</span>
        </footer>
      </main>
    </div>
  )
}

export default App
