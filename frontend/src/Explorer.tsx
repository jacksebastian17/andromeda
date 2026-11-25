import { useState } from 'react'
import { CalendarClock, Database, FolderSearch, Layers3, Search } from 'lucide-react'
import type { EventDetail, ResearchEvent } from './data'
import { counted, display, percent, stamp, useResource } from './data'
import { Badge, Boundary, Details, Empty, Panel, Select, Warning } from './ui'
import { Link, navigate } from './navigation'

function Lifecycle({ state }: { state: ResearchEvent['state'] }) {
  return <Badge tone={state === 'resolved' ? 'green' : 'blue'}>{state}</Badge>
}

function Inspection({ id }: { id: string }) {
  const query = useResource<EventDetail>('/events/' + encodeURIComponent(id))
  return (
    <div className="section-stack">
      <div>
        <Link className="button" href="/markets">
          Back to events
        </Link>
      </div>
      <Boundary query={query}>
        {(event) => (
          <>
            <section className="surface inspection-intro">
              <div className="badge-line">
                <Badge tone="violet">Synthetic</Badge>
                <Lifecycle state={event.state} />
              </div>
              <h2>{event.title}</h2>
              <p>{event.description}</p>
              <div className="intro-meta">
                <span>
                  <Layers3 />
                  {display(event.category)}
                </span>
                <span>
                  <CalendarClock />
                  Opens {stamp(event.opens_at)}
                </span>
                <span>Closes {stamp(event.closes_at)}</span>
              </div>
              <code>{event.id}</code>
            </section>
            <Panel title="Contracts" action={<Badge>{event.contracts.length} total</Badge>}>
              {event.contracts.length ? (
                <div className="contract-list">
                  {event.contracts.map((contract) => (
                    <article className="contract" key={contract.id}>
                      <div className="contract-header">
                        <div>
                          <h3>{contract.label}</h3>
                          <code>{contract.id}</code>
                        </div>
                        <strong className="prob-number">
                          {contract.forecast
                            ? percent(contract.forecast.probability)
                            : 'Unavailable'}
                        </strong>
                      </div>
                      {contract.issue && <Warning>Missing input · {contract.issue}</Warning>}
                      <Details
                        rows={[
                          [
                            'Resolution',
                            contract.resolution
                              ? contract.resolution.outcome
                                ? 'Yes'
                                : 'No'
                              : 'Unresolved',
                          ],
                          [
                            'Forecast quality',
                            contract.forecast ? display(contract.forecast.quality) : 'Unavailable',
                          ],
                          ...(contract.forecast
                            ? ([
                                [
                                  'Model',
                                  contract.forecast.model_id +
                                    ' · v' +
                                    contract.forecast.model_version,
                                ],
                                ['Forecast generated', stamp(contract.forecast.generated_at)],
                                ['Information cutoff', stamp(contract.forecast.cutoff_at)],
                                [
                                  'Observation references',
                                  contract.forecast.observation_ids.join(', ') || 'Unavailable',
                                ],
                              ] satisfies [string, string][])
                            : []),
                          ...(contract.resolution
                            ? ([
                                ['Resolved at', stamp(contract.resolution.resolved_at)],
                                ['Resolution available', stamp(contract.resolution.available_at)],
                                ['Resolution provenance', contract.resolution.provenance],
                              ] satisfies [string, string][])
                            : []),
                        ]}
                      />
                    </article>
                  ))}
                </div>
              ) : (
                <Empty
                  title="No contracts available"
                  text="This event has no registered contracts."
                  icon={Layers3}
                />
              )}
            </Panel>
            <Panel
              title="Source observations"
              action={<Badge>{counted(event.observations.length, 'record')}</Badge>}
            >
              {event.observations.length ? (
                <div className="observation-list">
                  {event.observations.map((observation) => (
                    <article key={observation.id}>
                      <h3>
                        <Database size={17} />
                        {observation.source}
                      </h3>
                      <p>{observation.provenance}</p>
                      <Details
                        rows={[
                          ['Observation', observation.id],
                          ['Issued', stamp(observation.issued_at)],
                          ['Available', stamp(observation.available_at)],
                          ['Ingested', stamp(observation.ingested_at)],
                          ['Sample count', observation.total],
                          [
                            'Input counts',
                            Object.entries(observation.counts)
                              .map(([key, value]) => key + ' (' + value + ')')
                              .join(', ') || 'Unavailable',
                          ],
                        ]}
                      />
                    </article>
                  ))}
                </div>
              ) : (
                <Empty
                  title="No source observations"
                  text="Forecast inputs are unavailable for this event."
                  icon={Database}
                />
              )}
            </Panel>
          </>
        )}
      </Boundary>
    </div>
  )
}

export default function Explorer({ id }: { id: string | null }) {
  const query = useResource<ResearchEvent[]>('/events', id === null)
  const [term, setTerm] = useState('')
  const [state, setState] = useState('all')
  if (id !== null) return <Inspection id={id} />
  return (
    <Boundary query={query}>
      {(events) => {
        const search = term.trim().toLowerCase()
        const rows = events.filter(
          (event) =>
            (state === 'all' || state === event.state) &&
            [
              event.id,
              event.title,
              event.category,
              ...event.contracts.flatMap((contract) => [contract.id, contract.label]),
            ].some((field) => field.toLowerCase().includes(search)),
        )
        return (
          <Panel
            title="Event directory"
            action={
              <Badge>
                {rows.length} of {counted(events.length, 'event')}
              </Badge>
            }
          >
            <div className="filter-bar">
              <label className="search">
                <Search size={17} />
                <input
                  type="search"
                  aria-label="Search events and contracts"
                  placeholder="Search events and contracts"
                  value={term}
                  onChange={(e) => setTerm(e.target.value)}
                />
              </label>
              <Select label="Lifecycle filter" value={state} onChange={setState}>
                <option value="all">All lifecycles</option>
                <option value="resolved">Resolved</option>
                <option value="unresolved">Unresolved</option>
              </Select>
            </div>
            {rows.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>Category</th>
                      <th>Lifecycle</th>
                      <th>Contracts</th>
                      <th>Data quality</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((event) => {
                      const missing = event.contracts.filter(
                        (contract) => !contract.forecast,
                      ).length
                      return (
                        <tr key={event.id}>
                          <td>
                            <button
                              className="event-button"
                              onClick={() =>
                                navigate('/markets?event=' + encodeURIComponent(event.id))
                              }
                            >
                              {event.title}
                            </button>
                            <code className="subline">{event.id}</code>
                          </td>
                          <td className="capitalize">{display(event.category)}</td>
                          <td>
                            <Lifecycle state={event.state} />
                          </td>
                          <td className="numeric">{event.contracts.length}</td>
                          <td>
                            {missing ? (
                              <Badge tone="amber">{missing} missing</Badge>
                            ) : (
                              <Badge tone={event.contracts.length ? 'green' : 'neutral'}>
                                {event.contracts.length ? 'Complete' : 'Unavailable'}
                              </Badge>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty
                icon={FolderSearch}
                title={events.length ? 'No matching events' : 'No events available'}
                text={
                  events.length
                    ? 'Try a different search or lifecycle.'
                    : 'Ingest the synthetic fixture to populate the directory.'
                }
              />
            )}
          </Panel>
        )
      }}
    </Boundary>
  )
}
