import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../utils/api'
import './Register.scss'

// ── Step metadata ─────────────────────────────────────────────────────────────
const STEPS = [
  { id: 1, label: 'Profile',      icon: 'person_outline' },
  { id: 2, label: 'Preferences',  icon: 'tune'           },
  { id: 3, label: 'Integrations', icon: 'extension'      },
]

// ── Password strength meter ───────────────────────────────────────────────────
function PasswordStrength({ password }) {
  if (!password) return null
  let score = 0
  if (password.length >= 8)              score++
  if (/[A-Z]/.test(password))           score++
  if (/[0-9]/.test(password))           score++
  if (/[^A-Za-z0-9]/.test(password))   score++

  const meta = [
    null,
    { label: 'Weak',   cls: 'rose'    },
    { label: 'Fair',   cls: 'amber'   },
    { label: 'Good',   cls: 'sky'     },
    { label: 'Strong', cls: 'emerald' },
  ]
  const m = meta[Math.max(1, score)]
  return (
    <div className="pwd-strength">
      <div className="pwd-strength__bars">
        {[1, 2, 3, 4].map(i => (
          <div
            key={i}
            className={`pwd-strength__bar ${i <= score ? `pwd-strength__bar--${m.cls}` : ''}`}
          />
        ))}
      </div>
      <span className={`pwd-strength__label pwd-strength__label--${m.cls}`}>{m.label}</span>
    </div>
  )
}

// ── Toggle switch ─────────────────────────────────────────────────────────────
function Toggle({ checked, onChange, label, description }) {
  return (
    <div className="pref-toggle" onClick={() => onChange(!checked)}>
      <div className="pref-toggle__text">
        <span className="pref-toggle__label">{label}</span>
        {description && <span className="pref-toggle__desc">{description}</span>}
      </div>
      <div className={`pref-toggle__track ${checked ? 'pref-toggle__track--on' : ''}`}>
        <div className="pref-toggle__thumb" />
      </div>
    </div>
  )
}

// ── Step 1: Profile ───────────────────────────────────────────────────────────
function Step1({ profile, errors, showPwd, showConf, setShowPwd, setShowConf, update }) {
  return (
    <div className="reg-step__content">
      <div className="reg-step__header">
        <div className="reg-step__icon-wrap">
          <span className="material-icons">rocket_launch</span>
        </div>
        <h2 className="reg-step__title">Let's get you set up</h2>
        <p className="reg-step__sub">Create your account in just a few steps.</p>
      </div>

      <div className="reg-fields">
        {/* Display Name */}
        <div className={`reg-field ${errors.displayName ? 'reg-field--error' : ''}`}>
          <label className="reg-field__label">Full Name</label>
          <div className="reg-field__wrap">
            <span className="material-icons">badge</span>
            <input
              type="text"
              placeholder="Jane Doe"
              value={profile.displayName}
              onChange={update('displayName')}
              autoFocus
              className="reg-field__input"
            />
          </div>
          {errors.displayName && <span className="reg-field__err">{errors.displayName}</span>}
        </div>

        {/* Email */}
        <div className={`reg-field ${errors.email ? 'reg-field--error' : ''}`}>
          <label className="reg-field__label">Email</label>
          <div className="reg-field__wrap">
            <span className="material-icons">email</span>
            <input
              type="email"
              placeholder="you@example.com"
              value={profile.email}
              onChange={update('email')}
              className="reg-field__input"
            />
          </div>
          {errors.email && <span className="reg-field__err">{errors.email}</span>}
        </div>

        {/* Password */}
        <div className={`reg-field ${errors.password ? 'reg-field--error' : ''}`}>
          <label className="reg-field__label">Password</label>
          <div className="reg-field__wrap">
            <span className="material-icons">lock</span>
            <input
              type={showPwd ? 'text' : 'password'}
              placeholder="••••••••"
              value={profile.password}
              onChange={update('password')}
              className="reg-field__input"
            />
            <button
              type="button"
              className="reg-field__eye"
              onClick={() => setShowPwd(v => !v)}
              tabIndex={-1}
            >
              <span className="material-icons">{showPwd ? 'visibility_off' : 'visibility'}</span>
            </button>
          </div>
          <PasswordStrength password={profile.password} />
          {errors.password && <span className="reg-field__err">{errors.password}</span>}
        </div>

        {/* Confirm password */}
        <div className={`reg-field ${errors.confirm ? 'reg-field--error' : ''}`}>
          <label className="reg-field__label">Confirm Password</label>
          <div className="reg-field__wrap">
            <span className="material-icons">lock_outline</span>
            <input
              type={showConf ? 'text' : 'password'}
              placeholder="••••••••"
              value={profile.confirm}
              onChange={update('confirm')}
              className="reg-field__input"
            />
            <button
              type="button"
              className="reg-field__eye"
              onClick={() => setShowConf(v => !v)}
              tabIndex={-1}
            >
              <span className="material-icons">{showConf ? 'visibility_off' : 'visibility'}</span>
            </button>
          </div>
          {errors.confirm && <span className="reg-field__err">{errors.confirm}</span>}
        </div>
      </div>
    </div>
  )
}

// ── Step 2: Preferences ───────────────────────────────────────────────────────
function Step2({ prefs, setPrefs }) {
  const set = (key) => (val) => setPrefs(p => ({ ...p, [key]: val }))

  const personalities = [
    { id: 'concise',  icon: 'bolt',       label: 'Concise',  desc: 'Short, punchy answers. Just the facts.' },
    { id: 'balanced', icon: 'balance',    label: 'Balanced', desc: 'A healthy mix of detail and brevity.'   },
    { id: 'detailed', icon: 'menu_book',  label: 'Detailed', desc: 'Thorough explanations with full context.' },
  ]

  return (
    <div className="reg-step__content">
      <div className="reg-step__header">
        <div className="reg-step__icon-wrap reg-step__icon-wrap--violet">
          <span className="material-icons">auto_fix_high</span>
        </div>
        <h2 className="reg-step__title">Make it yours</h2>
        <p className="reg-step__sub">Customize how AI Factory looks and feels for you.</p>
      </div>

      {/* Theme selector */}
      <div className="pref-section">
        <p className="pref-section__label">
          <span className="material-icons">palette</span>
          Interface Theme
        </p>
        <div className="theme-cards">
          <button
            className={`theme-card theme-card--dark ${prefs.theme === 'dark' ? 'theme-card--active' : ''}`}
            onClick={() => set('theme')('dark')}
          >
            <div className="theme-card__preview theme-card__preview--dark">
              <div className="theme-card__preview-bar" />
              <div className="theme-card__preview-row" />
              <div className="theme-card__preview-row theme-card__preview-row--short" />
            </div>
            <span className="theme-card__name">Dark</span>
            {prefs.theme === 'dark' && (
              <span className="theme-card__check material-icons">check_circle</span>
            )}
          </button>

          <button
            className={`theme-card theme-card--light ${prefs.theme === 'light' ? 'theme-card--active' : ''}`}
            onClick={() => set('theme')('light')}
          >
            <div className="theme-card__preview theme-card__preview--light">
              <div className="theme-card__preview-bar" />
              <div className="theme-card__preview-row" />
              <div className="theme-card__preview-row theme-card__preview-row--short" />
            </div>
            <span className="theme-card__name">Light</span>
            {prefs.theme === 'light' && (
              <span className="theme-card__check material-icons">check_circle</span>
            )}
          </button>
        </div>
      </div>

      {/* Notifications */}
      <div className="pref-section">
        <p className="pref-section__label">
          <span className="material-icons">notifications</span>
          Notifications
        </p>
        <Toggle
          checked={prefs.notifications}
          onChange={set('notifications')}
          label="Email notifications"
          description="Get updates when your projects hit milestones or need attention."
        />
      </div>

      {/* AI Personality */}
      <div className="pref-section">
        <p className="pref-section__label">
          <span className="material-icons">psychology</span>
          AI Personality
        </p>
        <div className="personality-cards">
          {personalities.map(p => (
            <button
              key={p.id}
              className={`personality-card ${prefs.personality === p.id ? 'personality-card--active' : ''}`}
              onClick={() => set('personality')(p.id)}
            >
              <span className="material-icons">{p.icon}</span>
              <strong>{p.label}</strong>
              <span>{p.desc}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Step 3: Integrations ──────────────────────────────────────────────────────
function Step3({ errors, submitting, onBack, onCreate }) {
  return (
    <div className="reg-step__content">
      <div className="reg-step__header">
        <div className="reg-step__icon-wrap reg-step__icon-wrap--sky">
          <span className="material-icons">hub</span>
        </div>
        <h2 className="reg-step__title">Connect your tools</h2>
        <p className="reg-step__sub">
          Link your external services to unlock the full AI Factory experience.
          You can always do this later from settings.
        </p>
      </div>

      <div className="integration-cards">
        {/* Jira */}
        <div className="integration-card">
          <div className="integration-card__left">
            <div className="integration-card__logo integration-card__logo--jira">
              <span className="material-icons">task_alt</span>
            </div>
            <div className="integration-card__info">
              <strong>Jira</strong>
              <span>Auto-create tickets from your PM conversations.</span>
            </div>
          </div>
          <button
            className="integration-card__btn integration-card__btn--enabled"
            onClick={() => {
              const token = localStorage.getItem('aif_token')
              const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
              window.location.href = `${base}/api/auth/jira/login${token ? `?token=${token}` : ''}`
            }}
          >
            <span className="material-icons">link</span>
            Connect Jira
          </button>
        </div>

        {/* GitHub */}
        <div className="integration-card">
          <div className="integration-card__left">
            <div className="integration-card__logo integration-card__logo--github">
              <span className="material-icons">code</span>
            </div>
            <div className="integration-card__info">
              <strong>GitHub</strong>
              <span>Push generated code directly to your repositories.</span>
            </div>
          </div>
          <button className="integration-card__btn" disabled>
            <span className="material-icons">link</span>
            Connect GitHub
          </button>
        </div>
      </div>

      <p className="integration-skip">
        <span className="material-icons">info</span>
        Integrations can be connected anytime from your account settings.
      </p>

      {errors.submit && (
        <div className="reg-error">
          <span className="material-icons">error_outline</span>
          {errors.submit}
        </div>
      )}

      {/* Final CTA lives inside step 3 for visual prominence */}
      <button
        className="reg-create-btn"
        onClick={onCreate}
        disabled={submitting}
      >
        {submitting ? (
          <><span className="reg-create-btn__spinner" />Creating your account…</>
        ) : (
          <>
            <span className="material-icons">auto_awesome</span>
            Create Account
          </>
        )}
      </button>
    </div>
  )
}

// ── Main Register component ───────────────────────────────────────────────────
export default function Register() {
  const navigate = useNavigate()

  const [step, setStep]       = useState(1)
  const [direction, setDir]   = useState('forward')
  const [stepKey, setStepKey] = useState(0)

  const [profile, setProfile] = useState({
    displayName: '',
    email: '',
    password: '',
    confirm: '',
  })

  const [prefs, setPrefs] = useState({
    theme: 'dark',
    notifications: true,
    personality: 'balanced',
  })

  const [errors, setErrors]         = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [showPwd, setShowPwd]       = useState(false)
  const [showConf, setShowConf]     = useState(false)

  const transition = (next, dir) => {
    setDir(dir)
    setStep(next)
    setStepKey(k => k + 1)
  }

  const updateProfile = (field) => (e) => {
    setProfile(p => ({ ...p, [field]: e.target.value }))
    setErrors(er => ({ ...er, [field]: '' }))
  }

  const validateStep1 = () => {
    const e = {}
    if (!profile.displayName.trim())                                     e.displayName = 'Full name is required'
    if (!profile.email.trim() || !/\S+@\S+\.\S+/.test(profile.email))   e.email       = 'Valid email required'
    if (profile.password.length < 8)                                     e.password    = 'At least 8 characters'
    if (profile.password !== profile.confirm)                            e.confirm     = 'Passwords do not match'
    setErrors(e)
    return !Object.keys(e).length
  }

  const handleNext = () => {
    if (step === 1 && !validateStep1()) return
    if (step < 3) transition(step + 1, 'forward')
  }

  const handleBack = () => {
    if (step > 1) transition(step - 1, 'back')
  }

  const handleCreate = async () => {
    setSubmitting(true)
    setErrors({})
    try {
      // Derive a valid username from email prefix
      const rawUsername = profile.email.split('@')[0].replace(/[^a-zA-Z0-9_]/g, '_')
      const username = rawUsername.length >= 3 ? rawUsername : rawUsername + '_usr'

      console.log('🔍 Attempting registration with:', {
        email: profile.email.trim(),
        username,
        display_name: profile.displayName.trim(),
      })

      const res = await api.post('/auth/register', {
        email:        profile.email.trim(),
        username,
        password:     profile.password,
        display_name: profile.displayName.trim(),
      })

      console.log('✅ Registration successful:', res.data)
      const { access_token, user } = res.data
      localStorage.setItem('aif_token', access_token)
      localStorage.setItem('aif_user', JSON.stringify({
        id:           user.id,
        username:     user.username,
        email:        user.email,
        display_name: user.display_name,
      }))
      navigate('/dashboard')
    } catch (err) {
      console.error('❌ Registration error:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status,
        statusText: err.response?.statusText,
        headers: err.response?.headers,
        fullError: err,
      })
      
      let errorMsg = 'Registration failed. Please try again.'
      
      if (err.response?.data?.detail) {
        errorMsg = err.response.data.detail
      } else if (err.response?.status === 400) {
        errorMsg = 'Invalid input. Please check your information.'
      } else if (err.response?.status === 500) {
        errorMsg = `Server error: ${err.response?.data?.detail || 'Unknown error'}`
      } else if (err.message === 'Network Error') {
        errorMsg = 'Network error. Make sure the backend is running at http://localhost:8000'
      } else if (!err.response) {
        errorMsg = `Error: ${err.message}. Check browser console for details.`
      }
      
      setErrors({ submit: errorMsg })
    } finally {
      setSubmitting(false)
    }
  }

  const completedSteps = step - 1

  return (
    <div className="reg-page">
      {/* ── Animated background ─────────────────────────────────── */}
      <div className="reg-page__bg">
        <div className="reg-page__orb reg-page__orb--1" />
        <div className="reg-page__orb reg-page__orb--2" />
        <div className="reg-page__orb reg-page__orb--3" />
        <div className="reg-page__grid" />
        {[...Array(9)].map((_, i) => (
          <div key={i} className={`reg-page__particle reg-page__particle--${i + 1}`} />
        ))}
      </div>

      {/* ── Card ────────────────────────────────────────────────── */}
      <div className="reg-card">
        {/* Logo */}
        <Link to="/" className="reg-card__logo">
          <span className="material-icons">auto_awesome</span>
          AI Factory
        </Link>

        {/* Step indicator */}
        <div className="step-bar">
          {STEPS.map((s, idx) => {
            const isDone   = step > s.id
            const isActive = step === s.id
            return (
              <div key={s.id} className="step-bar__item">
                {idx > 0 && (
                  <div className={`step-bar__line ${step > idx ? 'step-bar__line--filled' : ''}`}>
                    <div
                      className="step-bar__line-fill"
                      style={{ width: step > idx ? '100%' : '0%' }}
                    />
                  </div>
                )}
                <div className={`
                  step-bar__circle
                  ${isActive ? 'step-bar__circle--active' : ''}
                  ${isDone   ? 'step-bar__circle--done'   : ''}
                `}>
                  {isDone
                    ? <span className="material-icons">check</span>
                    : <span className="material-icons">{s.icon}</span>
                  }
                </div>
                <span className={`step-bar__label ${isActive ? 'step-bar__label--active' : ''}`}>
                  {s.label}
                </span>
              </div>
            )
          })}
        </div>

        {/* Animated step content */}
        <div key={stepKey} className={`reg-content reg-content--${direction}`}>
          {step === 1 && (
            <Step1
              profile={profile}
              errors={errors}
              showPwd={showPwd}
              showConf={showConf}
              setShowPwd={setShowPwd}
              setShowConf={setShowConf}
              update={updateProfile}
            />
          )}
          {step === 2 && (
            <Step2 prefs={prefs} setPrefs={setPrefs} />
          )}
          {step === 3 && (
            <Step3
              errors={errors}
              submitting={submitting}
              onBack={handleBack}
              onCreate={handleCreate}
            />
          )}
        </div>

        {/* Navigation row */}
        <div className={`reg-nav ${step > 1 ? 'reg-nav--split' : ''}`}>
          {step > 1 && (
            <button className="reg-nav__back" onClick={handleBack}>
              <span className="material-icons">arrow_back</span>
              Back
            </button>
          )}
          {step < 3 && (
            <button className="reg-nav__next" onClick={handleNext}>
              Continue
              <span className="material-icons">arrow_forward</span>
            </button>
          )}
        </div>

        {/* Sign-in link */}
        <p className="reg-card__signin">
          Already have an account?{' '}
          <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
