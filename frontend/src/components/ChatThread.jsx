import { useEffect, useRef, useState } from 'react'
import './ChatThread.scss'
import ConnectionStatus from './ConnectionStatus'

function parseMarkdownBold(text) {
  const parts = text.split(/\*\*(.*?)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  )
}

/**
 * SQLite stores datetimes as UTC without a 'Z' suffix.
 * Appending 'Z' tells JS to treat it as UTC so toLocaleTimeString()
 * converts correctly to the user's local timezone.
 */
function formatTime(isoString) {
  if (!isoString) return ''
  const utc = isoString.endsWith('Z') ? isoString : isoString + 'Z'
  return new Date(utc).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  return (
    <div className={`chat-bubble chat-bubble--${isUser ? 'user' : 'agent'} ${message._optimistic ? 'chat-bubble--optimistic' : ''}`}>
      {!isUser && (
        <div className="chat-bubble__avatar">
          <span className="material-icons">smart_toy</span>
        </div>
      )}
      <div className="chat-bubble__body">
        {!isUser && <span className="chat-bubble__name">PM Agent</span>}
        <div className="chat-bubble__text">
          {message.content.split('\n\n').map((para, i) => (
            <p key={i}>{parseMarkdownBold(para)}</p>
          ))}
        </div>
        <span className="chat-bubble__time">
          {message._optimistic ? 'Sending…' : formatTime(message.created_at)}
        </span>
      </div>
      {isUser && (
        <div className="chat-bubble__avatar chat-bubble__avatar--user">
          <span className="material-icons">person</span>
        </div>
      )}
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="chat-bubble chat-bubble--agent">
      <div className="chat-bubble__avatar">
        <span className="material-icons">smart_toy</span>
      </div>
      <div className="chat-bubble__body">
        <span className="chat-bubble__name">PM Agent</span>
        <div className="chat-typing">
          <span /><span /><span />
        </div>
      </div>
    </div>
  )
}

const TASKING_PHRASES = [
  'Analyzing Requirements',
  'Defining Scope',
  'Structuring Backlog',
  'Creating Tickets',
  'Assigning Tasks',
]

export default function ChatThread({
  messages,
  status,
  jiraStatus,
  jiraRequiredMessage,
  isSending,
  sendError,
  showReadyBanner,
  taskingResult,
  isTaskingLoading,
  repoUrl,
  hasBeenTasked,
  devInProcess,
  agentRunError,
  agentTickets,
  onSendMessage,
  onContinueChat,
  onStartTasking,
  onYesContinue,
  onNoClose,
  onAddMoreRequirements,
  onRetryTicket,
  onGoToProfile,
  onBack,
}) {
  const [input, setInput] = useState('')
  const [expandedErrors, setExpandedErrors] = useState({})
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const isTasking = status === 'tasking'
  const isDone    = status === 'done'
  const isJiraBlocked = jiraStatus !== 'connected'

  // Cycling phrase state for the loading overlay
  const [phraseIndex, setPhraseIndex] = useState(0)
  const [phraseVisible, setPhraseVisible] = useState(true)

  useEffect(() => {
    if (!isTaskingLoading) return
    setPhraseIndex(0)
    setPhraseVisible(true)

    const cycle = setInterval(() => {
      // Fade out
      setPhraseVisible(false)
      setTimeout(() => {
        setPhraseIndex(i => (i + 1) % TASKING_PHRASES.length)
        setPhraseVisible(true)
      }, 300) // wait for fade-out then swap text and fade in
    }, 2300) // total time per phrase (2.3s gives 2s visible + 0.3s fade)

    return () => clearInterval(cycle)
  }, [isTaskingLoading])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isSending])

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed || isSending || isTasking || isDone || isJiraBlocked) return
    setInput('')
    onSendMessage(trimmed)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-thread">

      {/* ── Tasking loading overlay ────────────────────────────── */}
      {isTaskingLoading && (
        <div className="tasking-overlay">
          <div className="tasking-overlay__orb" />
          <div className="tasking-overlay__ring tasking-overlay__ring--1" />
          <div className="tasking-overlay__ring tasking-overlay__ring--2" />
          <div className="tasking-overlay__ring tasking-overlay__ring--3" />
          <div className="tasking-overlay__icon">
            <span className="material-icons">smart_toy</span>
          </div>
          <p
            className="tasking-overlay__phrase"
            style={{ opacity: phraseVisible ? 1 : 0 }}
          >
            {TASKING_PHRASES[phraseIndex]}
          </p>
          <p className="tasking-overlay__sub">PM Agent is working…</p>
        </div>
      )}

      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="chat-thread__header">
        <button className="chat-thread__back" onClick={onBack}>
          <span className="material-icons">arrow_back</span>
          <span>Back</span>
        </button>
        <div className="chat-thread__info">
          <div className="chat-thread__agent-icon">
            <span className="material-icons">smart_toy</span>
          </div>
          <div>
            <p className="chat-thread__agent-name">PM Agent</p>
            <p className="chat-thread__agent-status">
              {isTasking ? 'Creating tasks…' : isSending ? 'Typing…' : 'Active'}
            </p>
          </div>
        </div>
        <div className="chat-thread__header-controls">
          <ConnectionStatus />
          <div className="chat-thread__header-badge">
            <span className="material-icons">forum</span>
            {messages.length} messages
          </div>
        </div>
      </div>

      {/* ── Dev agent progress panel ──────────────────────────── */}
      {(devInProcess || agentTickets.length > 0) && !agentRunError && (
        <div className="dev-progress">
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
            {agentTickets.length > 0 && (
              <p className="dev-progress__counts">
                {agentTickets.filter(t => t.status === 'done').length}/{agentTickets.length} tickets done
              </p>
            )}
          </div>
          {agentTickets.length > 0 && (
            <div className="dev-progress__bar-track">
              <div
                className="dev-progress__bar-fill"
                style={{
                  width: `${(agentTickets.filter(t => t.status === 'done').length / agentTickets.length) * 100}%`,
                }}
              />
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
                          <button
                            className="dev-progress__ticket-retry"
                            onClick={() => onRetryTicket(ticket.id)}
                            title="Retry this ticket"
                          >
                            <span className="material-icons">refresh</span>
                            Retry
                          </button>
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
        </div>
      )}

      {/* ── Agent run error banner ─────────────────────────────── */}
      {agentRunError && (
        <div className="dev-banner dev-banner--error">
          <span className="material-icons">error</span>
          <p className="dev-banner__text">{agentRunError}</p>
        </div>
      )}

      {/* ── Messages ───────────────────────────────────────────── */}
      <div className="chat-thread__messages">
        <div className="chat-thread__start-label">
          <span>Conversation started</span>
        </div>

        {isJiraBlocked && (
          <div className="chat-thread__jira-lockout" role="alert">
            <div className="chat-thread__jira-lockout-icon">
              <span className="material-icons">link_off</span>
            </div>
            <div className="chat-thread__jira-lockout-body">
              <p className="chat-thread__jira-lockout-title">{jiraRequiredMessage}</p>
              <p className="chat-thread__jira-lockout-text">
                Connect Jira from your profile to continue chatting with the PM agent.
              </p>
            </div>
            <button className="chat-thread__jira-lockout-action" onClick={onGoToProfile}>
              Connect Jira
            </button>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isSending && <TypingIndicator />}

        <div ref={bottomRef} />
      </div>

      {/* ── Send error ─────────────────────────────────────────── */}
      {sendError && (
        <div className="chat-thread__error">
          <span className="material-icons">error_outline</span>
          {sendError}
        </div>
      )}

      {/* ── Ready-to-task banner ───────────────────────────────── */}
      {showReadyBanner && !isTasking && (
        <div className="chat-ready-banner">
          <div className="chat-ready-banner__icon">
            <span className="material-icons">check_circle</span>
          </div>
          <div className="chat-ready-banner__body">
            <p className="chat-ready-banner__title">Ready to start building</p>
            <p className="chat-ready-banner__sub">
              The PM has enough context to generate tasks. How would you like to proceed?
            </p>
          </div>
          <div className="chat-ready-banner__actions">
            <button
              className="chat-ready-banner__btn chat-ready-banner__btn--ghost"
              onClick={onContinueChat}
              disabled={isJiraBlocked}
            >
              <span className="material-icons">chat</span>
              Continue Chat
            </button>
            <button
              className="chat-ready-banner__btn chat-ready-banner__btn--primary"
              onClick={onStartTasking}
              disabled={isJiraBlocked}
            >
              Start Building
              <span className="material-icons">rocket_launch</span>
            </button>
          </div>
        </div>
      )}

      {/* ── Post-tasking: Yes / No ─────────────────────────────── */}
      {isTasking && !isTaskingLoading && (
        <div className="chat-tasking-banner chat-tasking-banner--decision">
          <div className="chat-tasking-banner__decision-body">
            <span className="material-icons chat-tasking-banner__decision-icon">
              {taskingResult?.jira_error ? 'warning' : 'check_circle'}
            </span>
            <div>
              {repoUrl && (
                <p className="chat-tasking-banner__sub">
                  <span className="material-icons" style={{ fontSize: '0.9rem', verticalAlign: 'middle', marginRight: 4 }}>code</span>
                  <a href={repoUrl} target="_blank" rel="noreferrer" className="chat-tasking-banner__repo-link">
                    {repoUrl.replace('https://github.com/', '')}
                  </a>
                </p>
              )}
              {taskingResult?.jira_error ? (
                <p className="chat-tasking-banner__sub chat-tasking-banner__sub--warn">
                  Jira sync failed: {taskingResult.jira_error}
                </p>
              ) : taskingResult?.jira_tickets_created?.length > 0 ? (
                <p className="chat-tasking-banner__sub">
                  {taskingResult.jira_tickets_created.length} ticket{taskingResult.jira_tickets_created.length !== 1 ? 's' : ''} synced to Jira
                  &nbsp;·&nbsp;
                  {taskingResult.jira_tickets_created.map(t => t.key).join(' · ')}
                </p>
              ) : null}
            </div>
          </div>
          <p className="chat-tasking-banner__prompt">
            Would you like to continue defining the scope?
          </p>
          <div className="chat-ready-banner__actions">
            <button
              className="chat-ready-banner__btn chat-ready-banner__btn--ghost"
              onClick={onNoClose}
            >
              <span className="material-icons">close</span>
              No
            </button>
            <button
              className="chat-ready-banner__btn chat-ready-banner__btn--primary"
              onClick={onYesContinue}
            >
              Yes
              <span className="material-icons">arrow_forward</span>
            </button>
          </div>
        </div>
      )}

      {/* ── Input ──────────────────────────────────────────────── */}
      {!isTasking && !isDone && (
        <>
          <div className="chat-thread__input-bar">
            <textarea
              ref={inputRef}
              className="chat-thread__input"
              placeholder={isJiraBlocked ? 'Connect Jira to continue chatting' : 'Reply to the PM agent…'}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={isSending || isJiraBlocked}
            />
            <button
              className="chat-thread__send"
              onClick={handleSend}
              disabled={isJiraBlocked || !input.trim() || isSending}
              aria-label="Send message"
            >
              <span className="material-icons">send</span>
            </button>
          </div>
          {hasBeenTasked && (
            <div className="chat-thread__retask-bar">
              <button
                className="chat-thread__retask-btn"
                onClick={onStartTasking}
                disabled={isJiraBlocked}
              >
                <span className="material-icons">rocket_launch</span>
                Start Building
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Done: Add requirements ─────────────────────────────── */}
      {isDone && (
        <div className="chat-thread__add-more">
          <button
            className="chat-thread__add-more-btn"
            onClick={onAddMoreRequirements}
          >
            <span className="material-icons">add_circle_outline</span>
            Add Requirements
          </button>
        </div>
      )}
    </div>
  )
}
