import { BriefcaseBusiness, ChartLine, Coins, History, Landmark, Wallet } from 'lucide-react'
import { ApiError, money, useResource } from './data'
import type { Portfolio } from './data'
import { Badge, Boundary, Details, Empty, Metric, Panel } from './ui'

export default function PortfolioPage() {
  const query = useResource<Portfolio>('/portfolio')
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <Panel title="Paper accounting">
        <Empty icon={Wallet} title="Portfolio uninitialized" text={query.error.message} />
      </Panel>
    )
  }
  return (
    <Boundary query={query}>
      {(account) => (
        <div className="section-stack">
          <div className="metrics">
            <Metric
              label="Current paper cash"
              value={money(account.current_cash)}
              note={account.currency + ' · paper balance'}
              icon={Wallet}
            />
            <Metric
              label="Starting cash"
              value={money(account.starting_cash)}
              note="Configured opening balance"
              icon={Landmark}
              tone="blue"
            />
            <Metric
              label="Open positions"
              value={account.open_positions}
              note="Paper portfolio"
              icon={BriefcaseBusiness}
            />
            <Metric
              label="Realized P&L"
              value={money(account.realized_pnl)}
              note={account.transactions + ' financial transactions'}
              icon={Coins}
              tone="green"
            />
          </div>
          <div className="dashboard-grid">
            <Panel title="Performance history">
              <Empty
                title="No performance history"
                text="A performance series requires a recorded history of paper valuations."
                icon={ChartLine}
              />
            </Panel>
            <Panel title="Paper accounting" action={<Badge tone="violet">Paper only</Badge>}>
              <Details
                rows={[
                  ['Currency', account.currency],
                  ['Financial transactions', account.transactions],
                  [
                    'Portfolio return',
                    account.return_pct === null ? 'Unavailable' : account.return_pct + '%',
                  ],
                  ['Win rate', account.win_rate === null ? 'Unavailable' : account.win_rate + '%'],
                ]}
              />
            </Panel>
          </div>
          <div className="dashboard-grid equal">
            <Panel title="Positions">
              <Empty
                icon={BriefcaseBusiness}
                title="No open positions"
                text="The synthetic portfolio holds its opening cash balance."
              />
            </Panel>
            <Panel title="Transaction history">
              <Empty
                icon={History}
                title="No transactions"
                text="The opening balance is an initial condition. The ledger has no fills or transfers."
              />
            </Panel>
          </div>
        </div>
      )}
    </Boundary>
  )
}
