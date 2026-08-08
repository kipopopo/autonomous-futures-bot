import { BadgeCheck, CircleAlert, DatabaseZap, FileCheck2, ListChecks, LockKeyhole, ShieldCheck } from 'lucide-react'

import type { LearnerEvidenceStatus, LearnerModel } from '@/lib/learner'

function shortHash(value: string | null): string {
  if (!value) return '—'
  return `${value.slice(0, 12)}…${value.slice(-8)}`
}

function formatMyt(value: string | null): string {
  if (!value) return '—'
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

function statusLabel(status: LearnerEvidenceStatus): string {
  if (status === 'verified') return 'VERIFIED'
  if (status === 'integrity_unavailable') return 'INTEGRITY UNAVAILABLE'
  return 'UNAVAILABLE'
}

function qualificationDecisionLabel(decision: 'qualified' | 'rejected'): string {
  return decision === 'qualified' ? 'QUALIFIED' : 'REJECTED'
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

function EvidenceState({ status, title, detail }: { status: LearnerEvidenceStatus; title: string; detail: string }) {
  return (
    <div className={`learner-evidence-state learner-evidence-state-${status}`} role="status">
      <span className="learner-evidence-state-label">{statusLabel(status)}</span>
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  )
}

export function LearnerPage({ model }: { model: LearnerModel }) {
  const verified = model.status === 'verified'
  const artifact = model.learnerArtifact
  const run = model.learnerRun
  const trainingEvidence = model.trainingEvidence
  const qualityReview = model.qualityReview
  const qualification = model.qualification

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
        This page reports verified learner evidence only. It does not start training or claim model quality,
        promotion, paper activation, or live execution.
      </p>

      <div className="learner-readiness-grid" aria-label="Learner readiness summary">
        <ReadinessFact
          label="Data foundation"
          value={verified ? 'VERIFIED' : 'UNAVAILABLE'}
          detail={verified ? 'Registry-bound causal bundle' : 'No verified bundle connected'}
        />
        <ReadinessFact
          label="Learner artifact"
          value={statusLabel(model.learnerArtifactStatus)}
          detail={artifact ? 'Persisted model metadata verified' : 'No verified artifact evidence'}
        />
        <ReadinessFact
          label="Learning run"
          value={statusLabel(model.learningRunStatus)}
          detail={run ? 'Prepared provenance verified' : 'No verified run evidence'}
        />
        <ReadinessFact
          label="Training completion proof"
          value={statusLabel(model.trainingCompletionStatus)}
          detail={trainingEvidence ? 'Output file and evidence hashes verified' : 'No verified completion proof'}
        />
        <ReadinessFact label="Paper activation" value="OFF" detail="Activation is not available here" />
        <ReadinessFact
          label="Qualification evidence"
          value={qualification ? qualificationDecisionLabel(qualification.decision) : statusLabel(model.qualificationStatus)}
          detail={qualification ? 'Persisted gates only — not promotion' : 'No verified qualification evidence'}
        />
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

      <div className="learner-evidence-grid" aria-label="Persisted learner evidence">
        <section className="learner-evidence-card" aria-labelledby="learner-artifact-evidence-heading">
          <div className="learner-subsection-heading">
            <div>
              <span className="field-label">Phase 3f output boundary</span>
              <h3 id="learner-artifact-evidence-heading">Learner artifact evidence</h3>
            </div>
            <FileCheck2 size={19} aria-hidden="true" />
          </div>
          {artifact ? (
            <div className="learner-evidence-details">
              <div><span className="field-label">Identity</span><strong>{artifact.learnerId} · {artifact.learnerVersion}</strong></div>
              <div><span className="field-label">Model family</span><strong>{artifact.modelFamily}</strong></div>
              <div><span className="field-label">Model SHA-256</span><code title={artifact.modelArtifactHash}>{shortHash(artifact.modelArtifactHash)}</code></div>
              <div><span className="field-label">Artifact SHA-256</span><code title={artifact.artifactHash}>{shortHash(artifact.artifactHash)}</code></div>
              <div><span className="field-label">Training window</span><strong>{formatMyt(artifact.trainingWindowStart)} → {formatMyt(artifact.trainingWindowEnd)}</strong></div>
              <div><span className="field-label">Safety state</span><strong>{artifact.state} · {artifact.promotionState}</strong></div>
            </div>
          ) : (
            <EvidenceState
              status={model.learnerArtifactStatus}
              title="No persisted artifact is rendered"
              detail="The API did not provide verified learner artifact metadata."
            />
          )}
        </section>

        <section className="learner-evidence-card" aria-labelledby="learner-run-evidence-heading">
          <div className="learner-subsection-heading">
            <div>
              <span className="field-label">Phase 3e provenance boundary</span>
              <h3 id="learner-run-evidence-heading">Prepared learner run evidence</h3>
            </div>
            <ListChecks size={19} aria-hidden="true" />
          </div>
          {run ? (
            <div className="learner-evidence-details">
              <div><span className="field-label">Run identity</span><strong>{run.runId}</strong></div>
              <div><span className="field-label">Status</span><strong>{run.status}</strong></div>
              <div><span className="field-label">Run SHA-256</span><code title={run.runHash}>{shortHash(run.runHash)}</code></div>
              <div><span className="field-label">Input windows</span><strong>{run.inputWindowIds.length} · {run.inputSymbols.join(', ')}</strong></div>
              <div><span className="field-label">Training window</span><strong>{formatMyt(run.trainingWindowStart)} → {formatMyt(run.trainingWindowEnd)}</strong></div>
              <div><span className="field-label">Output / metrics</span><strong>UNAVAILABLE · UNAVAILABLE</strong></div>
            </div>
          ) : (
            <EvidenceState
              status={model.learningRunStatus}
              title="No persisted run is rendered"
              detail="Prepared provenance appears only after its hash and artifact binding verify."
            />
          )}
        </section>

        <section className="learner-evidence-card" aria-labelledby="learner-training-evidence-heading">
          <div className="learner-subsection-heading">
            <div>
              <span className="field-label">Phase 3l evidence boundary</span>
              <h3 id="learner-training-evidence-heading">Training completion proof</h3>
            </div>
            <BadgeCheck size={19} aria-hidden="true" />
          </div>
          {trainingEvidence ? (
            <div className="learner-evidence-details">
              <div><span className="field-label">Plain meaning</span><strong>Trainer output was saved and verified</strong></div>
              <div><span className="field-label">Status</span><strong>COMPLETED · PROVENANCE ONLY</strong></div>
              <div><span className="field-label">Model version / family</span><strong>{trainingEvidence.learnerVersion} · {trainingEvidence.modelFamily}</strong></div>
              <div><span className="field-label">Recorded at</span><strong>{formatMyt(trainingEvidence.completedAt)}</strong></div>
              <div><span className="field-label">Output file SHA-256</span><code title={trainingEvidence.outputArtifactHash}>{shortHash(trainingEvidence.outputArtifactHash)}</code></div>
              <div><span className="field-label">Evidence SHA-256</span><code title={trainingEvidence.evidenceHash}>{shortHash(trainingEvidence.evidenceHash)}</code></div>
              <div><span className="field-label">What this does not prove</span><strong>Quality, profitability, promotion, or trading permission</strong></div>
            </div>
          ) : (
            <EvidenceState
              status={model.trainingCompletionStatus}
              title="No completed-training proof is rendered"
              detail="This page will not invent progress, metrics, or a model result when the API has no verified evidence."
            />
          )}
        </section>

        <section className="learner-evidence-card" aria-labelledby="learner-quality-review-heading">
          <div className="learner-subsection-heading">
            <div>
              <span className="field-label">Phase 3m observation boundary</span>
              <h3 id="learner-quality-review-heading">Holdout quality review</h3>
            </div>
            <ListChecks size={19} aria-hidden="true" />
          </div>
          {qualityReview ? (
            <div className="learner-evidence-details">
              <div><span className="field-label">Plain meaning</span><strong>Reviewer observation recorded</strong></div>
              <div><span className="field-label">Status</span><strong>OBSERVED ONLY · NO QUALIFICATION DECISION</strong></div>
              <div><span className="field-label">Review / version</span><strong>{qualityReview.reviewRunId} · {qualityReview.reviewVersion}</strong></div>
              <div><span className="field-label">Split</span><strong>{qualityReview.split} · cached-only</strong></div>
              <div className="learner-quality-window-list">
                <span className="field-label">Observed holdout windows</span>
                {qualityReview.windows.map((window) => (
                  <div className="learner-quality-window" key={window.windowId}>
                    <strong>{window.windowId} · {window.symbol}</strong>
                    <span>{window.rowsEvaluated} rows · {window.metrics.map((metric) => `${metric.metricId}: ${metric.value}`).join(' · ')}</span>
                  </div>
                ))}
              </div>
              <div><span className="field-label">Reviewed at</span><strong>{formatMyt(qualityReview.reviewedAt)}</strong></div>
              <div><span className="field-label">Review SHA-256</span><code title={qualityReview.reviewHash}>{shortHash(qualityReview.reviewHash)}</code></div>
              <div><span className="field-label">Safety state</span><strong>{qualityReview.promotionState} · execution authority off</strong></div>
            </div>
          ) : (
            <EvidenceState
              status={model.qualityReviewStatus}
              title="No quality-review evidence is rendered"
              detail="The page will not infer model quality or qualification when the review endpoint is unavailable."
            />
          )}
        </section>

        <section className="learner-evidence-card learner-qualification-card" aria-labelledby="learner-qualification-heading">
          <div className="learner-subsection-heading">
            <div>
              <span className="field-label">Phase 3o evidence boundary</span>
              <h3 id="learner-qualification-heading">Learner qualification evidence</h3>
            </div>
            <ShieldCheck size={19} aria-hidden="true" />
          </div>
          {qualification ? (
            <div className="learner-evidence-details">
              <div className={`learner-qualification-result learner-qualification-${qualification.decision}`}>
                <span className="field-label">Decision</span>
                <strong>{qualificationDecisionLabel(qualification.decision)}</strong>
                <span>EVIDENCE ONLY — NOT PROMOTION</span>
              </div>
              <div>
                <span className="field-label">Policy</span>
                <strong>{qualification.policyId}</strong>
              </div>
              <div>
                <span className="field-label">Windows evaluated</span>
                <strong>{qualification.windowsEvaluated}</strong>
              </div>
              <div>
                <span className="field-label">Evaluated at</span>
                <strong>{formatMyt(qualification.evaluatedAt)}</strong>
              </div>
              <div className="learner-qualification-list">
                <span className="field-label">Persisted metric observations</span>
                {qualification.metrics.map((metric) => (
                  <div className="learner-qualification-row" key={`${metric.windowId}-${metric.metricId}`}>
                    <strong>{metric.windowId} · {metric.metricId}</strong>
                    <span>{metric.observed ?? '—'}</span>
                  </div>
                ))}
              </div>
              <div className="learner-qualification-list">
                <span className="field-label">Persisted gate results</span>
                {qualification.gates.map((gate) => (
                  <div className="learner-qualification-row" key={gate.gateId}>
                    <strong>{gate.gateId}</strong>
                    <span>{gate.passed ? 'PASSED' : 'FAILED'} · {gate.reasonCode}</span>
                  </div>
                ))}
              </div>
              <div><span className="field-label">Policy SHA-256</span><code title={qualification.policyHash}>{shortHash(qualification.policyHash)}</code></div>
              <div><span className="field-label">Qualification SHA-256</span><code title={qualification.qualificationHash}>{shortHash(qualification.qualificationHash)}</code></div>
              <div><span className="field-label">Safety state</span><strong>{qualification.promotionState} · execution authority off</strong></div>
            </div>
          ) : (
            <EvidenceState
              status={model.qualificationStatus}
              title="No learner qualification evidence is rendered"
              detail="Qualification is unavailable or failed integrity verification; no decision is inferred."
            />
          )}
        </section>
      </div>

      <div className="learner-safety-boundary" aria-label="Learner safety boundary">
        <span><ShieldCheck size={14} aria-hidden="true" /> Evidence/readiness only</span>
        <span><LockKeyhole size={14} aria-hidden="true" /> Execution authority: off</span>
        <span>Paper activation: off</span>
      </div>
    </section>
  )
}
