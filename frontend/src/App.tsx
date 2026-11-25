import { useEffect } from 'react'
import {
  Activity,
  Boxes,
  ChevronRight,
  FlaskConical,
  LayoutDashboard,
  Monitor,
  Search,
  ShieldCheck,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import type { Health } from './data'
import { clockTime, useResource } from './data'
import { Boundary, PageTitle, useClock } from './ui'
import { Link, useLocation } from './navigation'
import OverviewPage from './Overview'
import Explorer from './Explorer'
import Research from './Research'
import PortfolioPage from './Portfolio'
import HealthPage from './Health'
import mark from './mark.svg'

interface Page {
  path: string
  title: string
  icon: LucideIcon
  description: string
}
const pages: Page[] = [
  {
    path: '/',
    title: 'Overview',
    icon: LayoutDashboard,
    description: 'An operational view of your synthetic research workspace.',
  },
  {
    path: '/markets',
    title: 'Market Explorer',
    icon: Search,
    description: 'Inspect synthetic events, contract forecasts and their source observations.',
  },
  {
    path: '/research',
    title: 'Research Lab',
    icon: FlaskConical,
    description: 'Inspect versioned models and contract-level forecast evaluations.',
  },
  {
    path: '/portfolio',
    title: 'Paper Portfolio',
    icon: Wallet,
    description: 'Balances and accounting records for the synthetic paper portfolio.',
  },
  {
    path: '/health',
    title: 'System Health',
    icon: Activity,
    description: 'Backend diagnostics, fixture availability and recent processing activity.',
  },
]
function Navigation({ current }: { current: string }) {
  return (
    <nav aria-label="Main navigation">
      {[pages.slice(0, 3), pages.slice(3)].map((group, i) => (
        <div className="nav-group" key={i}>
          <span className="nav-label">{i === 0 ? 'Workspace' : 'Operations'}</span>
          {group.map((page) => (
            <Link
              key={page.path}
              href={page.path}
              aria-current={current === page.path ? 'page' : undefined}
            >
              <page.icon size={18} />
              <span>{page.title}</span>
            </Link>
          ))}
        </div>
      ))}
    </nav>
  )
}
export default function App() {
  const location = useLocation()
  const [path, search] = location.split('?')
  const page = pages.find((item) => item.path === path)
  const health = useResource<Health>('/health')
  const now = useClock()
  const current = health.isSuccess && now - health.dataUpdatedAt <= 15_000
  const connection = current
    ? 'Backend connected'
    : health.isPending
      ? 'Connecting'
      : 'Disconnected'
  useEffect(() => {
    document.title = (page?.title ?? 'Page unavailable') + ' · Andromeda'
    document.documentElement.scrollTop = 0
  }, [page, search])
  return (
    <div className="app-shell">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="Andromeda home">
          <img src={mark} alt="" />
          <span>
            ANDROMEDA<small>Research terminal</small>
          </span>
        </Link>
        <Navigation current={path} />
        <div className="mode">
          <div className="mode-heading">
            <ShieldCheck size={16} /> Synthetic research
          </div>
          <p>Paper only</p>
        </div>
        <div className="sidebar-foot">
          <Monitor size={14} />
          <span>Local workspace</span>
          {current && <code>v{health.data.version}</code>}
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="crumb">
            <Monitor size={15} />
            <span>Terminal</span>
            <ChevronRight size={13} />
            <b>{page?.title ?? 'Unavailable'}</b>
          </div>
          <div className="top-status">
            <span className={'connection ' + (current ? 'connected' : 'offline')}>
              <i />
              {connection}
            </span>
            <time>
              {clockTime(now)} <span>UTC</span>
            </time>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          {page ? (
            <>
              <PageTitle title={page.title} description={page.description} icon={page.icon} />
              <Boundary query={health}>
                {(data) => {
                  switch (path) {
                    case '/markets':
                      return <Explorer id={new URLSearchParams(search).get('event')} />
                    case '/research':
                      return <Research />
                    case '/portfolio':
                      return <PortfolioPage />
                    case '/health':
                      return <HealthPage data={data} />
                    default:
                      return <OverviewPage health={data} />
                  }
                }}
              </Boundary>
            </>
          ) : (
            <>
              <PageTitle
                title="Page unavailable"
                description="This path has no terminal view."
                icon={Boxes}
              />
              <Link href="/" className="button">
                Return to Overview
              </Link>
            </>
          )}
        </main>
        <footer className="workspace-foot">
          <span>Andromeda Research Terminal</span>
          <span>
            Refresh interval <b>5s</b>
          </span>
        </footer>
      </div>
    </div>
  )
}
