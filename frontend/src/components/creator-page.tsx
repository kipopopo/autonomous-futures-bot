import { useState } from 'react'

import { Bot, CheckCircle2, CircleAlert, DatabaseZap, FileCheck2, ShieldAlert } from 'lucide-react'

import { fetchCreatorQualification } from '@/lib/api'
import type { CreatorModel } from '@/lib/creator'
import {
  buildQualificationDetailModel,
  type QualificationDetailModel,
  type QualificationModel,
  type QualificationSummary,
} from '@/lib/qualification'

interface CreatorPageProps {
  model: CreatorModel
  qualification: QualificationModel
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

function CandidateRegistry({ model }: { model: CreatorModel }) {
  return (
    <section className="panel creator-candidate-registry" aria-labelledby="candidate-registry-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Read-only creator output</p>
          <h2 id="candidate-registry-heading">Verified candidate registry</h2>
        </div>
        <span className="creator-registry-status">REGISTRY VERIFIED</span>
      </div>
      <p className="creator-registry-copy">
        These are persisted research artifacts bound to the verified dataset. They remain in testing state;
        this surface does not qualify, promote, signal, or execute them.
      </p>
      <div className="creator-registry-meta">
        <div><span className="field-label">Candidates</span><strong>{model.candidateCount ?? '—'}</strong></div>
        <div><span className="field-label">Registry hash</span><code title={model.candidateRegistryHash ?? undefined}>{shortHash(model.candidateRegistryHash)}</code></div>
      </div>
      <div className="creator-candidate-list">
        {model.candidates.map((candidate) => (
          <article className="creator-candidate-card" key={candidate.candidateId}>
            <div className="creator-candidate-heading">
              <div>
                <span className="field-label">Candidate</span>
                <strong>{candidate.candidateId}</strong>
              </div>
              <span className="creator-testing-status">TESTING</span>
            </div>
            <div className="creator-candidate-facts">
              <div><span className="field-label">Family</span><span>{candidate.family}</span></div>
              <div><span className="field-label">Symbols</span><span>{candidate.symbols.join(', ')}</span></div>
              <div><span className="field-label">Creator run</span><code>{candidate.creatorRunId}</code></div>
              <div><span className="field-label">Artifact</span><code title={candidate.artifactHash}>{candidate.artifactRef}</code></div>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

function UnavailableCreatorOutput({ model }: { model: CreatorModel }) {
  return (
    <section className="panel creator-unavailable" aria-labelledby="creator-output-heading" role="status">
      <div className="creator-unavailable-icon" aria-hidden="true">
        <DatabaseZap size={22} />
      </div>
      <div className="creator-unavailable-copy">
        <p className="eyebrow">Creator output</p>
        <h2 id="creator-output-heading">UNAVAILABLE — no verified candidate registry connected</h2>
        <p>
          No verified creator candidate registry is exposed by the current read-only API.
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
  )
}

function formatMyt(value: string): string {
  const date = new Date(value)
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

function sourceLabel(source: QualificationSummary['source']): string {
  return source === 'walk_forward_oos' ? 'Walk-forward OOS' : 'Creator evaluator'
}

function DetailValue({ value }: { value: string | null }) {
  return <span>{value ?? '—'}</span>
}

function QualificationDetailPanel({ model }: { model: QualificationDetailModel }) {
  if (model.status === 'error') {
    return (
      <div className="creator-qualification-detail creator-qualification-detail-error" role="alert">
        <strong>DETAIL INTEGRITY UNAVAILABLE</strong>
        <span>No full artifact values are rendered until this persisted detail can be verified.</span>
      </div>
    )
  }

  if (model.status === 'unavailable') {
    return (
      <div className="creator-qualification-detail creator-qualification-detail-error" role="status">
        <strong>DETAIL UNAVAILABLE</strong>
        <span>The persisted qualification artifact is not available for this candidate.</span>
      </div>
    )
  }

  return (
    <div className="creator-qualification-detail" aria-labelledby="qualification-detail-heading">
      <div className="creator-qualification-detail-heading">
        <div>
          <span className="field-label">Verified artifact detail</span>
          <h3 id="qualification-detail-heading">Evidence, gates, and provenance</h3>
        </div>
        <span className="creator-qualification-detail-status">FULL ARTIFACT VERIFIED</span>
      </div>
      <div className="creator-qualification-detail-facts">
        <div><span className="field-label">Decision</span><strong>{model.decision ?? '—'}</strong></div>
        <div><span className="field-label">Source</span><DetailValue value={model.source === 'walk_forward_oos' ? 'Walk-forward OOS' : model.source} /></div>
        <div><span className="field-label">Evaluator run</span><code>{model.evaluatorRunId ?? '—'}</code></div>
        <div><span className="field-label">Evaluator version</span><code>{model.evaluatorVersion ?? '—'}</code></div>
        <div><span className="field-label">Windows</span><DetailValue value={model.windowsEvaluated?.toString() ?? null} /></div>
        <div><span className="field-label">Policy</span><code>{model.qualificationPolicyId ?? '—'}</code></div>
        <div><span className="field-label">Evaluated</span><DetailValue value={model.evaluatedAt ? formatMyt(model.evaluatedAt) : null} /></div>
      </div>

      <div className="creator-qualification-detail-block">
        <div className="creator-qualification-detail-block-heading">
          <h4>Persisted metrics</h4>
          <span>Decimal values are displayed without recalculation</span>
        </div>
        {model.metrics.length > 0 ? (
          <div className="creator-qualification-metric-grid">
            {model.metrics.map((metric) => (
              <div key={metric.metricId}>
                <span className="field-label">{metric.metricId}</span>
                <code>{metric.value}</code>
              </div>
            ))}
          </div>
        ) : <div className="creator-qualification-empty">No persisted metrics.</div>}
      </div>

      <div className="creator-qualification-detail-block">
        <div className="creator-qualification-detail-block-heading">
          <h4>Qualification gates</h4>
          <span>Every gate remains auditable</span>
        </div>
        {model.gates.length > 0 ? (
          <div className="creator-qualification-gate-list">
            {model.gates.map((gate) => (
              <div className="creator-qualification-gate" key={gate.gateId}>
                <span className={`creator-qualification-gate-status ${gate.passed ? 'gate-pass' : 'gate-fail'}`}>
                  {gate.passed ? 'PASS' : 'FAIL'}
                </span>
                <code>{gate.gateId}</code>
                <span>{gate.observed ?? '—'} {gate.comparator} {gate.threshold ?? '—'}</span>
                <code>{gate.reasonCode}</code>
              </div>
            ))}
          </div>
        ) : <div className="creator-qualification-empty">No persisted gates.</div>}
      </div>

      <div className="creator-qualification-detail-block">
        <div className="creator-qualification-detail-block-heading">
          <h4>Binding and provenance</h4>
          <span>Exact hashes from the persisted artifact</span>
        </div>
        <div className="creator-qualification-binding-grid">
          <div><span className="field-label">Candidate artifact</span><code title={model.binding.candidateArtifactHash ?? undefined}>{shortHash(model.binding.candidateArtifactHash)}</code></div>
          <div><span className="field-label">Dataset bundle</span><code title={model.binding.bundleHash ?? undefined}>{shortHash(model.binding.bundleHash)}</code></div>
          <div><span className="field-label">Dataset registry</span><code title={model.binding.datasetRegistryHash ?? undefined}>{shortHash(model.binding.datasetRegistryHash)}</code></div>
          <div><span className="field-label">OOS aggregation</span><code title={model.binding.oosAggregationHash ?? undefined}>{shortHash(model.binding.oosAggregationHash)}</code></div>
          <div><span className="field-label">Qualification artifact</span><code title={model.binding.qualificationHash ?? undefined}>{shortHash(model.binding.qualificationHash)}</code></div>
        </div>
      </div>

      <div className="creator-qualification-detail-safety">
        <span>Promotion: {model.safety.promotionState ?? '—'}</span>
        <span>Execution authority: {model.safety.executionAuthority === false ? 'off' : '—'}</span>
      </div>
    </div>
  )
}

function QualificationCard({ summary }: { summary: QualificationSummary }) {
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<QualificationDetailModel | null>(null)

  const toggleDetail = async () => {
    if (expanded && !loading && detail?.status === 'verified') {
      setExpanded(false)
      return
    }
    setExpanded(true)
    setLoading(true)
    try {
      const response = await fetchCreatorQualification(summary.candidateId)
      setDetail(buildQualificationDetailModel(response))
    } catch (error) {
      setDetail(buildQualificationDetailModel(
        null,
        error instanceof Error ? error.message : 'Qualification detail could not be verified',
      ))
    } finally {
      setLoading(false)
    }
  }

  const passed = summary.decision === 'qualified'
  return (
    <article className="creator-qualification-card">
      <div className="creator-qualification-heading">
        <div>
          <span className="field-label">Candidate</span>
          <strong>{summary.candidateId}</strong>
        </div>
        <span className={`creator-qualification-decision ${passed ? 'evidence-passed' : 'evidence-rejected'}`}>
          {passed ? <CheckCircle2 size={14} aria-hidden="true" /> : <CircleAlert size={14} aria-hidden="true" />}
          {passed ? 'EVIDENCE PASSED' : 'EVIDENCE REJECTED'}
        </span>
      </div>
      <div className="creator-qualification-facts">
        <div><span className="field-label">Source</span><span>{sourceLabel(summary.source)}</span></div>
        <div><span className="field-label">Evaluator</span><code>{summary.evaluatorVersion}</code></div>
        <div><span className="field-label">Windows</span><span>{summary.windowsEvaluated}</span></div>
        <div><span className="field-label">Policy</span><code>{summary.qualificationPolicyId ?? '—'}</code></div>
        <div><span className="field-label">Evaluated</span><span>{formatMyt(summary.evaluatedAt)}</span></div>
        <div><span className="field-label">Promotion</span><span>{summary.promotionState}</span></div>
      </div>
      <button
        type="button"
        className="creator-detail-toggle"
        aria-expanded={expanded}
        onClick={toggleDetail}
        disabled={loading}
      >
        {loading ? 'Loading persisted detail…' : expanded ? 'Hide full evidence' : 'View full evidence'}
      </button>
      {expanded && loading && <div className="creator-detail-loading" role="status">Verifying persisted qualification artifact…</div>}
      {expanded && !loading && detail && <QualificationDetailPanel model={detail} />}
    </article>
  )
}

function QualificationEvidence({ model }: { model: QualificationModel }) {
  if (model.status === 'error') {
    return (
      <section className="panel creator-qualification creator-qualification-error" aria-labelledby="qualification-heading" role="alert">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Evidence boundary</p>
            <h2 id="qualification-heading">Persisted qualification evidence</h2>
          </div>
          <span className="creator-qualification-status qualification-status-error"><ShieldAlert size={14} aria-hidden="true" /> INTEGRITY UNAVAILABLE</span>
        </div>
        <p className="creator-qualification-copy">
          Qualification evidence could not be verified. No evidence is rendered until the persisted artifact boundary is healthy.
        </p>
      </section>
    )
  }

  if (model.status === 'unavailable') {
    return (
      <section className="panel creator-qualification creator-qualification-error" aria-labelledby="qualification-heading" role="status">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Evidence boundary</p>
            <h2 id="qualification-heading">Persisted qualification evidence</h2>
          </div>
          <span className="creator-qualification-status qualification-status-unavailable"><CircleAlert size={14} aria-hidden="true" /> UNAVAILABLE</span>
        </div>
        <p className="creator-qualification-copy">
          No verified qualification evidence is exposed by the current read-only API. Missing evidence is not treated as rejection or promotion.
        </p>
      </section>
    )
  }

  return (
    <section className="panel creator-qualification" aria-labelledby="qualification-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Evidence boundary</p>
          <h2 id="qualification-heading">Persisted qualification evidence</h2>
        </div>
        <span className="creator-qualification-status qualification-status-verified"><FileCheck2 size={14} aria-hidden="true" /> EVIDENCE VERIFIED</span>
      </div>
      <p className="creator-qualification-copy">
        Qualification is a persisted OOS evidence outcome only. It does not promote, activate, or authorize execution.
      </p>
      <div className="creator-qualification-meta" aria-label="Qualification evidence summary">
        <div><span className="field-label">Candidates</span><strong>{model.candidateCount ?? '—'}</strong></div>
        <div><span className="field-label">Evidence artifacts</span><strong>{model.qualificationCount ?? '—'}</strong></div>
        <div><span className="field-label">Missing evidence</span><strong>{model.missingCandidateIds.length}</strong></div>
      </div>
      {model.qualifications.length > 0 ? (
        <div className="creator-qualification-list">
          {model.qualifications.map((summary) => <QualificationCard key={summary.candidateId} summary={summary} />)}
        </div>
      ) : (
        <div className="creator-qualification-empty" role="status">
          <CircleAlert size={18} aria-hidden="true" />
          <span>No persisted qualification artifact is available for this registry.</span>
        </div>
      )}
      <div className="creator-qualification-boundary">
        <span>Evidence only</span>
        <span>Promotion: unpromoted</span>
        <span>Execution authority: off</span>
      </div>
    </section>
  )
}

export function CreatorPage({ model, qualification }: CreatorPageProps) {
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

      {model.candidateAvailability === 'available'
        ? <CandidateRegistry model={model} />
        : <UnavailableCreatorOutput model={model} />}
      <QualificationEvidence model={qualification} />
    </div>
  )
}
