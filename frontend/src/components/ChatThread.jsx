import { useEffect, useRef, useState } from 'react'
import './ChatThread.scss'
import ConnectionStatus from './ConnectionStatus'
import DevProgress from './DevProgress'

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

const PROJECT_TYPE_LABELS = [
  { key: 'is_mobile_app',       label: 'Mobile App',     icon: 'smartphone', color: 'violet' },
  { key: 'is_devops_program',   label: 'DevOps',         icon: 'build',      color: 'amber' },
  { key: 'is_script',           label: 'Script / CLI',   icon: 'terminal',   color: 'emerald' },
  { key: 'is_full_stack',       label: 'Full-Stack',     icon: 'layers',     color: 'indigo' },
  { key: 'has_frontend',        label: 'Frontend',       icon: 'web',        color: 'rose' },
  { key: 'has_backend',         label: 'Backend API',    icon: 'dns',        color: 'sky' },
]

function getProjectTypeLabel(tags) {
  if (!tags) return null
  for (const { key, label, icon, color } of PROJECT_TYPE_LABELS) {
    if (tags[key]) return { label, icon, color }
  }
  return null
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
  projectTags,
  jiraStatus,
  jiraProjectSelected,
  jiraRequiredMessage,
  isSending,
  sendError,
  showReadyBanner,
  taskingResult,
  isTaskingLoading,
  repoUrl,
  deploymentStatus,
  deploymentLiveUrl,
  deploymentError,
  devInProcess,
  isDeployActionLoading,
  agentRunError,
  agentTickets,
  sessionExpired,
  onSendMessage,
  onContinueChat,
  onStartTasking,
  onAddMoreRequirements,
  onReportBug,
  onRetryTicket,
  onRefreshTickets,
  onDeployIdea,
  onRedeployIdea,
  onCancelAgents,
  onGoToProfile,
  onBack,
}) {
  const [input, setInput] = useState('')
  const [showStopConfirm, setShowStopConfirm] = useState(false)
  const [isStoppingAgents, setIsStoppingAgents] = useState(false)
  const [stopModalError, setStopModalError] = useState('')
  const [toast, setToast] = useState(null)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const toastTimerRef = useRef(null)
  const isTasking = status === 'tasking'
  const isDone    = status === 'done'
  const isJiraBlocked = jiraStatus !== 'connected' || !jiraProjectSelected
  const projectTypeLabel = getProjectTypeLabel(projectTags)
  const composerHint = sessionExpired
    ? 'Session expired'
    : isJiraBlocked
      ? (jiraStatus !== 'connected' ? 'Connect Jira in Profile' : 'Select a Jira project in Profile')
      : isSending
        ? 'Sending message...'
        : 'Shift+Enter for newline'

  // Cycling phrase state for the loading overlay
  const [phraseIndex, setPhraseIndex] = useState(0)
  const [phraseVisible, setPhraseVisible] = useState(true)
  const prevShowReadyBannerRef = useRef(showReadyBanner)
  const stoppableTicketsCount = agentTickets.filter((ticket) => ['pending', 'in_progress'].includes(ticket.status)).length
  const hasFrontendCapability = !!(
    projectTags?.has_frontend ||
    projectTags?.is_full_stack ||
    agentTickets.some((ticket) => ticket.type === 'frontend')
  )
  const hasAnyTickets = agentTickets.length > 0
  const allTicketsDone = hasAnyTickets && agentTickets.every((ticket) => ticket.status === 'done')
  const hasSuccessfulDeployment = !!deploymentLiveUrl || deploymentStatus === 'deployed'
  const jiraErrorForSummary = taskingResult?.jira_error || null
  const jiraKeysFromTasking = Array.isArray(taskingResult?.jira_tickets_created)
    ? taskingResult.jira_tickets_created
        .map((ticket) => ticket?.key)
        .filter(Boolean)
    : []
  const jiraKeysFromAgentTickets = Array.from(new Set(
    agentTickets
      .map((ticket) => ticket?.jira_issue_key)
      .filter(Boolean)
  ))
  const jiraKeysForSummary = jiraKeysFromTasking.length > 0
    ? jiraKeysFromTasking
    : jiraKeysFromAgentTickets
  const hasTaskingSummary = !isTaskingLoading && (
    !!taskingResult ||
    !!repoUrl ||
    !!jiraErrorForSummary ||
    jiraKeysForSummary.length > 0
  )

  let deployControlMode = 'hidden'
  let deployControlDisabled = false
  let deployControlDisabledReason = ''

  if (hasFrontendCapability && repoUrl) {
    if (deploymentStatus === 'deploying' || (hasSuccessfulDeployment && devInProcess)) {
      deployControlMode = 'deploying'
    } else if (deploymentStatus === 'deployed' && !devInProcess) {
      deployControlMode = 'deployed'
    } else if (!hasSuccessfulDeployment && devInProcess) {
      // First build in progress and not yet deployed: hide deploy controls.
      deployControlMode = 'hidden'
    } else if (hasSuccessfulDeployment) {
      deployControlMode = 'redeploy'
      deployControlDisabled = !!isDeployActionLoading
      deployControlDisabledReason = isDeployActionLoading ? 'Starting redeploy...' : ''
    } else {
      deployControlMode = 'deploy'
      deployControlDisabled = !allTicketsDone || !!isDeployActionLoading
      if (!allTicketsDone) {
        deployControlDisabledReason = 'Deploy Idea is enabled after all Jira tickets are completed.'
      } else if (isDeployActionLoading) {
        deployControlDisabledReason = 'Starting deployment...'
      }
    }
  }

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

  useEffect(() => {
    if (prevShowReadyBannerRef.current && !showReadyBanner && !isTasking && !isDone) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      window.setTimeout(() => {
        inputRef.current?.focus()
      }, 60)
    }
    prevShowReadyBannerRef.current = showReadyBanner
  }, [showReadyBanner, isTasking, isDone])

  useEffect(() => {
    if (!devInProcess) {
      setShowStopConfirm(false)
      setIsStoppingAgents(false)
      setStopModalError('')
    }
  }, [devInProcess])

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) {
        window.clearTimeout(toastTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (!showStopConfirm) return

    const handleEsc = (event) => {
      if (event.key === 'Escape' && !isStoppingAgents) {
        setShowStopConfirm(false)
      }
    }

    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [showStopConfirm, isStoppingAgents])

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed || isSending || isTasking || isDone || isJiraBlocked || sessionExpired) return
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

  const showToast = (type, message, duration = 3400) => {
    if (toastTimerRef.current) {
      window.clearTimeout(toastTimerRef.current)
    }

    setToast({ type, message })
    toastTimerRef.current = window.setTimeout(() => {
      setToast(null)
      toastTimerRef.current = null
    }, duration)
  }

  const handleOpenStopConfirm = () => {
    if (!devInProcess || !onCancelAgents) return
    setStopModalError('')
    setShowStopConfirm(true)
  }

  const handleCloseStopConfirm = () => {
    if (isStoppingAgents) return
    setStopModalError('')
    setShowStopConfirm(false)
  }

  const handleConfirmStopAgents = async () => {
    if (!onCancelAgents || isStoppingAgents) return
    setIsStoppingAgents(true)
    setStopModalError('')

    try {
      const result = await onCancelAgents()
      if (!result?.ok) {
        const message = result?.error || 'Unable to stop agents right now. Please try again.'
        setStopModalError(message)
        showToast('error', message, 4200)
        return
      }

      setShowStopConfirm(false)
      showToast('success', 'Agents stopped. Development has been halted for this run.', 4200)
    } finally {
      setIsStoppingAgents(false)
    }
  }

  const closeToast = () => {
    if (toastTimerRef.current) {
      window.clearTimeout(toastTimerRef.current)
      toastTimerRef.current = null
    }
    setToast(null)
  }

  return (
    <div className="chat-thread">

      {/* ── In-app toast ─────────────────────────────────────── */}
      {toast && (
        <div className={`chat-toast chat-toast--${toast.type}`} role="status" aria-live="polite">
          <span className="material-icons chat-toast__icon">
            {toast.type === 'success' ? 'check_circle' : toast.type === 'error' ? 'error' : 'info'}
          </span>
          <span className="chat-toast__text">{toast.message}</span>
          <button className="chat-toast__close" onClick={closeToast} aria-label="Dismiss notification">
            <span className="material-icons">close</span>
          </button>
        </div>
      )}

      {/* ── Stop agents confirmation modal ────────────────────── */}
      {showStopConfirm && (
        <div className="chat-stop-modal__overlay" onClick={handleCloseStopConfirm}>
          <div
            className="chat-stop-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="chat-stop-modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="chat-stop-modal__icon">
              <span className="material-icons">warning</span>
            </div>
            <h3 className="chat-stop-modal__title" id="chat-stop-modal-title">
              Stop development agents?
            </h3>
            <p className="chat-stop-modal__text">
              This will completely halt your development run. The agents will stop immediately and the project will not be finished automatically.
            </p>
            {stoppableTicketsCount > 0 && (
              <p className="chat-stop-modal__hint">
                {stoppableTicketsCount} ticket{stoppableTicketsCount !== 1 ? 's are' : ' is'} still pending or running and will be left unfinished.
              </p>
            )}
            {stopModalError && <p className="chat-stop-modal__error">{stopModalError}</p>}
            <div className="chat-stop-modal__actions">
              <button
                className="chat-stop-modal__btn chat-stop-modal__btn--ghost"
                onClick={handleCloseStopConfirm}
                disabled={isStoppingAgents}
                autoFocus
              >
                Keep Running
              </button>
              <button
                className="chat-stop-modal__btn chat-stop-modal__btn--danger"
                onClick={handleConfirmStopAgents}
                disabled={isStoppingAgents}
              >
                {isStoppingAgents ? 'Stopping…' : 'Stop Agents'}
              </button>
            </div>
          </div>
        </div>
      )}

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
          <ConnectionStatus
            mode={deployControlMode}
            disabled={deployControlDisabled}
            disabledReason={deployControlDisabledReason}
            loading={!!isDeployActionLoading}
            onDeploy={onDeployIdea}
            onRedeploy={onRedeployIdea}
          />
          {projectTypeLabel && (
            <div className={`chat-thread__header-badge chat-thread__header-badge--project chat-thread__header-badge--${projectTypeLabel.color}`}>
              <span className="material-icons">{projectTypeLabel.icon}</span>
              {projectTypeLabel.label}
            </div>
          )}
          <div className="chat-thread__header-badge">
            <span className="material-icons">forum</span>
            {messages.length} messages
          </div>
        </div>
      </div>

      {/* ── Dev agent progress panel ──────────────────────────── */}
      {!agentRunError && (
        <>
          <DevProgress
            devInProcess={devInProcess}
            agentTickets={agentTickets}
            onRefreshTickets={onRefreshTickets}
            onRetryTicket={onRetryTicket}
          />
          {devInProcess && onCancelAgents && (
            <div className="chat-thread__stop-bar">
              <button className="chat-thread__stop-btn" onClick={handleOpenStopConfirm}>
                <span className="material-icons">stop_circle</span>
                Stop Agents
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Agent run error banner ─────────────────────────────── */}
      {agentRunError && (
        <div className="dev-banner dev-banner--error">
          <span className="material-icons">error</span>
          <p className="dev-banner__text">{agentRunError}</p>
        </div>
      )}

      {/* ── Deployment error banner ────────────────────────────── */}
      {deploymentStatus === 'failed' && deploymentError && (
        <div className="dev-banner dev-banner--error">
          <span className="material-icons">cloud_off</span>
          <p className="dev-banner__text">Deployment failed: {deploymentError}</p>
        </div>
      )}

      {/* ── Messages ───────────────────────────────────────────── */}
      <div className="chat-thread__messages">
        <div className="chat-thread__start-label">
          <span>Conversation started</span>
        </div>

        {sessionExpired && (
          <div className="chat-thread__jira-lockout chat-thread__jira-lockout--expired" role="alert">
            <div className="chat-thread__jira-lockout-icon">
              <span className="material-icons">lock</span>
            </div>
            <div className="chat-thread__jira-lockout-body">
              <p className="chat-thread__jira-lockout-title">Your session has expired</p>
              <p className="chat-thread__jira-lockout-text">
                You'll be redirected to the login page in a moment…
              </p>
            </div>
          </div>
        )}

        {isJiraBlocked && !sessionExpired && (
          <div className="chat-thread__jira-lockout" role="alert">
            <div className="chat-thread__jira-lockout-icon">
              <span className="material-icons">{jiraStatus !== 'connected' ? 'link_off' : 'folder_off'}</span>
            </div>
            <div className="chat-thread__jira-lockout-body">
              <p className="chat-thread__jira-lockout-title">{jiraRequiredMessage}</p>
              <p className="chat-thread__jira-lockout-text">
                {jiraStatus !== 'connected'
                  ? 'Connect Jira from your profile to continue chatting with the PM agent.'
                  : 'Select a target Jira project from your profile to continue.'}
              </p>
            </div>
            <button className="chat-thread__jira-lockout-action" onClick={onGoToProfile}>
              {jiraStatus !== 'connected' ? 'Connect Jira' : 'Go to Profile'}
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

      {/* ── Post-tasking summary + actions ─────────────────────── */}
      {hasTaskingSummary && (
        <div className="chat-tasking-banner chat-tasking-banner--decision">
          <div className="chat-tasking-banner__decision-body">
            <span className="material-icons chat-tasking-banner__decision-icon">
              {jiraErrorForSummary ? 'warning' : 'check_circle'}
            </span>
            <div>
              {repoUrl && (
                <p className="chat-tasking-banner__sub">
                  <span className="material-icons" style={{ fontSize: '0.9rem', verticalAlign: 'middle', marginRight: 4 }}>code</span>
                  <a
                    href={repoUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="chat-tasking-banner__repo-link"
                    title={repoUrl}
                  >
                    Project being developed here
                  </a>
                </p>
              )}
              {jiraErrorForSummary ? (
                <p className="chat-tasking-banner__sub chat-tasking-banner__sub--warn">
                  Jira sync failed: {jiraErrorForSummary}
                </p>
              ) : jiraKeysForSummary.length > 0 ? (
                <p className="chat-tasking-banner__sub">
                  {jiraKeysForSummary.length} ticket{jiraKeysForSummary.length !== 1 ? 's' : ''} synced to Jira
                  &nbsp;·&nbsp;
                  {jiraKeysForSummary.join(' · ')}
                </p>
              ) : null}
            </div>
          </div>
          <div className="chat-tasking-banner__actions">
            <button
              className="chat-thread__add-more-btn"
              onClick={onAddMoreRequirements}
            >
              <span className="material-icons">add_circle_outline</span>
              Add Requirements
            </button>
            <button
              className="chat-thread__add-more-btn chat-thread__add-more-btn--ghost"
              onClick={onReportBug}
            >
              <span className="material-icons">bug_report</span>
              Report Bug
            </button>
          </div>
        </div>
      )}

      {/* ── Input ──────────────────────────────────────────────── */}
      {!isTasking && !isDone && !showReadyBanner && (
        <>
          <div className="chat-thread__composer">
            <div className="chat-thread__composer-meta">
              <p className="chat-thread__composer-label">Message Composer</p>
              <p className={`chat-thread__composer-hint ${isJiraBlocked || sessionExpired ? 'chat-thread__composer-hint--warn' : ''}`}>
                {composerHint}
              </p>
            </div>
            <div className="chat-thread__input-bar">
              <textarea
                ref={inputRef}
                className="chat-thread__input"
                placeholder={
                  sessionExpired  ? 'Session expired — redirecting…' :
                  isJiraBlocked   ? (jiraStatus !== 'connected' ? 'Connect Jira to continue chatting' : 'Select a Jira project to continue') :
                  'Reply to the PM agent…'
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                disabled={isSending || isJiraBlocked || sessionExpired}
              />
              <button
                className="chat-thread__send"
                onClick={handleSend}
                disabled={isJiraBlocked || sessionExpired || !input.trim() || isSending}
                aria-label="Send message"
              >
                <span className="material-icons">send</span>
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── Done: Add requirements ─────────────────────────────── */}
      {isDone && !hasTaskingSummary && (
        <div className="chat-thread__add-more">
          <button
            className="chat-thread__add-more-btn"
            onClick={onAddMoreRequirements}
          >
            <span className="material-icons">add_circle_outline</span>
            Add Requirements
          </button>
          <button
            className="chat-thread__add-more-btn chat-thread__add-more-btn--ghost"
            onClick={onReportBug}
          >
            <span className="material-icons">bug_report</span>
            Report Bug
          </button>
        </div>
      )}
    </div>
  )
}
