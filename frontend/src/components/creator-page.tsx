import { Bot, CheckCircle2, CircleAlert, DatabaseZap } from 'lucide-react'

import type { CreatorModel } from '@/lib/creator'

interface CreatorPageProps {
  model: CreatorModel
}

function shortHash(value: string | null): string {
  if (!value) return '—'
  return `${value.slice(0, 12)}…${value.slice(-8)}`
}

function ReadinessCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="creator-readiness-card">
      <span className="field-label">{label}</span>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  )
}

export function CreatorPage({ model }: CreatorPageProps) {
  const foundationReady = model.foundationState === 'verified'
  const symbols = model.symbols.length > 0 ? model.symbols.join(', ') : '—'
  const intervals = model.primaryInterval && model.contextInterval
    ? `${model.primaryInterval} / ${model.contextInterval}`
    : '—'

  return (
    <div className="creator-page">
      <section className="panel creator-intro" aria-labelledby="creator-heading">
        <div className="creator-intro-heading">
          <div className="creator-icon" aria-hidden="true">
            <Bot size={24} />
          </div>
          <div>
            <p className="eyebrow">Research plane / creator</p>
            <h2 id="creator-heading">Creator research readiness</h2>
          </div>
        </div>
        <div className={`creator-state ${foundationReady ? 'creator-state-ready' : 'creator-state-unavailable'}`}>
          {foundationReady ? <CheckCircle2 size={15} aria-hidden="true" /> : <CircleAlert size={15} aria-hidden="true" />}
          <span>{foundationReady ? 'DATA FOUNDATION VERIFIED' : 'DATA FOUNDATION UNAVAILABLE'}</span>
        </div>
        <p className="creator-intro-copy">
          This surface confirms whether the verified causal dataset is ready for a future creator engine.
          It does not claim that strategy generation is running.
        </p>
      </section>

      <section className="creator-readiness-grid" aria-label="Creator data foundation readiness">
        <ReadinessCard label="Universe" value={symbols} detail="Verified bundle symbols" />
        <ReadinessCard label="Components" value={model.componentCount?.toString() ?? '—'} detail="Registry-bound artifacts" />
        <ReadinessCard label="Intervals" value={intervals} detail="Primary / causal context" />
        <ReadinessCard label="Causal policy" value={model.contextPolicy ?? '—'} detail="Context availability rule" />
      </section>

      <section className="panel creator-unavailable" aria-labelledby="creator-output-heading" role="status">
        <div className="creator-unavailable-icon" aria-hidden="true">
          <DatabaseZap size={22} />
        </div>
        <div className="creator-unavailable-copy">
          <p className="eyebrow">Creator output</p>
          <h2 id="creator-output-heading">UNAVAILABLE — no creator artifact connected</h2>
          <p>
            No creator engine, candidate registry, generation artifact, or evaluator result is exposed by the current read-only API.
            Unavailable is shown explicitly instead of inventing a candidate count or AI activity.
          </p>
        </div>
        <div className="creator-boundary-list" aria-label="Creator output boundary">
          <div><span>Candidate count</span><strong>—</strong></div>
          <div><span>Generation status</span><strong>UNAVAILABLE</strong></div>
          <div><span>Evaluator result</span><strong>UNAVAILABLE</strong></div>
          <div><span>Bundle hash</span><code title={model.bundleHash ?? undefined}>{shortHash(model.bundleHash)}</code></div>
        </div>
      </section>
    </div>
  )
}
