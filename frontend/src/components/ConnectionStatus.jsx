import './ConnectionStatus.scss'

export default function ConnectionStatus({
  mode = 'hidden',
  disabled = false,
  disabledReason = '',
  loading = false,
  onDeploy,
  onRedeploy,
}) {
  if (mode === 'hidden') return null

  if (mode === 'deployed') {
    return (
      <div className="connection-status connection-status--deployed" title="This idea is already deployed.">
        <span className="material-icons">check_circle</span>
        <span className="connection-status__text">Idea Deployed!</span>
      </div>
    )
  }

  if (mode === 'deploying') {
    return (
      <div className="connection-status connection-status--deploying" title="Deployment is currently running.">
        <span className="material-icons">sync</span>
        <span className="connection-status__text">Deploying...</span>
      </div>
    )
  }

  const isRedeploy = mode === 'redeploy'
  const isBusy = loading
  const actionLabel = isRedeploy ? 'Redeploy Idea' : 'Deploy Idea!'

  const handleAction = () => {
    if (disabled || isBusy) return
    if (isRedeploy) {
      onRedeploy?.()
      return
    }
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
