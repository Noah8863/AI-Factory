import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { submitIdea, getIdeas } from '../utils/api'
import './Dashboard.scss'

const TEMPLATES = [
  {
    label: 'Web App',
    icon: 'language',
    text: 'Build a web application that ',
  },
  {
    label: 'REST API',
    icon: 'api',
    text: 'Create a REST API that ',
  },
  {
    label: 'Dashboard',
    icon: 'dashboard',
    text: 'Build an admin dashboard that displays ',
  },
  {
    label: 'CLI Tool',
    icon: 'terminal',
    text: 'Create a command-line tool that ',
  },
  {
    label: 'Data Pipeline',
    icon: 'account_tree',
    text: 'Build a data pipeline that ingests, processes, and outputs ',
  },
]

const STATUS_META = {
  pending:    { label: 'Pending',    icon: 'schedule',      color: 'amber'   },
  processing: { label: 'Processing', icon: 'sync',          color: 'sky'     },
  completed:  { label: 'Completed',  icon: 'check_circle',  color: 'emerald' },
}

const DRAFT_KEY = 'aif_draft'
const MAX_CHARS = 3000

function formatDate(iso) {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function truncate(str, n = 160) {
  return str.length > n ? str.slice(0, n) + '…' : str
}

export default function Dashboard() {
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('aif_user') || 'null')

  const [text, setText] = useState(() => localStorage.getItem(DRAFT_KEY) || '')
  const [ideas, setIdeas] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const [loadingIdeas, setLoadingIdeas] = useState(true)
  const [activeNav, setActiveNav] = useState('new')
  const textareaRef = useRef(null)
  const saveTimer = useRef(null)

  // Redirect if not logged in
  useEffect(() => {
    if (!user) navigate('/login')
  }, [])

  // Load existing ideas
  const fetchIdeas = useCallback(async () => {
    try {
      const res = await getIdeas()
      setIdeas(res.data)
    } catch {
      // Backend may not be running — fail silently
    } finally {
      setLoadingIdeas(false)
    }
  }, [])

  useEffect(() => { fetchIdeas() }, [fetchIdeas])

  // Auto-save draft
  useEffect(() => {
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      localStorage.setItem(DRAFT_KEY, text)
    }, 800)
    return () => clearTimeout(saveTimer.current)
  }, [text])

  const handleTemplate = (tpl) => {
    setText(tpl.text)
    textareaRef.current?.focus()
  }

  const handleSubmit = async () => {
    if (!text.trim()) return
    setSubmitting(true)
    setError('')
    try {
      const res = await submitIdea(text.trim())
      setIdeas((prev) => [res.data, ...prev])
      setText('')
      localStorage.removeItem(DRAFT_KEY)
      setSubmitted(true)
      setTimeout(() => setSubmitted(false), 3000)
    } catch {
      setError('Could not reach the backend. Make sure the API server is running.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('aif_user')
    localStorage.removeItem(DRAFT_KEY)
    navigate('/')
  }

  const charCount = text.length
  const charColor =
    charCount > MAX_CHARS * 0.9 ? 'rose' : charCount > MAX_CHARS * 0.7 ? 'amber' : 'default'

  return (
    <div className="dashboard">
      {/* ── Sidebar ──────────────────────────────────────────────── */}
      <aside className="sidebar">
        <Link to="/" className="sidebar__logo">
          <span className="material-icons">auto_awesome</span>
          AI Factory
        </Link>

        <nav className="sidebar__nav">
          <button
            className={`sidebar__item ${activeNav === 'new' ? 'sidebar__item--active' : ''}`}
            onClick={() => setActiveNav('new')}
          >
            <span className="material-icons">add_circle</span>
            New Idea
          </button>
          <button
            className={`sidebar__item ${activeNav === 'history' ? 'sidebar__item--active' : ''}`}
            onClick={() => setActiveNav('history')}
          >
            <span className="material-icons">history</span>
            My Ideas
            {ideas.length > 0 && (
              <span className="sidebar__badge">{ideas.length}</span>
            )}
          </button>
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__user">
            <div className="sidebar__avatar">
              {user?.username?.[0]?.toUpperCase() ?? 'U'}
            </div>
            <span className="sidebar__username">{user?.username}</span>
          </div>
          <button className="sidebar__logout" onClick={handleLogout} title="Logout">
            <span className="material-icons">logout</span>
          </button>
        </div>
      </aside>

      {/* ── Main ─────────────────────────────────────────────────── */}
      <main className="dashboard__main">

        {activeNav === 'new' && (
          <div className="idea-panel">
            <div className="idea-panel__header">
              <div>
                <h1 className="idea-panel__title">New Idea</h1>
                <p className="idea-panel__sub">
                  Describe what you want to build. Be as detailed or as vague as you like.
                </p>
              </div>
            </div>

            {/* Templates */}
            <div className="templates">
              <p className="templates__label">
                <span className="material-icons">bolt</span>
                Quick start
              </p>
              <div className="templates__chips">
                {TEMPLATES.map((t) => (
                  <button
                    key={t.label}
                    className="template-chip"
                    onClick={() => handleTemplate(t)}
                  >
                    <span className="material-icons">{t.icon}</span>
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Textarea */}
            <div className="idea-input">
              <textarea
                ref={textareaRef}
                className="idea-input__textarea"
                placeholder="e.g. Build a SaaS app where users can upload CSV files, visualize the data in charts, and share dashboards with their team via link. Include user authentication, a free tier with up to 3 dashboards, and a paid tier with unlimited dashboards..."
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={MAX_CHARS}
                spellCheck
              />

              <div className="idea-input__footer">
                <div className="idea-input__meta">
                  <span className={`idea-input__chars idea-input__chars--${charColor}`}>
                    {charCount.toLocaleString()} / {MAX_CHARS.toLocaleString()}
                  </span>
                  {charCount > 0 && (
                    <span className="idea-input__autosave">
                      <span className="material-icons">cloud_done</span>
                      Draft saved
                    </span>
                  )}
                </div>

                <button
                  className="idea-input__submit"
                  onClick={handleSubmit}
                  disabled={!text.trim() || submitting || charCount > MAX_CHARS}
                >
                  {submitting ? (
                    <>
                      <span className="idea-input__spinner" />
                      Submitting…
                    </>
                  ) : submitted ? (
                    <>
                      <span className="material-icons">check_circle</span>
                      Submitted!
                    </>
                  ) : (
                    <>
                      Submit Idea
                      <span className="material-icons">send</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {error && (
              <div className="idea-panel__error">
                <span className="material-icons">warning</span>
                {error}
              </div>
            )}

            {/* Tips */}
            <div className="tips">
              <p className="tips__heading">
                <span className="material-icons">lightbulb</span>
                Tips for better results
              </p>
              <ul className="tips__list">
                <li>Describe the <strong>end goal</strong>, not the implementation details.</li>
                <li>Mention the <strong>target users</strong> and their key actions.</li>
                <li>Include any <strong>tech preferences</strong> (language, framework, database).</li>
                <li>Specify <strong>must-have features</strong> vs. nice-to-haves.</li>
              </ul>
            </div>
          </div>
        )}

        {activeNav === 'history' && (
          <div className="history-panel">
            <div className="history-panel__header">
              <h1 className="idea-panel__title">My Ideas</h1>
              <p className="idea-panel__sub">
                All submitted ideas and their current status.
              </p>
            </div>

            {loadingIdeas ? (
              <div className="history-panel__loading">
                <span className="idea-input__spinner" style={{ width: 24, height: 24 }} />
              </div>
            ) : ideas.length === 0 ? (
              <div className="history-panel__empty">
                <span className="material-icons">inbox</span>
                <p>No ideas submitted yet.</p>
                <button
                  className="template-chip"
                  onClick={() => setActiveNav('new')}
                >
                  <span className="material-icons">add</span>
                  Submit your first idea
                </button>
              </div>
            ) : (
              <div className="ideas-list">
                {ideas.map((idea) => {
                  const meta = STATUS_META[idea.status] ?? STATUS_META.pending
                  return (
                    <div key={idea.id} className="idea-card">
                      <div className="idea-card__top">
                        <span className={`idea-card__status idea-card__status--${meta.color}`}>
                          <span className="material-icons">{meta.icon}</span>
                          {meta.label}
                        </span>
                        <span className="idea-card__date">{formatDate(idea.created_at)}</span>
                      </div>
                      <p className="idea-card__content">{truncate(idea.content)}</p>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
