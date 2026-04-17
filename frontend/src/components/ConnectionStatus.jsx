import { useState } from 'react'
import './ConnectionStatus.scss'

export default function ConnectionStatus({
  mode = 'hidden',
  disabled = false,
  disabledReason = '',
  loading = false,
  deploymentError = '',
  liveUrl = '',
  repoUrl = '',
  onDeploy,
  onRedeploy,
}) {
  const [showModal, setShowModal] = useState(false)

  if (mode === 'hidden') return null

  // ── Deployed pill — clickable, opens success modal ──────────────────────────
  if (mode === 'deployed') {
    return (
      <>
        <button
          className="connection-status connection-status--deployed connection-status--action"
          type="button"
          onClick={() => setShowModal(true)}
          title="Your idea is live — click for details"
        >
          <span className="material-icons">check_circle</span>
          <span className="connection-status__text">Idea Deployed!</span>
        </button>

        {showModal && (
          <div className="cs-modal__overlay" onClick={() => setShowModal(false)}>
            <div className="cs-modal cs-modal--success" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
              <div className="cs-modal__glow cs-modal__glow--success" />

              <div className="cs-modal__icon-wrap cs-modal__icon-wrap--success">
                <span className="material-icons">rocket_launch</span>
              </div>

              <h2 className="cs-modal__title">It's alive.</h2>

              <p className="cs-modal__body">
                Your agents burned the midnight oil, turning every line of your vision into real,
                running code — deployed and breathing on the internet, exactly as you imagined it.
                No stand-ups. No sprint planning. Just results.
              </p>

              {liveUrl && (
                <a
                  href={liveUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="cs-modal__live-link"
                >
                  <span className="material-icons">open_in_new</span>
                  View Live Site
                </a>
              )}

              {repoUrl && (
                <a
                  href={repoUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="cs-modal__repo-link"
                >
                  <span className="material-icons">code</span>
                  View Source on GitHub
                </a>
              )}

              <div className="cs-modal__actions">
                <button className="cs-modal__btn cs-modal__btn--ghost" onClick={() => setShowModal(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    )
  }

  // ── Deploying pill — non-interactive ────────────────────────────────────────
  if (mode === 'deploying') {
    return (
      <div className="connection-status connection-status--deploying" title="Deployment is currently running.">
        <span className="material-icons">sync</span>
        <span className="connection-status__text">Deploying...</span>
      </div>
    )
  }

  // ── Failed pill — clickable, opens error modal ───────────────────────────────
  if (mode === 'failed') {
    return (
      <>
        <button
          className="connection-status connection-status--failed connection-status--action"
          type="button"
          onClick={() => setShowModal(true)}
          title="Deployment failed — click for details"
        >
          <span className="material-icons">error</span>
          <span className="connection-status__text">Deployment Failed</span>
        </button>

        {showModal && (
          <div className="cs-modal__overlay" onClick={() => setShowModal(false)}>
            <div className="cs-modal cs-modal--error" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
              <div className="cs-modal__glow cs-modal__glow--error" />

              <div className="cs-modal__icon-wrap cs-modal__icon-wrap--error">
                <span className="material-icons">cloud_off</span>
              </div>

              <h2 className="cs-modal__title">Deployment Failed</h2>

              <p className="cs-modal__body">
                One of your agents hit a snag on the launchpad. The code is ready — the deployment
                just needs another shot. Review the error below and retry when you're ready.
              </p>

              {deploymentError && (
                <div className="cs-modal__error-box">
                  <p className="cs-modal__error-label">
                    <span className="material-icons">terminal</span>
                    Error Details
                  </p>
                  <pre className="cs-modal__error-text">{deploymentError}</pre>
                </div>
              )}

              <div className="cs-modal__actions">
                <button className="cs-modal__btn cs-modal__btn--ghost" onClick={() => setShowModal(false)}>
                  Close
                </button>
                <button
                  className="cs-modal__btn cs-modal__btn--danger"
                  onClick={() => { setShowModal(false); onRedeploy?.() }}
                >
                  <span className="material-icons">refresh</span>
                  Redeploy Project
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    )
  }

  // ── Deploy / Redeploy buttons ────────────────────────────────────────────────
  const isRedeploy = mode === 'redeploy'
  const isBusy = loading
  const actionLabel = isRedeploy ? 'Redeploy Idea' : 'Deploy Idea!'

  const handleAction = () => {
    if (disabled || isBusy) return
    if (isRedeploy) { onRedeploy?.(); return }
    onDeploy?.()
  }

  return (
    <button
      className={`connection-status connection-status--action ${isRedeploy ? 'connection-status--redeploy' : 'connection-status--deploy'} ${disabled ? 'connection-status--disabled' : ''}`}
      type="button"
      onClick={handleAction}
      disabled={disabled || isBusy}
      title={disabledReason || actionLabel}
    >
      <span className="material-icons">
        {isBusy ? 'hourglass_top' : isRedeploy ? 'refresh' : 'rocket_launch'}
      </span>
      <span className="connection-status__text">
        {isBusy ? 'Deploying...' : actionLabel}
      </span>
    </button>
  )
}
