import { CircleAlert, DatabaseZap, LockKeyhole, ShieldCheck } from 'lucide-react'

import type { LearnerModel } from '@/lib/learner'

function shortHash(value: string | null): string {
  if (!value) return '—'
  return `${value.slice(0, 12)}…${value.slice(-8)}`
}

function ReadinessFact({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="learner-readiness-fact">
      <span className="field-label">{label}</span>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  )
}

export function LearnerPage({ model }: { model: LearnerModel }) {
  const verified = model.status === 'verified'

  return (
    <section className="panel learner-readiness-panel" aria-labelledby="learner-readiness-heading">
      <div className="section-heading learner-section-heading">
        <div>
          <p className="eyebrow">Learner plane / read-only</p>
          <h2 id="learner-readiness-heading">Learner research readiness</h2>
        </div>
        <span className={`learner-verification-status ${verified ? 'learner-status-verified' : 'learner-status-unavailable'}`}>
          {verified ? 'DATA FOUNDATION VERIFIED' : 'UNAVAILABLE'}
        </span>
      </div>

      <p className="learner-readiness-copy">
        This page reports whether the verified causal dataset is ready for a future learner artifact.
        It does not claim that model training or learning activity is running.
      </p>

      <div className="learner-readiness-grid" aria-label="Learner readiness summary">
        <ReadinessFact
          label="Data foundation"
          value={verified ? 'VERIFIED' : 'UNAVAILABLE'}
          detail={verified ? 'Registry-bound causal bundle' : 'No verified bundle connected'}
        />
        <ReadinessFact label="Learner artifact" value="UNAVAILABLE" detail="No persisted learner artifact" />
        <ReadinessFact label="Learning run" value="UNAVAILABLE" detail="No verified run exposed" />
        <ReadinessFact label="Paper activation" value="OFF" detail="Activation is not available here" />
      </div>

      {verified ? (
        <section className="learner-foundation-section" aria-labelledby="learner-foundation-heading">
          <div className="learner-subsection-heading">
            <div>
              <span className="field-label">Verified input boundary</span>
              <h3 id="learner-foundation-heading">Causal research foundation</h3>
            </div>
            <DatabaseZap size={19} aria-hidden="true" />
          </div>
          <div className="learner-foundation-grid">
            <div><span className="field-label">Symbols</span><strong>{model.symbols.join(', ') || '—'}</strong></div>
            <div><span className="field-label">Intervals</span><strong>{model.primaryInterval ?? '—'} / {model.contextInterval ?? '—'}</strong></div>
            <div><span className="field-label">Causal policy</span><code>{model.contextFeaturePolicy ?? '—'}</code></div>
            <div><span className="field-label">Bundle hash</span><code title={model.bundleHash ?? undefined}>{shortHash(model.bundleHash)}</code></div>
            <div><span className="field-label">Registry hash</span><code title={model.registryHash ?? undefined}>{shortHash(model.registryHash)}</code></div>
          </div>
        </section>
      ) : (
        <section className="learner-unavailable-section" aria-labelledby="learner-unavailable-heading" role="status">
          <CircleAlert size={21} aria-hidden="true" />
          <div>
            <h3 id="learner-unavailable-heading">UNAVAILABLE — no verified learner foundation connected</h3>
            <p>No learner artifact, training run, model metric, or learning activity is rendered without verified input data.</p>
          </div>
        </section>
      )}

      <div className="learner-safety-boundary" aria-label="Learner safety boundary">
        <span><ShieldCheck size={14} aria-hidden="true" /> Evidence/readiness only</span>
        <span><LockKeyhole size={14} aria-hidden="true" /> Execution authority: off</span>
        <span>Paper activation: off</span>
      </div>
    </section>
  )
}
