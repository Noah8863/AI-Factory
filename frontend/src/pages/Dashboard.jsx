import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getIdeas, startConversation, sendMessage, startTasking, getIdeaConversation, deleteIdea } from '../utils/api'
import ChatThread from '../components/ChatThread'
import Navbar from '../components/Navbar'
import './Dashboard.scss'

const TEMPLATES = [
  { label: 'Web App',       icon: 'language',     text: 'Build a web application that ' },
  { label: 'REST API',      icon: 'api',          text: 'Create a REST API that ' },
  { label: 'Dashboard',     icon: 'dashboard',    text: 'Build an admin dashboard that displays ' },
  { label: 'CLI Tool',      icon: 'terminal',     text: 'Create a command-line tool that ' },
  { label: 'Data Pipeline', icon: 'account_tree', text: 'Build a data pipeline that ingests, processes, and outputs ' },
]

const STATUS_META = {
  pending:    { label: 'Pending',    icon: 'schedule',     color: 'amber'   },
  processing: { label: 'Processing', icon: 'sync',         color: 'sky'     },
  completed:  { label: 'Completed',  icon: 'check_circle', color: 'emerald' },
}

const DRAFT_KEY = 'aif_draft'
const MAX_CHARS = 3000

function formatDate(iso) {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function truncate(str, n = 160) {
  return str.length > n ? str.slice(0, n) + '…' : str
}

export default function Dashboard() {
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('aif_user') || 'null')
  const avatar = localStorage.getItem('aif_avatar')

  // ── Nav & view state ────────────────────────────────────────
  const [activeNav, setActiveNav] = useState('new')

  // ── Idea input state ────────────────────────────────────────
  const [text, setText] = useState(() => localStorage.getItem(DRAFT_KEY) || '')
  const [submitting, setSubmitting] = useState(false)
  const [inputError, setInputError] = useState('')
  const textareaRef = useRef(null)
  const saveTimer = useRef(null)

  // ── Conversation / chat state ────────────────────────────────
  const [conversation, setConversation] = useState(null)  // { id, idea_id, status }
  const [messages, setMessages] = useState([])            // MessageRead[]
  const [isSending, setIsSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [showReadyBanner, setShowReadyBanner] = useState(false)

  // ── History state ────────────────────────────────────────────
  const [ideas, setIdeas] = useState([])
  const [loadingIdeas, setLoadingIdeas] = useState(true)
  const [openingIdeaId, setOpeningIdeaId] = useState(null)  // idea.id currently loading
  const [deleteConfirm, setDeleteConfirm] = useState(null)   // idea pending deletion
  const [deleting, setDeleting] = useState(false)

  // ── Auth guard ───────────────────────────────────────────────
  useEffect(() => { if (!user) navigate('/login') }, [])

  // ── Load ideas ───────────────────────────────────────────────
  const fetchIdeas = useCallback(async () => {
    try {
      const res = await getIdeas()
      setIdeas(res.data)
    } catch {
      // Backend offline — fail silently
    } finally {
      setLoadingIdeas(false)
    }
  }, [])

  useEffect(() => { fetchIdeas() }, [fetchIdeas])

  // ── Auto-save draft ──────────────────────────────────────────
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

  // ── Submit idea → open conversation ──────────────────────────
  const handleSubmit = async () => {
    if (!text.trim()) return
    setSubmitting(true)
    setInputError('')
    try {
      const res = await startConversation(text.trim())
      const { conversation: conv, messages: msgs } = res.data
      setConversation(conv)
      setMessages(msgs)
      setShowReadyBanner(conv.status === 'ready_to_task')
      setText('')
      localStorage.removeItem(DRAFT_KEY)
      setActiveNav('chat')
      fetchIdeas()
    } catch {
      setInputError('Could not reach the backend. Make sure the API server is running.')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Re-open a past idea's chat ───────────────────────────────
  const handleOpenIdeaChat = async (idea) => {
    setOpeningIdeaId(idea.id)
    try {
      const res = await getIdeaConversation(idea.id)
      const { conversation: conv, messages: msgs } = res.data
      setConversation(conv)
      setMessages(msgs)
      setShowReadyBanner(conv.status === 'ready_to_task')
      setSendError('')
      setActiveNav('chat')
    } catch {
      // no conversation yet or error — nothing to open
    } finally {
      setOpeningIdeaId(null)
    }
  }

  // ── Delete idea ──────────────────────────────────────────────
  const handleDeleteIdea = (idea) => {
    setDeleteConfirm(idea)
  }

  const confirmDeleteIdea = async () => {
    if (!deleteConfirm) return
    setDeleting(true)
    try {
      await deleteIdea(deleteConfirm.id)
      setIdeas((prev) => prev.filter((i) => i.id !== deleteConfirm.id))
      // If the active conversation belongs to this idea, clear it
      if (conversation?.idea_id === deleteConfirm.id) {
        setConversation(null)
        setMessages([])
        setShowReadyBanner(false)
        if (activeNav === 'chat') setActiveNav('new')
      }
      setDeleteConfirm(null)
    } catch {
      // Keep modal open on error so user can retry
    } finally {
      setDeleting(false)
    }
  }

  // ── Send message in active conversation ──────────────────────
  const handleSendMessage = async (content) => {
    if (!conversation) return
    setSendError('')

    const optimisticMsg = {
      id: `optimistic-${Date.now()}`,
      conversation_id: conversation.id,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
      _optimistic: true,
    }
    setMessages((prev) => [...prev, optimisticMsg])
    setIsSending(true)

    try {
      const res = await sendMessage(conversation.id, content)
      const { conversation: conv, messages: msgs } = res.data
      setConversation(conv)
      setMessages(msgs)
      if (conv.status === 'ready_to_task') setShowReadyBanner(true)
    } catch {
      setMessages((prev) => prev.filter((m) => m.id !== optimisticMsg.id))
      setSendError('Failed to send. Please try again.')
    } finally {
      setIsSending(false)
    }
  }

  // ── Start tasking ────────────────────────────────────────────
  const handleStartTasking = async () => {
    if (!conversation) return
    setShowReadyBanner(false)
    try {
      const res = await startTasking(conversation.id)
      setConversation(res.data)
    } catch {
      setSendError('Failed to start tasking. Please try again.')
    }
  }

  const handleContinueChat = () => setShowReadyBanner(false)
  const handleBackFromChat  = () => setActiveNav('new')

  const handleLogout = () => {
    localStorage.removeItem('aif_user')
    localStorage.removeItem(DRAFT_KEY)
    navigate('/')
  }

  const charCount = text.length
  const charColor = charCount > MAX_CHARS * 0.9 ? 'rose' : charCount > MAX_CHARS * 0.7 ? 'amber' : 'default'

  return (
    <div className="dashboard">

      {/* ── Animated background ───────────────────────────────── */}
      <div className="dashboard__bg">
        <div className="dashboard__orb dashboard__orb--1" />
        <div className="dashboard__orb dashboard__orb--2" />
        <div className="dashboard__orb dashboard__orb--3" />
        <div className="dashboard__grid" />
        {[...Array(9)].map((_, i) => (
          <div key={i} className={`dashboard__particle dashboard__particle--${i + 1}`} />
        ))}
      </div>

      <Navbar />

      {/* ── Confirmation modal ─────────────────────────────────── */}
      {deleteConfirm && (
        <div className="confirm-overlay" onClick={() => !deleting && setDeleteConfirm(null)}>
          <div className="confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-modal__icon">
              <span className="material-icons">delete_forever</span>
            </div>
            <h2 className="confirm-modal__title">Delete this idea?</h2>
            <p className="confirm-modal__body">
              This will permanently delete the idea and its entire chat history. This action cannot be undone.
              <br /><br />
              <span className="confirm-modal__preview">"{truncate(deleteConfirm.content, 80)}"</span>
            </p>
            <div className="confirm-modal__actions">
              <button
                className="confirm-modal__cancel"
                onClick={() => setDeleteConfirm(null)}
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                className="confirm-modal__confirm"
                onClick={confirmDeleteIdea}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Mobile bottom tab bar ──────────────────────────────── */}
      <nav className="bottom-tabs">
        <button
          className={`bottom-tabs__item ${activeNav === 'new' ? 'bottom-tabs__item--active' : ''}`}
          onClick={() => setActiveNav('new')}
        >
          <span className="material-icons">add_circle</span>
          New
        </button>
        {conversation && (
          <button
            className={`bottom-tabs__item ${activeNav === 'chat' ? 'bottom-tabs__item--active' : ''}`}
            onClick={() => setActiveNav('chat')}
          >
            <span className="material-icons">forum</span>
            Chat
          </button>
        )}
        <button
          className={`bottom-tabs__item ${activeNav === 'history' ? 'bottom-tabs__item--active' : ''}`}
          onClick={() => setActiveNav('history')}
        >
          <span className="material-icons">history</span>
          Ideas
        </button>
        <Link to="/profile" className="bottom-tabs__item">
          <span className="material-icons">person</span>
          Profile
        </Link>
        <button className="bottom-tabs__item bottom-tabs__item--danger" onClick={handleLogout}>
          <span className="material-icons">logout</span>
          Logout
        </button>
      </nav>

      {/* ── Sidebar ────────────────────────────────────────────── */}
      <aside className="sidebar">
        <nav className="sidebar__nav">
          <button
            className={`sidebar__item ${activeNav === 'new' ? 'sidebar__item--active' : ''}`}
            onClick={() => setActiveNav('new')}
          >
            <span className="material-icons">add_circle</span>
            New Idea
          </button>

          {conversation && (
            <button
              className={`sidebar__item ${activeNav === 'chat' ? 'sidebar__item--active' : ''}`}
              onClick={() => setActiveNav('chat')}
            >
              <span className="material-icons">forum</span>
              Active Chat
              {conversation.status === 'ready_to_task' && (
                <span className="sidebar__dot sidebar__dot--green" title="Ready to task" />
              )}
              {conversation.status === 'tasking' && (
                <span className="sidebar__dot sidebar__dot--indigo" title="Tasking" />
              )}
            </button>
          )}

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
          <Link to="/profile" className="sidebar__user sidebar__user--link">
            <div className="sidebar__avatar">
              {avatar
                ? <img src={avatar} alt="avatar" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                : (user?.username?.[0]?.toUpperCase() ?? 'U')
              }
            </div>
            <span className="sidebar__username">{user?.display_name || user?.username}</span>
          </Link>
          <button className="sidebar__logout" onClick={handleLogout} title="Logout">
            <span className="material-icons">logout</span>
          </button>
        </div>
      </aside>

      {/* ── Main ───────────────────────────────────────────────── */}
      <main className={`dashboard__main ${activeNav === 'chat' ? 'dashboard__main--chat' : ''}`}>

        {/* ── New Idea ──────────────────────────────────────────── */}
        {activeNav === 'new' && (
          <div className="idea-panel">
            <div className="idea-panel__header">
              <h1 className="idea-panel__title">New Idea</h1>
              <p className="idea-panel__sub">
                Describe what you want to build. Be as detailed or as vague as you like.
              </p>
            </div>

            <div className="templates">
              <p className="templates__label">
                <span className="material-icons">bolt</span>
                Quick start
              </p>
              <div className="templates__chips">
                {TEMPLATES.map((t) => (
                  <button key={t.label} className="template-chip" onClick={() => handleTemplate(t)}>
                    <span className="material-icons">{t.icon}</span>
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="idea-input">
              <textarea
                ref={textareaRef}
                className="idea-input__textarea"
                placeholder="e.g. Build a SaaS app where users can upload CSV files, visualize the data in charts, and share dashboards with their team via link…"
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
                    <><span className="idea-input__spinner" />Starting…</>
                  ) : (
                    <>Start Chat<span className="material-icons">send</span></>
                  )}
                </button>
              </div>
            </div>

            {inputError && (
              <div className="idea-panel__error">
                <span className="material-icons">warning</span>
                {inputError}
              </div>
            )}

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

        {/* ── Active Chat ───────────────────────────────────────── */}
        {activeNav === 'chat' && conversation && (
          <ChatThread
            messages={messages}
            status={conversation.status}
            isSending={isSending}
            sendError={sendError}
            showReadyBanner={showReadyBanner}
            onSendMessage={handleSendMessage}
            onContinueChat={handleContinueChat}
            onStartTasking={handleStartTasking}
            onBack={handleBackFromChat}
          />
        )}

        {/* ── My Ideas ──────────────────────────────────────────── */}
        {activeNav === 'history' && (
          <div className="history-panel">
            <div className="history-panel__header">
              <h1 className="idea-panel__title">My Ideas</h1>
              <p className="idea-panel__sub">All submitted ideas and their current status.</p>
            </div>

            {loadingIdeas ? (
              <div className="history-panel__loading">
                <span style={{ width: 24, height: 24, border: '2px solid', borderTopColor: 'transparent', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
              </div>
            ) : ideas.length === 0 ? (
              <div className="history-panel__empty">
                <span className="material-icons">inbox</span>
                <p>No ideas submitted yet.</p>
                <button className="template-chip" onClick={() => setActiveNav('new')}>
                  <span className="material-icons">add</span>
                  Submit your first idea
                </button>
              </div>
            ) : (
              <div className="ideas-list">
                {ideas.map((idea) => {
                  const meta = STATUS_META[idea.status] ?? STATUS_META.pending
                  const isLoading = openingIdeaId === idea.id
                  return (
                    <div key={idea.id} className="idea-card">
                      <div className="idea-card__top">
                        <span className={`idea-card__status idea-card__status--${meta.color}`}>
                          <span className="material-icons">{meta.icon}</span>
                          {meta.label}
                        </span>
                        <div className="idea-card__meta-right">
                          <span className="idea-card__id">#{idea.id}</span>
                          <span className="idea-card__date">{formatDate(idea.created_at)}</span>
                        </div>
                      </div>
                      <p className="idea-card__content">{truncate(idea.content)}</p>
                      <div className="idea-card__actions">
                        <button
                          className="idea-card__btn idea-card__btn--open"
                          onClick={() => handleOpenIdeaChat(idea)}
                          disabled={isLoading}
                        >
                          {isLoading ? (
                            <><span className="idea-card__spinner" />Loading…</>
                          ) : (
                            <><span className="material-icons">forum</span>Open Chat</>
                          )}
                        </button>
                        <button
                          className="idea-card__btn idea-card__btn--delete"
                          onClick={() => handleDeleteIdea(idea)}
                          title="Delete idea"
                        >
                          <span className="material-icons">delete</span>
                          Delete
                        </button>
                      </div>
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
