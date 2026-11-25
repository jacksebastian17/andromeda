import { useState } from 'react'
import {
  Activity as ActivityIcon,
  Blocks,
  ChartColumn,
  CircleCheck,
  Database,
  Focus,
  Layers3,
  Timer,
  Wallet,
} from 'lucide-react'
import { Badge, Boundary, Empty, Metric, Panel, Select } from './ui'
import { counted, display, money, percent, stamp, uptime, useResource } from './data'
import type { Counts, Health, Overview, ResearchEvent } from './data'
import { Link } from './navigation'

function ProbabilityChart({ events }: { events: ResearchEvent[] }) {
  const [selected, setSelected] = useState('')
  const event =
    events.find((item) => item.id === selected) ??
    events.find(
      (item) => item.contracts.length > 1 && item.contracts.every((contract) => contract.forecast),
    ) ??
    events[0]
  return (
    <Panel
      title="Forecast probabilities"
      className="probabilities"
      action={<Badge tone="violet">Synthetic</Badge>}
    >
      {event ? (
        <div className="chart-body">
          <Select label="Chart event" value={event.id} onChange={setSelected}>
            {events.map((item) => (
              <option value={item.id} key={item.id}>
                {item.title}
              </option>
            ))}
          </Select>
          {event.contracts.length ? (
            <div className="chart-scroll">
              <div
                className="prob-chart"
                style={{ minWidth: Math.max(260, event.contracts.length * 82) }}
              >
                <div className="chart-ticks" aria-hidden="true">
                  {[100, 75, 50, 25, 0].map((tick) => (
                    <span key={tick}>{tick}%</span>
                  ))}
                </div>
                <div className="bar-grid">
                  {event.contracts.map((contract) => (
                    <div className="bar-col" key={contract.id}>
                      <div className="bar-track">
                        <div
                          className={'bar' + (contract.forecast ? '' : ' no-value')}
                          style={{ height: (contract.forecast?.probability ?? 0) * 100 + '%' }}
                        >
                          <span className="bar-value">
                            {contract.forecast ? percent(contract.forecast.probability) : 'Missing'}
                          </span>
                        </div>
                      </div>
                      <span className="bar-label">{contract.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <Empty
              title="No contracts available"
              text="The event has no registered contracts."
              icon={ChartColumn}
            />
          )}
          <div className="chart-legend">
            <span className="legend-key" />
            Forecast probability
            <Link href={'/markets?event=' + encodeURIComponent(event.id)}>Inspect event</Link>
          </div>
        </div>
      ) : (
        <Empty
          title="No forecasts available"
          text="Ingest the synthetic fixture to inspect contract probabilities."
          icon={ChartColumn}
        />
      )}
    </Panel>
  )
}
export function Coverage({ counts }: { counts: Counts }) {
  const awaitingEvaluation =
    counts.forecasts - counts.evaluated_forecasts - counts.unresolved_forecasts
  const rows = [
    { label: 'Evaluated forecasts', value: counts.evaluated_forecasts, color: 'violet' },
    { label: 'Awaiting resolution', value: counts.unresolved_forecasts, color: 'blue' },
    ...(awaitingEvaluation > 0
      ? [{ label: 'Awaiting evaluation', value: awaitingEvaluation, color: 'mint' }]
      : []),
    { label: 'Missing forecasts', value: counts.missing_forecasts, color: 'amber' },
    { label: 'Invalid forecasts', value: counts.invalid_forecasts, color: 'red' },
  ]
  return (
    <Panel title="Forecast coverage">
      <div className="coverage-body">
        <div className="coverage-bar" aria-hidden="true">
          {rows
            .filter((row) => row.value > 0)
            .map((row) => (
              <div key={row.label} className={row.color} style={{ flex: row.value }} />
            ))}
        </div>
        <dl className="coverage-list">
          {rows.map((row) => (
            <div key={row.label}>
              <dt>
                <i className={'swatch ' + row.color} />
                {row.label}
              </dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Panel>
  )
}
function Runtime({ health }: { health: Health }) {
  return (
    <Panel
      title="Runtime status"
      action={
        <Link className="text-link" href="/health">
          View health
        </Link>
      }
    >
      <div className="runtime-rows">
        <div>
          <span>
            <ActivityIcon />
            Backend
          </span>
          <Badge tone="green">Connected</Badge>
        </div>
        <div>
          <span>
            <Database />
            Database
          </span>
          <b>{display(health.database)}</b>
        </div>
        <div>
          <span>
            <Blocks />
            Synthetic source
          </span>
          <Badge tone={health.source_status === 'ready' ? 'green' : 'amber'}>
            {display(health.source_status)}
          </Badge>
        </div>
        <div>
          <span>
            <Timer />
            Process uptime
          </span>
          <b className="numeric">{uptime(health.uptime_seconds)}</b>
        </div>
      </div>
      <div className="runtime-foot">
        Latest ingestion <time>{stamp(health.last_ingestion_at)}</time>
      </div>
    </Panel>
  )
}
export default function OverviewPage({ health }: { health: Health }) {
  const summary = useResource<Overview>('/overview')
  const events = useResource<ResearchEvent[]>('/events')
  return (
    <Boundary query={summary}>
      {(data) => (
        <div className="section-stack">
          <div className="metrics">
            <Metric
              label="Research events"
              value={data.counts.events}
              note={counted(data.counts.contracts, 'associated contract')}
              icon={Layers3}
            />
            <Metric
              label="Forecasts"
              value={data.counts.forecasts}
              note={counted(data.counts.evaluated_forecasts, 'evaluated forecast')}
              icon={Focus}
              tone="blue"
            />
            <Metric
              label="Mean Brier score"
              value={data.mean_brier?.toFixed(4) ?? 'Unavailable'}
              note="Binary score · lower is better"
              icon={ChartColumn}
            />
            <Metric
              label="Paper cash"
              value={data.portfolio ? money(data.portfolio.current_cash) : 'Unavailable'}
              note={
                data.portfolio
                  ? counted(data.portfolio.open_positions, 'open position')
                  : 'Portfolio uninitialized'
              }
              icon={Wallet}
              tone="green"
            />
          </div>
          <div className="dashboard-grid">
            <Boundary query={events}>{(items) => <ProbabilityChart events={items} />}</Boundary>
            <Runtime health={health} />
          </div>
          <div className="dashboard-grid">
            <Panel
              title="Research activity"
              action={<Badge>{counted(data.activity.length, 'record')}</Badge>}
            >
              {data.activity.length ? (
                <ol className="activity-list">
                  {data.activity.map((item, index) => (
                    <li key={item.kind + item.at + index}>
                      <span className="activity-icon">
                        {item.kind.includes('eval') ? (
                          <CircleCheck size={17} />
                        ) : (
                          <Database size={17} />
                        )}
                      </span>
                      <div>
                        <h3>{display(item.kind)}</h3>
                        <p>{item.description}</p>
                      </div>
                      <time dateTime={item.at}>{stamp(item.at)}</time>
                    </li>
                  ))}
                </ol>
              ) : (
                <Empty
                  icon={ActivityIcon}
                  title="No research activity"
                  text="Ingestion and evaluation activity will appear here."
                />
              )}
            </Panel>
            <Coverage counts={data.counts} />
          </div>
        </div>
      )}
    </Boundary>
  )
}
