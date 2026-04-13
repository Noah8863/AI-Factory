import { useState } from 'react'
import './DevProgress.scss'

export default function DevProgress({
  devInProcess,
  agentTickets,
  onRefreshTickets,
  onRetryTicket,
  compact = false,
}) {
  const [expandedErrors, setExpandedErrors] = useState({})
  const [isCollapsed, setIsCollapsed] = useState(false)

  if (!devInProcess && agentTickets.length === 0) return null

  const doneCount = agentTickets.filter(t => t.status === 'done').length
  const activeCount = agentTickets.filter(t => t.status === 'in_progress').length
  const failedCount = agentTickets.filter(t => t.status === 'failed').length
  const pendingCount = agentTickets.filter(t => t.status === 'pending').length
  const rootClass = compact ? 'dev-progress dev-progress--compact' : 'dev-progress'

  return (
    <div className={rootClass}>
      <div className="dev-progress__header">
        <div className="dev-progress__title-row">
          {devInProcess ? (
            <>
              <div className="dev-progress__hammer-wrap">
                <span className="material-icons dev-progress__hammer">hardware</span>
              </div>
              <p className="dev-progress__title">Development in progress</p>
              <div className="dev-progress__dots"><span /><span /><span /></div>
            </>
          ) : (
            <>
              <span className="material-icons dev-progress__done-icon">check_circle</span>
              <p className="dev-progress__title">Development complete</p>
            </>
          )}
        </div>
        <div className="dev-progress__header-right">
          {agentTickets.length > 0 && (
            <div className="dev-progress__counts">
              <span>{doneCount}/{agentTickets.length} done</span>
              {failedCount > 0 && (
                <span className="dev-progress__count-alert">{failedCount} failed</span>
              )}
            </div>
          )}
          {onRefreshTickets && (
            <button className="dev-progress__refresh" onClick={onRefreshTickets} title="Refresh ticket status">
              <span className="material-icons">refresh</span>
            </button>
          )}
          {!compact && (
            <button
              className="dev-progress__collapse"
              onClick={() => setIsCollapsed(c => !c)}
              title={isCollapsed ? 'Expand ticket list' : 'Collapse ticket list'}
            >
              <span className="material-icons">
                {isCollapsed ? 'expand_more' : 'expand_less'}
              </span>
            </button>
          )}
        </div>
      </div>
      {!isCollapsed && (
        <>
          {agentTickets.length > 0 && (
            <div className="dev-progress__bar-track">
              <div
                className="dev-progress__bar-fill"
                style={{
                  width: `${(doneCount / agentTickets.length) * 100}%`,
                }}
              />
            </div>
          )}
          {agentTickets.length > 0 && (
            <div className="dev-progress__summary">
              <span className="dev-progress__summary-pill dev-progress__summary-pill--done">Done {doneCount}</span>
              <span className="dev-progress__summary-pill dev-progress__summary-pill--active">Active {activeCount}</span>
              <span className="dev-progress__summary-pill dev-progress__summary-pill--pending">Pending {pendingCount}</span>
              {failedCount > 0 && (
                <span className="dev-progress__summary-pill dev-progress__summary-pill--failed">Failed {failedCount}</span>
              )}
            </div>
          )}
          {/* Skeleton while tickets haven't loaded yet */}
          {devInProcess && agentTickets.length === 0 && (
            <div className="dev-progress__skeleton">
              <div className="dev-progress__skeleton-bar" />
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="dev-progress__skeleton-row">
                  <div className="dev-progress__skeleton-circle" />
                  <div className="dev-progress__skeleton-id" />
                  <div className="dev-progress__skeleton-title" />
                  <div className="dev-progress__skeleton-badge" />
                </div>
              ))}
            </div>
          )}
          {agentTickets.length > 0 && (
            <ul className="dev-progress__list">
              {agentTickets.map(ticket => {
            const statusIcon =
              ticket.status === 'done'        ? 'check_circle' :
              ticket.status === 'in_progress' ? 'sync' :
              ticket.status === 'failed'      ? 'error' :
                                                'schedule'
            const statusClass =
              ticket.status === 'done'        ? 'done' :
              ticket.status === 'in_progress' ? 'active' :
              ticket.status === 'failed'      ? 'failed' :
                                                'pending'
            const isExpanded = !!expandedErrors[ticket.id]
            const hasFailed = ticket.status === 'failed' && ticket.error_msg
            return (
              <li key={ticket.id} className={`dev-progress__ticket dev-progress__ticket--${statusClass}`}>
                <div className="dev-progress__ticket-row">
                  <span className={`material-icons dev-progress__ticket-icon dev-progress__ticket-icon--${statusClass}`}>
                    {statusIcon}
                  </span>
                  <span className="dev-progress__ticket-id">{ticket.ticket_id}</span>
                  <span className="dev-progress__ticket-title">{ticket.title}</span>
                  <span className={`dev-progress__ticket-badge dev-progress__ticket-badge--${statusClass}`}>
                    {ticket.status === 'in_progress' ? 'building' : ticket.status}
                  </span>
                  {hasFailed && (
                    <>
                      <button
                        className="dev-progress__ticket-toggle"
                        onClick={() =>
                          setExpandedErrors(prev => ({ ...prev, [ticket.id]: !prev[ticket.id] }))
                        }
                        title={isExpanded ? 'Hide error details' : 'Show error details'}
                      >
                        <span className="material-icons">
                          {isExpanded ? 'expand_less' : 'expand_more'}
                        </span>
                      </button>
                      {onRetryTicket && (
                        <button
                          className="dev-progress__ticket-retry"
                          onClick={() => onRetryTicket(ticket.id)}
                          title="Retry this ticket"
                        >
                          <span className="material-icons">refresh</span>
                          Retry
                        </button>
                      )}
                    </>
                  )}
                </div>
                {hasFailed && isExpanded && (
                  <div className="dev-progress__ticket-error">
                    <pre className="dev-progress__ticket-error-pre">{ticket.error_msg}</pre>
                  </div>
                )}
              </li>
            )
          })}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
