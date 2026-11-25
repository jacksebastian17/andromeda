import { Activity, CircleCheck, Clock3, Database, Radio } from 'lucide-react'
import type { Health } from './data'
import { counted, display, stamp, uptime } from './data'
import { Badge, Details, Empty, Metric, Panel, Warning } from './ui'

export default function HealthPage({ data }: { data: Health }) {
  return (
    <div className="section-stack">
      <div className="metrics">
        <Metric
          label="Backend"
          value="Connected"
          note={'Application v' + data.version}
          icon={Activity}
          tone="green"
        />
        <Metric
          label="Database"
          value={display(data.database)}
          note="SQLite persistence"
          icon={Database}
          tone={data.database === 'connected' ? 'blue' : 'amber'}
        />
        <Metric
          label="Runtime uptime"
          value={uptime(data.uptime_seconds)}
          note="Current backend process"
          icon={Clock3}
        />
        <Metric
          label="Synthetic source"
          value={display(data.source_status)}
          note={
            data.missing_inputs === null
              ? 'Input availability unknown'
              : counted(data.missing_inputs, 'missing input')
          }
          icon={Radio}
          tone={data.source_status === 'ready' ? 'green' : 'amber'}
        />
      </div>
      <div className="dashboard-grid equal">
        <Panel title="Runtime diagnostics">
          <Details
            rows={[
              ['Operating mode', data.mode],
              ['Version', data.version],
              ['Startup time', stamp(data.started_at)],
              ['Uptime', uptime(data.uptime_seconds)],
            ]}
          />
        </Panel>
        <Panel title="Fixture activity">
          <Details
            rows={[
              [
                'Source status',
                <Badge tone={data.source_status === 'ready' ? 'green' : 'amber'}>
                  {display(data.source_status)}
                </Badge>,
              ],
              ['Latest successful ingestion', stamp(data.last_ingestion_at)],
              ['Latest evaluation', stamp(data.last_evaluation_at)],
              ['Missing inputs', data.missing_inputs ?? 'Unavailable'],
            ]}
          />
        </Panel>
      </div>
      <Panel
        title="System warnings"
        action={
          <Badge tone={data.warnings.length ? 'amber' : 'green'}>
            {counted(data.warnings.length, 'warning')}
          </Badge>
        }
      >
        {data.warnings.length ? (
          <div className="warnings">
            {data.warnings.map((warning) => (
              <Warning key={warning}>{warning}</Warning>
            ))}
          </div>
        ) : (
          <Empty
            icon={CircleCheck}
            title="No warnings reported"
            text="The backend returned no runtime or source warnings."
          />
        )}
      </Panel>
    </div>
  )
}
