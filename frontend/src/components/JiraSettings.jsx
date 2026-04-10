import { useEffect, useRef, useState } from 'react'
import api from '../utils/api'
import './JiraSettings.scss'

// ── helpers ───────────────────────────────────────────────────────────────────
const authHeader = () => {
  const t = localStorage.getItem('aif_token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}

// ── sub-views ─────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="js-skeleton">
      <div className="js-skeleton__bar js-skeleton__bar--long" />
      <div className="js-skeleton__bar js-skeleton__bar--short" />
    </div>
  )
}

function ErrorBanner({ message, onRetry }) {
  return (
    <div className="js-error">
      <span className="material-icons">error_outline</span>
      <span>{message}</span>
      <button className="js-error__retry" onClick={onRetry}>
        <span className="material-icons">refresh</span>
        Retry
      </button>
    </div>
  )
}

function DisconnectedPrompt() {
  const token   = localStorage.getItem('aif_token')
  const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

  return (
    <div className="js-disconnected">
      <div className="js-disconnected__icon">
        <span className="material-icons">link_off</span>
      </div>
      <p className="js-disconnected__text">
        Connect your Jira account to automatically create tickets during PM sessions.
      </p>
      <button
        className="js-disconnected__btn"
        onClick={() => {
          window.location.href = `${apiBase}/api/auth/jira/login${token ? `?token=${token}` : ''}`
        }}
      >
        <span className="material-icons">link</span>
        Connect Jira
      </button>
    </div>
  )
}

function SaveBadge({ state }) {
  if (state === 'idle') return null
  return (
    <span className={`js-save-badge js-save-badge--${state}`}>
      {state === 'saving' && <span className="js-save-badge__spinner" />}
      {state === 'saved'  && <span className="material-icons">check_circle</span>}
      {state === 'error'  && <span className="material-icons">error_outline</span>}
      {state === 'saving' ? 'Saving…' : state === 'saved' ? 'Saved' : 'Failed to save'}
    </span>
  )
}

// ── main component ────────────────────────────────────────────────────────────
export default function JiraSettings({ className = '', onProjectSelect }) {
  // page-level state
  const [loadState, setLoadState] = useState('loading') // loading | ready | error
  const [errMsg,    setErrMsg]    = useState('')

  // data state
  const [connected,  setConnected]  = useState(false)
  const [projects,   setProjects]   = useState([])
  const [cloudId,    setCloudId]    = useState('')
  const [selected,   setSelected]   = useState(null) // { key, name } | null

  // dropdown state
  const [isOpen,   setIsOpen]   = useState(false)
  const [search,   setSearch]   = useState('')
  const [saveState, setSave]    = useState('idle') // idle | saving | saved | error

  const wrapRef   = useRef(null)
  const searchRef = useRef(null)

  // ── load projects ─────────────────────────────────────────────────────────
  const load = async () => {
    setLoadState('loading')
    setErrMsg('')
    try {
      const res = await api.get('/auth/jira/projects', { headers: authHeader() })
      const { cloud_id, projects: list, selected_project_key } = res.data

      setCloudId(cloud_id)
      setProjects(list)
      setConnected(true)

      if (selected_project_key) {
        const match = list.find(p => p.key === selected_project_key)
        setSelected(match
          ? { key: match.key, name: match.name }
          : { key: selected_project_key, name: selected_project_key },
        )
      }
      setLoadState('ready')
    } catch (err) {
      // 400 means no Jira token — treat as "not connected", not an error
      if (err.response?.status === 400) {
        setConnected(false)
        setLoadState('ready')
      } else {
        setErrMsg(err.response?.data?.detail || 'Could not load Jira projects.')
        setLoadState('error')
      }
    }
  }

  useEffect(() => { load() }, [])

  // ── close dropdown on outside click ──────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setIsOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // ── focus search when dropdown opens ─────────────────────────────────────
  useEffect(() => {
    if (isOpen) searchRef.current?.focus()
  }, [isOpen])

  // ── select a project ──────────────────────────────────────────────────────
  const pick = async (proj) => {
    setIsOpen(false)
    setSearch('')
    setSelected({ key: proj.key, name: proj.name })
    setSave('saving')
    try {
      await api.patch(
        '/auth/jira/project',
        { project_key: proj.key, cloud_id: cloudId },
        { headers: authHeader() },
      )
      setSave('saved')
      onProjectSelect?.(proj.key)
      setTimeout(() => setSave('idle'), 2800)
    } catch {
      setSave('error')
      setSelected(null)
      setTimeout(() => setSave('idle'), 3000)
    }
  }

  // ── filtered list ─────────────────────────────────────────────────────────
  const filtered = projects.filter(p => {
    const q = search.toLowerCase()
    return p.name.toLowerCase().includes(q) || p.key.toLowerCase().includes(q)
  })

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className={`js-root ${className}`}>
      {/* ── Header ──────────────────────────────────────────────── */}
      <div className="js-header">
        <div className="js-header__left">
          <div className="js-header__jira-dot">
            <span className="material-icons">task_alt</span>
          </div>
          <span className="js-header__title">Jira Project</span>
        </div>

        {loadState === 'ready' && (
          <span className={`js-status ${connected ? 'js-status--on' : 'js-status--off'}`}>
            <span className="js-status__dot" />
            {connected ? 'Connected' : 'Not connected'}
          </span>
        )}
      </div>

      {/* ── Body ────────────────────────────────────────────────── */}
      {loadState === 'loading' && <Skeleton />}

      {loadState === 'error' && (
        <ErrorBanner message={errMsg} onRetry={load} />
      )}

      {loadState === 'ready' && !connected && <DisconnectedPrompt />}

      {loadState === 'ready' && connected && (
        <>
          <div className="js-dropdown" ref={wrapRef}>
            {/* Trigger button */}
            <button
              className={`js-trigger ${isOpen ? 'js-trigger--open' : ''}`}
              onClick={() => setIsOpen(o => !o)}
              aria-haspopup="listbox"
              aria-expanded={isOpen}
            >
              <span className="js-trigger__content">
                {selected ? (
                  <>
                    <span className="js-key-badge">{selected.key}</span>
                    <span className="js-trigger__name">{selected.name}</span>
                  </>
                ) : (
                  <span className="js-trigger__placeholder">Select a project…</span>
                )}
              </span>
              <span className={`js-trigger__chevron material-icons ${isOpen ? 'js-trigger__chevron--up' : ''}`}>
                expand_more
              </span>
            </button>

            {/* Save badge sits inline after the trigger */}
            <SaveBadge state={saveState} />

            {/* Dropdown panel */}
            {isOpen && (
              <div className="js-panel" role="listbox">
                {/* Search */}
                <div className="js-search-row">
                  <span className="material-icons">search</span>
                  <input
                    ref={searchRef}
                    className="js-search"
                    placeholder="Search projects…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                  />
                  {search && (
                    <button className="js-search-clear" onClick={() => setSearch('')}>
                      <span className="material-icons">close</span>
                    </button>
                  )}
                </div>

                {/* Project list */}
                <ul className="js-list">
                  {filtered.length === 0 ? (
                    <li className="js-list__empty">
                      <span className="material-icons">search_off</span>
                      No projects match &ldquo;{search}&rdquo;
                    </li>
                  ) : (
                    filtered.map(p => (
                      <li
                        key={p.key}
                        role="option"
                        aria-selected={selected?.key === p.key}
                        className={`js-option ${selected?.key === p.key ? 'js-option--active' : ''}`}
                        onClick={() => pick(p)}
                      >
                        <span className="js-key-badge">{p.key}</span>
                        <span className="js-option__name">{p.name}</span>
                        {selected?.key === p.key && (
                          <span className="js-option__check material-icons">check</span>
                        )}
                      </li>
                    ))
                  )}
                </ul>
              </div>
            )}
          </div>

          <p className="js-hint">
            <span className="material-icons">info</span>
            Tickets are sent to this project when you start tasking in a PM session.
          </p>
        </>
      )}
    </div>
  )
}
