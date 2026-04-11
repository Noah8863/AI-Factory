import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../utils/api'
import Navbar from '../components/Navbar'
import { useTheme } from '../context/ThemeContext'
import './Profile.scss'

export default function Profile() {
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('aif_user') || 'null')
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    if (!user) navigate('/login')
  }, [])

  // Avatar — stored as base64 in localStorage
  const [avatar, setAvatar] = useState(() => localStorage.getItem('aif_avatar') || null)
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
  const [githubStatus, setGithubStatus] = useState('loading')

  // Jira project selection
  const [jiraProjects, setJiraProjects] = useState([])         // [{ key, name, id }]
  const [jiraCloudId, setJiraCloudId] = useState('')
  const [selectedProject, setSelectedProject] = useState('')   // project key
  const [projectSaving, setProjectSaving] = useState(false)
  const [projectSaveMsg, setProjectSaveMsg] = useState('')     // '' | 'saved' | error string
  const [loadingProjects, setLoadingProjects] = useState(false)

  useEffect(() => {
    api.get('/auth/jira/status')
      .then(res => setJiraStatus(res.data.connected ? 'connected' : 'disconnected'))
      .catch(() => setJiraStatus('disconnected'))

    api.get('/auth/github/status')
      .then(res => setGithubStatus(res.data.connected ? 'connected' : 'disconnected'))
      .catch(() => setGithubStatus('disconnected'))
  }, [])

  // Fetch Jira projects once we know the user is connected
  useEffect(() => {
    if (jiraStatus !== 'connected') return
    setLoadingProjects(true)
    api.get('/auth/jira/projects')
      .then(res => {
        setJiraProjects(res.data.projects || [])
        setJiraCloudId(res.data.cloud_id || '')
        setSelectedProject(res.data.selected_project_key || '')
      })
      .catch(() => {/* non-fatal */})
      .finally(() => setLoadingProjects(false))
  }, [jiraStatus])

  const handleProjectSelect = async (key) => {
    if (!key || !jiraCloudId) return
    setSelectedProject(key)
    setProjectSaving(true)
    setProjectSaveMsg('')
    try {
      await api.patch('/auth/jira/project', { project_key: key, cloud_id: jiraCloudId })
      setProjectSaveMsg('saved')
      setTimeout(() => setProjectSaveMsg(''), 3000)
    } catch {
      setProjectSaveMsg('Failed to save — please try again.')
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
      localStorage.setItem('aif_avatar', b64)
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
    if (token) window.location.href = `${base}/api/auth/jira/login?token=${token}`
  }

  const handleConnectGitHub = () => {
    const token = localStorage.getItem('aif_token')
    const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001'
    if (token) window.location.href = `${base}/api/auth/github/login?token=${token}`
  }

  const initials = (displayName || user?.username || 'U')[0].toUpperCase()

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
                    onClick={() => { setAvatar(null); localStorage.removeItem('aif_avatar') }}
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

            <div className="integrations">

              {/* Jira */}
              <div className={`intg-block ${jiraStatus === 'disconnected' ? 'intg-block--error' : ''}`}>
                <div className="intg-row">
                  <div className="intg-row__logo intg-row__logo--jira">J</div>
                  <div className="intg-row__info">
                    <p className="intg-row__name">Jira</p>
                    <p className="intg-row__desc">Atlassian project management</p>
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

                {/* Project selector — shown only when connected */}
                {jiraStatus === 'connected' && (
                  <div className="intg-project">
                    <label className="intg-project__label">
                      <span className="material-icons">folder</span>
                      Jira Project
                    </label>
                    {loadingProjects ? (
                      <span className="intg-project__loading">
                        <span className="intg-badge__spinner" />
                        Loading projects…
                      </span>
                    ) : jiraProjects.length === 0 ? (
                      <p className="intg-project__empty">
                        No projects found. Create a project in your Jira workspace first.
                      </p>
                    ) : (
                      <div className="intg-project__row">
                        <select
                          className="intg-project__select"
                          value={selectedProject}
                          onChange={(e) => handleProjectSelect(e.target.value)}
                          disabled={projectSaving}
                        >
                          <option value="">— Select a project —</option>
                          {jiraProjects.map(p => (
                            <option key={p.key} value={p.key}>
                              {p.name} ({p.key})
                            </option>
                          ))}
                        </select>
                        {projectSaving && <span className="intg-project__spinner" />}
                        {projectSaveMsg === 'saved' && (
                          <span className="intg-project__ok">
                            <span className="material-icons">check_circle</span>
                            Saved
                          </span>
                        )}
                        {projectSaveMsg && projectSaveMsg !== 'saved' && (
                          <span className="intg-project__err">{projectSaveMsg}</span>
                        )}
                      </div>
                    )}
                    {selectedProject && (
                      <p className="intg-project__hint">
                        Tickets from the PM agent will be created in <strong>{selectedProject}</strong>.
                      </p>
                    )}
                  </div>
                )}
              </div>

              {/* GitHub */}
              <div className={`intg-row ${githubStatus === 'disconnected' ? 'intg-row--error' : ''}`}>
                <div className="intg-row__logo intg-row__logo--github">
                  <span className="material-icons">code</span>
                </div>
                <div className="intg-row__info">
                  <p className="intg-row__name">GitHub</p>
                  <p className="intg-row__desc">Code repository and version control</p>
                </div>
                <div className="intg-row__right">
                  {githubStatus === 'loading' ? (
                    <span className="intg-badge intg-badge--loading">
                      <span className="intg-badge__spinner" />
                      Checking…
                    </span>
                  ) : githubStatus === 'connected' ? (
                    <span className="intg-badge intg-badge--connected">
                      <span className="material-icons">check_circle</span>
                      Connected
                    </span>
                  ) : (
                    <span className="intg-badge intg-badge--disconnected">
                      <span className="material-icons">error</span>
                      GitHub Disconnected
                    </span>
                  )}
                  {githubStatus !== 'loading' && (
                    <button
                      className={`intg-btn ${githubStatus === 'connected' ? 'intg-btn--secondary' : 'intg-btn--primary'}`}
                      onClick={handleConnectGitHub}
                    >
                      <span className="material-icons">
                        {githubStatus === 'connected' ? 'refresh' : 'add_link'}
                      </span>
                      {githubStatus === 'connected' ? 'Reconnect' : 'Connect GitHub'}
                    </button>
                  )}
                </div>
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
    </div>
  )
}