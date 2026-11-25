import { BookOpen, Boxes, ChartColumn, FlaskConical, Hourglass, Layers3 } from 'lucide-react'
import type { Evaluations, Model } from './data'
import { counted, display, percent, stamp, useResource } from './data'
import { Badge, Boundary, Empty, Metric, Panel } from './ui'
import { Link } from './navigation'

export default function Research() {
  const models = useResource<Model[]>('/research/models')
  const evaluations = useResource<Evaluations>('/research/evaluations')
  return (
    <div className="section-stack">
      <Boundary query={evaluations}>
        {(data) => (
          <div className="metrics">
            <Metric
              label="Mean Brier score"
              value={data.mean_brier?.toFixed(4) ?? 'Unavailable'}
              note="Arithmetic mean per scored contract"
              icon={ChartColumn}
            />
            <Metric
              label="Evaluated forecasts"
              value={data.counts.evaluated_forecasts}
              note={
                counted(new Set(data.records.map((row) => row.event_id)).size, 'scored event') +
                ' · ' +
                data.counts.resolved_events +
                ' resolved total'
              }
              icon={Layers3}
              tone="blue"
            />
            <Metric
              label="Unresolved forecasts"
              value={data.counts.unresolved_forecasts}
              note="Awaiting synthetic outcomes"
              icon={Hourglass}
            />
            <Metric
              label="Missing forecasts"
              value={data.counts.missing_forecasts}
              note={counted(data.counts.invalid_forecasts, 'invalid forecast')}
              icon={Boxes}
              tone="amber"
            />
          </div>
        )}
      </Boundary>
      <div className="dashboard-grid">
        <Panel title="Research models">
          <Boundary query={models}>
            {(items) =>
              items.length ? (
                <div className="model-list">
                  {items.map((model) => (
                    <article key={model.id + model.version}>
                      <div className="model-line">
                        <span className="model-icon">
                          <FlaskConical size={21} />
                        </span>
                        <div>
                          <h3>{model.id}</h3>
                          <code>Version {model.version}</code>
                        </div>
                        <Badge tone="violet">{display(model.status)}</Badge>
                      </div>
                      <p>{model.description}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <Empty
                  icon={FlaskConical}
                  title="No models registered"
                  text="Ingest the synthetic fixture to register its research model."
                />
              )
            }
          </Boundary>
        </Panel>
        <Panel title="Evaluation method">
          <div className="method">
            <code>Brier = (p − y)²</code>
            <p>
              Each resolved contract receives a binary score. Contracts within an event share an
              outcome structure and can be statistically dependent.
            </p>
          </div>
        </Panel>
      </div>
      <Panel title="Forecast evaluations">
        <Boundary query={evaluations}>
          {(data) =>
            data.records.length ? (
              <>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Event / contract</th>
                        <th>Forecast</th>
                        <th>Outcome</th>
                        <th>Brier score</th>
                        <th>Evaluated at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.records.map((record) => (
                        <tr key={record.id}>
                          <td>
                            <Link
                              className="row-link"
                              href={'/markets?event=' + encodeURIComponent(record.event_id)}
                            >
                              {record.event_title}
                            </Link>
                            <span className="subline">{record.contract_label}</span>
                          </td>
                          <td className="numeric">{percent(record.probability)}</td>
                          <td>
                            <Badge tone={record.outcome ? 'green' : 'neutral'}>
                              {record.outcome ? 'Yes' : 'No'}
                            </Badge>
                          </td>
                          <td className="numeric score-cell">{record.score.toFixed(4)}</td>
                          <td className="date-cell">{stamp(record.evaluated_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <Empty
                icon={BookOpen}
                title="No scored forecasts"
                text="Resolved contracts with eligible forecasts will receive scores."
              />
            )
          }
        </Boundary>
      </Panel>
      <section className="research-note">
        <BookOpen size={18} />
        <div>
          <h2>Research limitations</h2>
          <p>
            This deterministic fixture exercises the evaluation workflow. The scores provide no
            evidence of predictive skill or economic returns. Market calibration, structural
            consistency and cross-market valuation remain future research.
          </p>
        </div>
      </section>
    </div>
  )
}
