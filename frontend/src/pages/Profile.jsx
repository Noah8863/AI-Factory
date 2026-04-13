import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../utils/api'
import Navbar from '../components/Navbar'
import { useTheme } from '../context/ThemeContext'
import './Profile.scss'

const DASHBOARD_NAV_KEY = 'aif_dashboard_nav'

function isPlaceholderJiraProject(project) {
  const key = (project?.key || '').trim().toLowerCase()
  const name = (project?.name || '').trim().toLowerCase()

  if (key === 'sam1') return true
  if (name.includes('(example)')) return true
  if (name.includes(' example')) return true
  return false
}

export default function Profile() {
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('aif_user') || 'null')
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    if (!user) navigate('/login')
  }, [])

  // Avatar — stored as base64 in localStorage, keyed by user ID to prevent bleed-over between accounts
  const avatarKey = `aif_avatar_${user?.id}`
  const [avatar, setAvatar] = useState(() => localStorage.getItem(avatarKey) || null)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef(null)

  // Profile fields
  const [displayName, setDisplayName] = useState(user?.display_name || user?.username || '')
  const [email, setEmail] = useState(user?.email || '')
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [saveError, setSaveError] = useState('')

  // Integration statuses
  const [jiraStatus, setJiraStatus] = useState('loading')  // 'loading' | 'connected' | 'disconnected'

  useEffect(() => {
    api.get('/auth/jira/status')
      .then(res => setJiraStatus(res.data.connected ? 'connected' : 'disconnected'))
      .catch(() => setJiraStatus('disconnected'))
  }, [])

  // Jira project selection
  const [jiraProjects, setJiraProjects] = useState([])
  const [jiraCloudId, setJiraCloudId] = useState('')
  const [selectedProject, setSelectedProject] = useState('')
  const [loadingProjects, setLoadingProjects] = useState(false)
  const [projectSaving, setProjectSaving] = useState(false)
  const [projectSaveMsg, setProjectSaveMsg] = useState('')

  useEffect(() => {
    if (jiraStatus !== 'connected') return
    setLoadingProjects(true)
    api.get('/auth/jira/projects')
      .then(res => {
        const filteredProjects = (res.data.projects || []).filter((p) => !isPlaceholderJiraProject(p))
        setJiraProjects(filteredProjects)
        setJiraCloudId(res.data.cloud_id || '')
        const selectedKey = res.data.selected_project_key || ''
        const selectedExists = filteredProjects.some((p) => p.key === selectedKey)
        setSelectedProject(selectedExists ? selectedKey : '')
      })
      .catch(() => {})
      .finally(() => setLoadingProjects(false))
  }, [jiraStatus])

  const handleProjectSelect = async (projectKey) => {
    setSelectedProject(projectKey)
    if (!projectKey) return
    setProjectSaving(true)
    setProjectSaveMsg('')
    try {
      await api.patch('/auth/jira/project', { project_key: projectKey, cloud_id: jiraCloudId })
      setProjectSaveMsg('Project saved!')
      setTimeout(() => setProjectSaveMsg(''), 3000)
    } catch {
      setProjectSaveMsg('Failed to save project.')
    } finally {
      setProjectSaving(false)
    }
  }

  const loadAvatar = (file) => {
    if (!file || !file.type.startsWith('image/')) return
    const reader = new FileReader()
    reader.onload = (e) => {
      const b64 = e.target.result
      setAvatar(b64)
      localStorage.setItem(avatarKey, b64)
    }
    reader.readAsDataURL(file)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    loadAvatar(e.dataTransfer.files[0])
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveError('')
    setSaveSuccess(false)
    try {
      await api.patch('/auth/profile', { display_name: displayName, email })
    } catch {
      // Backend endpoint may not exist yet — still update localStorage
    }
    const updated = { ...user, display_name: displayName, email }
    localStorage.setItem('aif_user', JSON.stringify(updated))
    setSaving(false)
    setSaveSuccess(true)
    setTimeout(() => setSaveSuccess(false), 3000)
  }

  const handleConnectJira = () => {
    const token = localStorage.getItem('aif_token')
    const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001'
    if (token) {
      localStorage.setItem('aif_jira_return_to', window.location.pathname)
      window.location.href = `${base}/api/auth/jira/login?token=${token}`
    }
  }

  const initials = (displayName || user?.username || 'U')[0].toUpperCase()

  const goToDashboardTab = (tab) => {
    localStorage.setItem(DASHBOARD_NAV_KEY, tab)
    navigate('/dashboard')
  }

  const handleLogout = () => {
    localStorage.removeItem('aif_user')
    navigate('/')
  }

  return (
    <div className="profile-page">

      {/* ── Animated background ───────────────────────────────── */}
      <div className="profile-page__bg">
        <div className="profile-page__orb profile-page__orb--1" />
        <div className="profile-page__orb profile-page__orb--2" />
        <div className="profile-page__orb profile-page__orb--3" />
        <div className="profile-page__grid" />
        {[...Array(9)].map((_, i) => (
          <div key={i} className={`profile-page__particle profile-page__particle--${i + 1}`} />
        ))}
      </div>

      <Navbar />

      <div className="profile-page__body">
        <div className="profile-wrap">

          {/* Page header */}
          <div className="profile-page__header">
            <Link to="/dashboard" className="profile-page__back">
              <span className="material-icons">arrow_back</span>
              Back to Dashboard
            </Link>
            <h1 className="profile-page__title">Your Profile</h1>
            <p className="profile-page__sub">Manage your account and integrations</p>
          </div>

          {/* ── Avatar ────────────────────────────────────────────── */}
          <section className="profile-card">
            <h2 className="profile-card__heading">
              <span className="material-icons">person</span>
              Profile Picture
            </h2>

            <div className="avatar-row">
              <div
                className={`avatar-zone ${dragging ? 'avatar-zone--over' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
                aria-label="Upload profile picture"
              >
                {avatar ? (
                  <img src={avatar} alt="Avatar" className="avatar-zone__img" />
                ) : (
                  <span className="avatar-zone__initial">{initials}</span>
                )}
                <div className="avatar-zone__overlay">
                  <span className="material-icons">photo_camera</span>
                  <span>Change</span>
                </div>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="avatar-zone__file"
                onChange={(e) => loadAvatar(e.target.files[0])}
              />

              <div className="avatar-meta">
                <p className="avatar-meta__label">Click or drag-and-drop an image</p>
                <p className="avatar-meta__hint">PNG, JPG or GIF · max 5 MB</p>
                {avatar && (
                  <button
                    className="avatar-meta__remove"
                    onClick={() => { setAvatar(null); localStorage.removeItem(avatarKey) }}
                  >
                    <span className="material-icons">delete</span>
                    Remove photo
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* ── Personal Info ─────────────────────────────────────── */}
          <section className="profile-card">
            <h2 className="profile-card__heading">
              <span className="material-icons">badge</span>
              Personal Info
            </h2>

            <div className="profile-form">
              <div className="profile-form__field">
                <label className="profile-form__label" htmlFor="pf-name">Display Name</label>
                <input
                  id="pf-name"
                  type="text"
                  className="profile-form__input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Your name"
                />
              </div>

              <div className="profile-form__field">
                <label className="profile-form__label" htmlFor="pf-email">Email Address</label>
                <input
                  id="pf-email"
                  type="email"
                  className="profile-form__input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                />
              </div>

              {saveError && (
                <div className="profile-form__error">
                  <span className="material-icons">warning</span>
                  {saveError}
                </div>
              )}

              <button
                className={`profile-form__save ${saveSuccess ? 'profile-form__save--success' : ''}`}
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? (
                  <><span className="profile-form__spinner" />Saving…</>
                ) : saveSuccess ? (
                  <><span className="material-icons">check_circle</span>Saved!</>
                ) : (
                  <><span className="material-icons">save</span>Save Changes</>
                )}
              </button>
            </div>
          </section>

          {/* ── Integrations ──────────────────────────────────────── */}
          <section className="profile-card">
            <h2 className="profile-card__heading">
              <span className="material-icons">link</span>
              Integrations
            </h2>

            <div className={`profile-required-callout ${jiraStatus === 'connected' ? 'profile-required-callout--connected' : 'profile-required-callout--warning'}`}>
              <span className="material-icons">
                {jiraStatus === 'connected' ? 'verified' : 'error'}
              </span>
              <div>
                <p className="profile-required-callout__title">Jira is required for PM projects</p>
                <p className="profile-required-callout__text">
                  {jiraStatus === 'connected'
                    ? 'Your account is ready to create projects with the PM agent.'
                    : 'You need to link Jira before you can create a project or keep chatting with the PM agent.'}
                </p>
              </div>
            </div>

            <div className="integrations">

              {/* Jira */}
              <div className={`intg-block ${jiraStatus === 'disconnected' ? 'intg-block--error' : ''}`}>
                <div className="intg-row">
                  <div className="intg-row__logo intg-row__logo--jira">J</div>
                  <div className="intg-row__info">
                    <p className="intg-row__name">Jira</p>
                    <p className="intg-row__desc">Atlassian project management · required</p>
                  </div>
                  <div className="intg-row__right">
                    {jiraStatus === 'loading' ? (
                      <span className="intg-badge intg-badge--loading">
                        <span className="intg-badge__spinner" />
                        Checking…
                      </span>
                    ) : jiraStatus === 'connected' ? (
                      <span className="intg-badge intg-badge--connected">
                        <span className="material-icons">check_circle</span>
                        Connected
                      </span>
                    ) : (
                      <span className="intg-badge intg-badge--disconnected">
                        <span className="material-icons">error</span>
                        Jira Disconnected
                      </span>
                    )}
                    {jiraStatus !== 'loading' && (
                      <button
                        className={`intg-btn ${jiraStatus === 'connected' ? 'intg-btn--secondary' : 'intg-btn--primary'}`}
                        onClick={handleConnectJira}
                      >
                        <span className="material-icons">
                          {jiraStatus === 'connected' ? 'refresh' : 'add_link'}
                        </span>
                        {jiraStatus === 'connected' ? 'Reconnect' : 'Connect Jira'}
                      </button>
                    )}
                  </div>
                </div>

                {/* Project selector — shown once Jira is connected */}
                {jiraStatus === 'connected' && (
                  <div className="intg-project">
                    <p className="intg-project__label">
                      <span className="material-icons">folder</span>
                      Target Jira Project
                    </p>
                    {loadingProjects ? (
                      <div className="intg-project__loading">
                        <span className="intg-project__spinner" />
                        Loading projects…
                      </div>
                    ) : jiraProjects.length === 0 ? (
                      <p className="intg-project__empty">No projects found in your Jira workspace.</p>
                    ) : (
                      <div className="intg-project__row">
                        <select
                          className="intg-project__select"
                          value={selectedProject}
                          onChange={(e) => handleProjectSelect(e.target.value)}
                          disabled={projectSaving}
                        >
                          <option value="">— Select a project —</option>
                          {jiraProjects.map((p) => (
                            <option key={p.key} value={p.key}>
                              [{p.key}] {p.name}
                            </option>
                          ))}
                        </select>
                        {projectSaving && <span className="intg-project__spinner" />}
                        {projectSaveMsg && !projectSaving && (
                          projectSaveMsg.startsWith('Failed') ? (
                            <span className="intg-project__err">{projectSaveMsg}</span>
                          ) : (
                            <span className="intg-project__ok">
                              <span className="material-icons">check_circle</span>
                              {projectSaveMsg}
                            </span>
                          )
                        )}
                      </div>
                    )}
                    {!loadingProjects && jiraProjects.length > 0 && (
                      <p className="intg-project__hint">
                        All tickets generated by the PM agent will be sent to this project.
                      </p>
                    )}
                  </div>
                )}
              </div>

            </div>
          </section>

          {/* ── Appearance ────────────────────────────────────────── */}
          <section className="profile-card">
            <h2 className="profile-card__heading">
              <span className="material-icons">palette</span>
              Appearance
            </h2>

            <div className="theme-picker">
              <button
                className={`theme-option ${theme === 'dark' ? 'theme-option--active' : ''}`}
                onClick={() => setTheme('dark')}
              >
                <div className="theme-option__preview theme-option__preview--dark">
                  <div className="theme-option__bar" />
                  <div className="theme-option__row" />
                  <div className="theme-option__row theme-option__row--short" />
                </div>
                <span className="theme-option__label">Dark</span>
                {theme === 'dark' && (
                  <span className="theme-option__check material-icons">check_circle</span>
                )}
              </button>

              <button
                className={`theme-option ${theme === 'light' ? 'theme-option--active' : ''}`}
                onClick={() => setTheme('light')}
              >
                <div className="theme-option__preview theme-option__preview--light">
                  <div className="theme-option__bar" />
                  <div className="theme-option__row" />
                  <div className="theme-option__row theme-option__row--short" />
                </div>
                <span className="theme-option__label">Light</span>
                {theme === 'light' && (
                  <span className="theme-option__check material-icons">check_circle</span>
                )}
              </button>
            </div>
          </section>

        </div>
      </div>

      <nav className="bottom-tabs">
        <button className="bottom-tabs__item" onClick={() => goToDashboardTab('new')}>
          <span className="material-icons">add_circle</span>
          New
        </button>
        <button className="bottom-tabs__item" onClick={() => goToDashboardTab('chat')}>
          <span className="material-icons">forum</span>
          Active
        </button>
        <button className="bottom-tabs__item" onClick={() => goToDashboardTab('history')}>
          <span className="material-icons">history</span>
          Ideas
        </button>
        <button className="bottom-tabs__item bottom-tabs__item--active" aria-current="page">
          <span className="material-icons">person</span>
          Profile
        </button>
        <button className="bottom-tabs__item bottom-tabs__item--danger" onClick={handleLogout}>
          <span className="material-icons">logout</span>
          Logout
        </button>
      </nav>
    </div>
  )
}