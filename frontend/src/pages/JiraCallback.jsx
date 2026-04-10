import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../utils/api'
import './JiraCallback.scss'

// ── Loading view ──────────────────────────────────────────────────────────────
function LoadingView() {
  return (
    <div className="jira-cb__state">
      <div className="jira-cb__spinner-wrap">
        <div className="jira-cb__ring" />
        <div className="jira-cb__ring jira-cb__ring--inner" />
        <div className="jira-cb__icon-center">
          <span className="material-icons">task_alt</span>
        </div>
      </div>

      <h2 className="jira-cb__title">Verifying connection…</h2>
      <p className="jira-cb__sub">Confirming your Jira token with the server.</p>

      <div className="jira-cb__dots">
        <span /><span /><span />
      </div>
    </div>
  )
}

// ── Success view ──────────────────────────────────────────────────────────────
function SuccessView({ navigate }) {
  const burst = [0, 45, 90, 135, 180, 225, 270, 315]
  return (
    <div className="jira-cb__state jira-cb__state--success">
      <div className="jira-cb__badge jira-cb__badge--success">
        {burst.map((deg, i) => (
          <div
            key={i}
            className="jira-cb__burst-arm"
            style={{ transform: `rotate(${deg}deg)` }}
          >
            <div className={`jira-cb__burst jira-cb__burst--${i + 1}`} />
          </div>
        ))}
        <span className="material-icons">check_circle</span>
      </div>

      <h2 className="jira-cb__title">Jira Connected!</h2>
      <p className="jira-cb__sub">
        Your Jira workspace is now linked. Tickets will be automatically
        created during your PM Agent sessions.
      </p>

      <button
        className="jira-cb__btn jira-cb__btn--primary"
        onClick={() => navigate('/dashboard')}
      >
        <span className="material-icons">rocket_launch</span>
        Continue to Workspace
      </button>

      <Link to="/dashboard" className="jira-cb__link">
        Go to account settings
      </Link>
    </div>
  )
}

// ── Error view ────────────────────────────────────────────────────────────────
function ErrorView({ message, navigate }) {
  return (
    <div className="jira-cb__state jira-cb__state--error">
      <div className="jira-cb__badge jira-cb__badge--error">
        <span className="material-icons">link_off</span>
      </div>

      <h2 className="jira-cb__title">Connection Failed</h2>
      <p className="jira-cb__sub">{message}</p>

      <button
        className="jira-cb__btn jira-cb__btn--primary"
        onClick={() => navigate('/dashboard')}
      >
        <span className="material-icons">replay</span>
        Try Again
      </button>

      <button
        className="jira-cb__btn jira-cb__btn--ghost"
        onClick={() => navigate('/dashboard')}
      >
        Continue Anyway
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function JiraCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState('loading')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    const success = searchParams.get('success')
    const error   = searchParams.get('error')

    // Atlassian or backend reported an error
    if (error) {
      setErrorMsg(decodeURIComponent(error).replace(/_/g, ' '))
      setStatus('error')
      return
    }

    // No recognised flag — user probably landed here directly
    if (success !== '1') {
      setErrorMsg('No success flag found. Please try connecting Jira again.')
      setStatus('error')
      return
    }

    // Confirm the token was actually persisted in the database
    const token = localStorage.getItem('aif_token')
    if (!token) {
      setErrorMsg('Your session has expired. Please log in and reconnect Jira.')
      setStatus('error')
      return
    }

    api
      .get('/auth/jira/status', {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((res) => {
        if (res.data.connected) {
          setStatus('success')
        } else {
          setErrorMsg('Token was not saved correctly. Please try connecting again.')
          setStatus('error')
        }
      })
      .catch((err) => {
        setErrorMsg(
          err.response?.data?.detail || 'Could not verify the connection with the server.'
        )
        setStatus('error')
      })
  }, [searchParams])

  return (
    <div className="jira-cb">
      {/* Animated background */}
      <div className="jira-cb__bg">
        <div className="jira-cb__orb jira-cb__orb--1" />
        <div className="jira-cb__orb jira-cb__orb--2" />
        <div className="jira-cb__grid" />
      </div>

      <div className="jira-cb__card">
        <Link to="/" className="jira-cb__logo">
          <span className="material-icons">auto_awesome</span>
          AI Factory
        </Link>

        {status === 'loading' && <LoadingView />}
        {status === 'success' && <SuccessView navigate={navigate} />}
        {status === 'error'   && <ErrorView message={errorMsg} navigate={navigate} />}
      </div>
    </div>
  )
}
