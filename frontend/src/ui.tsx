import { useEffect, useId, useState, type ReactNode } from 'react'
import { type UseQueryResult } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, CircleAlert, type LucideIcon } from 'lucide-react'
import { stamp } from './data'

export function useClock() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

export function Boundary<T>({
  query,
  children,
}: {
  query: UseQueryResult<T, Error>
  children: (data: T) => ReactNode
}) {
  const now = useClock()
  if (query.isPending)
    return (
      <div className="surface state-box" role="status">
        <span className="loading-line" />
        Loading workspace data…
      </div>
    )
  const expired = query.dataUpdatedAt > 0 && now - query.dataUpdatedAt > 15_000
  if (query.isError || expired) {
    const hadSnapshot = query.dataUpdatedAt > 0
    return (
      <div className="surface state-box failure" role="alert">
        <CircleAlert size={23} />
        <h2>{hadSnapshot ? 'Stale data' : 'Data unavailable'}</h2>
        <p>
          {hadSnapshot
            ? 'Last successful response ' + stamp(new Date(query.dataUpdatedAt).toISOString()) + '.'
            : 'The terminal could not load this resource.'}{' '}
          {query.error?.message}
        </p>
        <button className="button" onClick={() => void query.refetch()}>
          Retry connection
        </button>
      </div>
    )
  }
  return children(query.data)
}

export function PageTitle({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon
  title: string
  description: string
}) {
  return (
    <header className="page-heading">
      <div className="title-line">
        <span className="page-icon">
          <Icon size={23} />
        </span>
        <h1>{title}</h1>
      </div>
      <p>{description}</p>
    </header>
  )
}

export function Panel({
  title,
  action,
  children,
  className = '',
}: {
  title: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  const id = useId()
  return (
    <section className={'surface panel ' + className} aria-labelledby={id}>
      <div className="panel-header">
        <h2 id={id}>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}
export function Metric({
  label,
  value,
  note,
  icon: Icon,
  tone = 'violet',
}: {
  label: string
  value: string | number
  note: string
  icon: LucideIcon
  tone?: string
}) {
  return (
    <article className="surface metric" aria-label={label}>
      <div className="metric-label">
        <span>{label}</span>
        <Icon className={'metric-icon ' + tone} size={18} />
      </div>
      <strong className={value === 'Unavailable' ? 'metric-unavailable' : ''}>{value}</strong>
      <div className="metric-note">{note}</div>
    </article>
  )
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={'badge ' + tone}>{children}</span>
}
export function Details({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="details">
      {rows.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
export function Empty({
  title,
  text,
  icon: Icon,
}: {
  title: string
  text: string
  icon: LucideIcon
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon size={24} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  )
}
export function Warning({ children }: { children: ReactNode }) {
  return (
    <div className="warning">
      <AlertTriangle size={16} />
      <span>{children}</span>
    </div>
  )
}
export function Select({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
}) {
  return (
    <div className="select">
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
      <ChevronDown size={15} />
    </div>
  )
}
