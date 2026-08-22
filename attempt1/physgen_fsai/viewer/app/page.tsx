'use client';

import { useEffect, useMemo, useState } from 'react';

type Asset = {
  url: string;
  source: string;
  sha256: string;
  sizeBytes: number;
};

type Metric = {
  label: string;
  value: number;
  unit: string;
  tone: string;
};

type Model = {
  id: string;
  name: string;
  type: string;
  version: string;
  learned: boolean;
  responsibility: string;
};

type Stage = {
  id: string;
  order: number;
  phase: string;
  label: string;
  modelId: string;
  status: string;
  image: Asset;
  supportingImages: Asset[];
  justification: string;
  alteration: {
    scope: string;
    before: string;
    after: string;
    summary: string;
  };
  metrics: Metric[];
  evidence: string[];
};

type Candidate = {
  id: string;
  name: string;
  role: string;
  status: string;
  eligible: boolean;
  image: Asset;
  metrics: Metric[];
  rawMetrics: Record<string, number | boolean>;
  verdict: string;
};

type Repair = {
  id: string;
  status: string;
  modelId: string;
  title: string;
  diagnosis: string;
  change: string;
  before: unknown;
  after: unknown;
};

type ViewerData = {
  schemaVersion: string;
  run: {
    id: string;
    title: string;
    subtitle: string;
    issue: number;
    status: string;
    offline: boolean;
    learnedInferenceUsed: boolean;
    wallSeconds: number;
    peakRssBytes: number;
    sourceAssemblySha256: string;
  };
  models: Model[];
  stages: Stage[];
  candidates: Candidate[];
  repairs: Repair[];
  warnings: string[];
};

function compactNumber(value: number) {
  const absolute = Math.abs(value);
  if ((absolute > 0 && absolute < 0.001) || absolute >= 1_000_000) {
    return value.toExponential(3);
  }
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: absolute < 10 ? 4 : 2,
  }).format(value);
}

function statusLabel(status: string) {
  return status.replaceAll('-', ' ');
}

function evidenceValue(value: unknown) {
  if (value === null || value === undefined) return 'Pending';
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return compactNumber(value);
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key.replace(/([A-Z])/g, ' $1')}: ${typeof item === 'number' ? compactNumber(item) : String(item)}`)
      .join(' · ');
  }
  return String(value);
}

const comparisonMetrics = [
  { key: 'material_fraction', label: 'Material fraction', unit: '' },
  { key: 'compliance_n_mm', label: 'Compliance', unit: 'N·mm' },
  { key: 'max_displacement_mm', label: 'Max displacement', unit: 'mm' },
  { key: 'max_von_mises_mpa', label: 'Max von Mises', unit: 'MPa' },
] as const;

export default function Home() {
  const [data, setData] = useState<ViewerData | null>(null);
  const [error, setError] = useState('');
  const [activeStageId, setActiveStageId] = useState('vehicle-context');
  const [activeImage, setActiveImage] = useState<Asset | null>(null);
  const [leftCandidateId, setLeftCandidateId] = useState('baseline-full-plate');
  const [rightCandidateId, setRightCandidateId] = useState('candidate-braced');

  useEffect(() => {
    let cancelled = false;
    fetch('/data/viewer-data.json', { cache: 'no-store' })
      .then((response) => {
        if (!response.ok) throw new Error(`viewer data returned ${response.status}`);
        return response.json() as Promise<ViewerData>;
      })
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setActiveStageId(payload.stages[0]?.id ?? '');
        setActiveImage(payload.stages[0]?.image ?? null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const stage = useMemo(
    () => data?.stages.find((item) => item.id === activeStageId) ?? data?.stages[0],
    [activeStageId, data],
  );
  const model = data?.models.find((item) => item.id === stage?.modelId);
  const leftCandidate = data?.candidates.find((item) => item.id === leftCandidateId) ?? data?.candidates[0];
  const rightCandidate = data?.candidates.find((item) => item.id === rightCandidateId) ?? data?.candidates[1];

  useEffect(() => {
    if (stage) setActiveImage(stage.image);
  }, [stage]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!data || !stage || !['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) return;
      const direction = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : -1;
      const current = data.stages.findIndex((item) => item.id === stage.id);
      const next = (current + direction + data.stages.length) % data.stages.length;
      setActiveStageId(data.stages[next].id);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [data, stage]);

  if (error) {
    return (
      <main className="load-state error-state">
        <p className="eyebrow">Viewer data unavailable</p>
        <h1>The FS-AI evidence bundle could not be loaded.</h1>
        <code>{error}</code>
      </main>
    );
  }

  if (!data || !stage || !model || !activeImage) {
    return (
      <main className="load-state">
        <span className="spinner" aria-hidden="true" />
        <p>Loading local FS-AI evidence…</p>
      </main>
    );
  }

  const gallery = [stage.image, ...stage.supportingImages];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark">N</span>
          <div>
            <p className="eyebrow">Nightshift / PhysGen FS-AI</p>
            <p className="brand-subline">Evidence console</p>
          </div>
        </div>
        <nav className="topnav" aria-label="Viewer sections">
          <a href="#progression">Progression</a>
          <a href="#compare">Compare</a>
          <a href="#repairs">Repairs</a>
        </nav>
        <div className="run-health">
          <span className="live-dot" aria-hidden="true" />
          <span>Local replay</span>
          <span className="divider" />
          <span>Issue #{data.run.issue}</span>
          <span className="divider" />
          <span>{data.run.wallSeconds.toFixed(2)} s</span>
        </div>
      </header>

      <section className="run-banner">
        <div>
          <p className="eyebrow">Actual CAD + deterministic evidence</p>
          <h1>{data.run.title}</h1>
          <p className="run-subtitle">{data.run.subtitle}</p>
        </div>
        <div className="run-verdict">
          <span>Run state</span>
          <strong>{statusLabel(data.run.status)}</strong>
          <small>{data.run.learnedInferenceUsed ? 'Learned inference used' : 'Deterministic fallback · no learned inference'}</small>
        </div>
      </section>

      <section className="workspace" id="progression">
        <aside className="stage-rail" aria-label="Progression stages">
          <div className="rail-heading">
            <span>Progression</span>
            <kbd>↑ ↓</kbd>
          </div>
          <ol>
            {data.stages.map((item) => {
              const selected = item.id === stage.id;
              return (
                <li key={item.id}>
                  <button
                    className={selected ? 'stage-button selected' : 'stage-button'}
                    onClick={() => setActiveStageId(item.id)}
                    aria-current={selected ? 'step' : undefined}
                  >
                    <span className="stage-index">{String(item.order).padStart(2, '0')}</span>
                    <span className="stage-copy">
                      <small>{item.phase}</small>
                      <strong>{item.label}</strong>
                    </span>
                    <span className={`stage-state state-${item.status}`} title={statusLabel(item.status)} />
                  </button>
                </li>
              );
            })}
          </ol>
        </aside>

        <article className="stage-detail">
          <div className="visual-panel">
            <div className="visual-toolbar">
              <div>
                <span className="phase-tag">{stage.phase}</span>
                <span className={`status-chip status-${stage.status}`}>{statusLabel(stage.status)}</span>
              </div>
              <span className="artifact-sha">sha {activeImage.sha256.slice(0, 12)}</span>
            </div>
            <div className="hero-image-wrap">
              <img src={activeImage.url} alt={`${stage.label} evidence`} className="hero-image" />
              <div className="image-caption">
                <span>Actual saved artifact</span>
                <code>{activeImage.source}</code>
              </div>
            </div>
            {gallery.length > 1 && (
              <div className="gallery-strip" aria-label="Stage image views">
                {gallery.map((image, index) => (
                  <button
                    key={image.sha256}
                    onClick={() => setActiveImage(image)}
                    className={image.sha256 === activeImage.sha256 ? 'thumb selected' : 'thumb'}
                    aria-label={`Open view ${index + 1}`}
                  >
                    <img src={image.url} alt="" />
                    <span>View {index + 1}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="detail-copy">
            <div className="stage-title-row">
              <div>
                <p className="eyebrow">Step {String(stage.order).padStart(2, '0')}</p>
                <h2>{stage.label}</h2>
              </div>
              <span className="stage-count">{stage.order} / {data.stages.length}</span>
            </div>

            <section className="model-card">
              <div className="model-icon">{model.learned ? 'AI' : 'D'}</div>
              <div>
                <p className="eyebrow">Model responsible</p>
                <h3>{model.name}</h3>
                <p>{model.type} · {model.version.slice(0, 12)}</p>
              </div>
              <span className={model.learned ? 'learned-pill' : 'deterministic-pill'}>
                {model.learned ? 'learned' : 'deterministic'}
              </span>
            </section>

            <section className="reason-card">
              <p className="section-label">Why this stage exists</p>
              <p>{stage.justification}</p>
              <div className="responsibility">
                <span>Responsibility</span>
                <p>{model.responsibility}</p>
              </div>
            </section>

            <section className="alteration-card">
              <div className="section-heading">
                <p className="section-label">Alteration ledger</p>
                <span>{stage.alteration.scope}</span>
              </div>
              <div className="before-after">
                <div><span>Before</span><strong>{stage.alteration.before}</strong></div>
                <span className="flow-arrow">→</span>
                <div><span>After</span><strong>{stage.alteration.after}</strong></div>
              </div>
              <p className="alteration-summary">{stage.alteration.summary}</p>
            </section>

            <section className="metrics-card">
              <p className="section-label">Measured at this stage</p>
              <div className="metric-grid">
                {stage.metrics.map((item) => (
                  <div key={item.label} className="metric">
                    <span>{item.label}</span>
                    <strong>{compactNumber(item.value)} <small>{item.unit}</small></strong>
                  </div>
                ))}
              </div>
            </section>

            <details className="evidence-card">
              <summary>Evidence references <span>{stage.evidence.length}</span></summary>
              <ul>
                {stage.evidence.map((path) => <li key={path}><code>{path}</code></li>)}
              </ul>
            </details>
          </div>
        </article>
      </section>

      {leftCandidate && rightCandidate && (
        <section className="content-section" id="compare">
          <div className="content-heading">
            <div>
              <p className="eyebrow">Candidate inspection</p>
              <h2>Compare what changed, not just who won.</h2>
            </div>
            <p>Every option used the same corrected annulus fixture. Failed and ineligible fields remain visible.</p>
          </div>

          <div className="compare-controls">
            <label>
              <span>Reference A</span>
              <select value={leftCandidateId} onChange={(event) => setLeftCandidateId(event.target.value)}>
                {data.candidates.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.name}</option>)}
              </select>
            </label>
            <span className="versus">A / B</span>
            <label>
              <span>Candidate B</span>
              <select value={rightCandidateId} onChange={(event) => setRightCandidateId(event.target.value)}>
                {data.candidates.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.name}</option>)}
              </select>
            </label>
          </div>

          <div className="candidate-grid">
            {[leftCandidate, rightCandidate].map((candidate, index) => (
              <article className={`candidate-card candidate-${candidate.status}`} key={`${index}-${candidate.id}`}>
                <div className="candidate-image-wrap">
                  <img src={candidate.image.url} alt={`${candidate.name} structural field`} />
                  <span className="candidate-letter">{index === 0 ? 'A' : 'B'}</span>
                </div>
                <div className="candidate-body">
                  <div className="candidate-title-row">
                    <div>
                      <p>{candidate.role}</p>
                      <h3>{candidate.name}</h3>
                    </div>
                    <span className={`candidate-status candidate-status-${candidate.status}`}>
                      {statusLabel(candidate.status)}
                    </span>
                  </div>
                  <p className="candidate-verdict">{candidate.verdict}</p>
                  <dl className="candidate-metrics">
                    {comparisonMetrics.map((metric) => {
                      const value = candidate.rawMetrics[metric.key];
                      return (
                        <div key={metric.key}>
                          <dt>{metric.label}</dt>
                          <dd>{typeof value === 'number' ? compactNumber(value) : '—'} <small>{metric.unit}</small></dd>
                        </div>
                      );
                    })}
                  </dl>
                  <code className="candidate-source">{candidate.image.source}</code>
                </div>
              </article>
            ))}
          </div>

          <div className="delta-ledger" aria-label="Candidate metric deltas">
            <div className="delta-heading">
              <span>Measured delta</span>
              <strong>B − A</strong>
            </div>
            {comparisonMetrics.map((metric) => {
              const left = leftCandidate.rawMetrics[metric.key];
              const right = rightCandidate.rawMetrics[metric.key];
              const delta = typeof left === 'number' && typeof right === 'number' ? right - left : null;
              return (
                <div className="delta-row" key={metric.key}>
                  <span>{metric.label}</span>
                  <strong className={delta !== null && delta > 0 ? 'delta-positive' : 'delta-negative'}>
                    {delta === null ? '—' : `${delta > 0 ? '+' : ''}${compactNumber(delta)}`} <small>{metric.unit}</small>
                  </strong>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="content-section" id="repairs">
        <div className="content-heading">
          <div>
            <p className="eyebrow">Repair history</p>
            <h2>Underlying issues are part of the evidence.</h2>
          </div>
          <p>Each repair records the diagnosing model, its exact intervention, and the measured before/after state.</p>
        </div>
        <div className="repair-grid">
          {data.repairs.map((repair, index) => {
            const repairModel = data.models.find((item) => item.id === repair.modelId);
            return (
              <article className={`repair-card repair-${repair.status}`} key={repair.id}>
                <div className="repair-index">R{String(index + 1).padStart(2, '0')}</div>
                <div className="repair-content">
                  <div className="repair-title-row">
                    <div>
                      <span>{repairModel?.name ?? repair.modelId}</span>
                      <h3>{repair.title}</h3>
                    </div>
                    <span className={`repair-status repair-status-${repair.status}`}>{statusLabel(repair.status)}</span>
                  </div>
                  <p className="repair-diagnosis">{repair.diagnosis}</p>
                  <div className="repair-change"><span>Intervention</span><p>{repair.change}</p></div>
                  <div className="repair-values">
                    <div><span>Before</span><strong>{evidenceValue(repair.before)}</strong></div>
                    <span aria-hidden="true">→</span>
                    <div><span>After</span><strong>{evidenceValue(repair.after)}</strong></div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="content-section model-section">
        <div className="content-heading compact-heading">
          <div>
            <p className="eyebrow">Model registry</p>
            <h2>Who changed what.</h2>
          </div>
          <p>No learned model was invoked in this captured run.</p>
        </div>
        <div className="model-registry">
          {data.models.map((item, index) => (
            <article key={item.id}>
              <div className="registry-topline">
                <span>{String(index + 1).padStart(2, '0')}</span>
                <span className={item.learned ? 'learned-pill' : 'deterministic-pill'}>{item.learned ? 'learned' : 'deterministic'}</span>
              </div>
              <h3>{item.name}</h3>
              <p className="registry-type">{item.type} · {item.version.slice(0, 16)}</p>
              <p>{item.responsibility}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="boundary-panel">
        <div>
          <p className="eyebrow">Evidence boundary</p>
          <h2>What this run does not prove</h2>
        </div>
        <ul>
          {data.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      </section>

      <footer className="viewer-footer">
        <span>Offline artifact viewer · {data.schemaVersion}</span>
        <span>Assembly sha {data.run.sourceAssemblySha256.slice(0, 16)}</span>
      </footer>
    </main>
  );
}
