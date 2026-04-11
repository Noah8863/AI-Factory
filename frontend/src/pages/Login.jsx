import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import './Login.scss'

const VALID_USERNAME = import.meta.env.VITE_AUTH_USERNAME
const VALID_PASSWORD_HASH = import.meta.env.VITE_AUTH_PASSWORD_HASH

async function sha256(str) {
  const buf = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(str)
  )
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export default function Login() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleChange = (e) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))
    setError('')
  }

const handleSubmit = async (e) => {
  e.preventDefault()
  if (!form.username.trim() || !form.password.trim()) {
    setError('Please fill in all fields.')
    return
  }
  setLoading(true)
  try {
    const res = await api.post('/auth/login', {
      email: form.username.trim(),
      password: form.password,
    })
    const { access_token, user } = res.data
    localStorage.setItem('aif_token', access_token)
    localStorage.setItem('aif_user', JSON.stringify(user))
    navigate('/dashboard')
  } catch (err) {
    setError(err.response?.data?.detail || 'Invalid email or password.')
  } finally {
    setLoading(false)
  }
}

  return (
    <div className="login-page">
      {/* Background */}
      <div className="login-page__bg">
        <div className="login-page__orb login-page__orb--1" />
        <div className="login-page__orb login-page__orb--2" />
        <div className="login-page__grid" />
      </div>

      {/* Card */}
      <div className="login-card">
        <Link to="/" className="login-card__logo">
          <span className="material-icons">auto_awesome</span>
          AI Factory
        </Link>

        <h1 className="login-card__title">Welcome back</h1>
        <p className="login-card__sub">Sign in to your workspace.</p>

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-form__field">
            <label className="login-form__label" htmlFor="username">
              Email
            </label>
            <div className="login-form__input-wrap">
              <span className="material-icons">email</span>
              <input
                id="username"
                name="username"
                type="email"
                autoComplete="username"
                autoFocus
                placeholder="you@example.com"
                value={form.username}
                onChange={handleChange}
                className="login-form__input"
              />
            </div>
          </div>

          <div className="login-form__field">
            <label className="login-form__label" htmlFor="password">
              Password
            </label>
            <div className="login-form__input-wrap">
              <span className="material-icons">lock</span>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={form.password}
                onChange={handleChange}
                className="login-form__input"
              />
            </div>
          </div>

          {error && (
            <div className="login-form__error">
              <span className="material-icons">error_outline</span>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="login-form__submit"
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="login-form__spinner" />
                Signing in…
              </>
            ) : (
              <>
                Sign In
                <span className="material-icons">arrow_forward</span>
              </>
            )}
          </button>
        </form>

        <p className="login-card__register">
          Don't have an account?{' '}
          <Link to="/register">Create one for free</Link>
        </p>

        <p className="login-card__back">
          <Link to="/">
            <span className="material-icons">arrow_back</span>
            Back to home
          </Link>
        </p>
      </div>
    </div>
  )
}
