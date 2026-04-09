import { useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import './Navbar.scss'

export default function Navbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const isLoggedIn = !!localStorage.getItem('aif_user')
  const isDashboard = location.pathname === '/dashboard'
  const [menuOpen, setMenuOpen] = useState(false)

  const handleLogout = () => {
    localStorage.removeItem('aif_user')
    navigate('/')
  }

  const close = () => setMenuOpen(false)

  return (
    <nav className="navbar">
      <div className="navbar__inner">
        <Link to={isLoggedIn ? '/dashboard' : '/'} className="navbar__logo" onClick={close}>
          <span className="material-icons">auto_awesome</span>
          AI Factory
        </Link>

        {/* Desktop links */}
        <div className="navbar__links">
          {isLoggedIn ? (
            <>
              {!isDashboard && (
                <Link to="/dashboard" className="navbar__link">Dashboard</Link>
              )}
              <button onClick={handleLogout} className="navbar__logout">
                <span className="material-icons">logout</span>
                Logout
              </button>
            </>
          ) : (
            <>
              <a href="#how-it-works" className="navbar__link">How It Works</a>
              <a href="#features" className="navbar__link">Features</a>
              <Link to="/login" className="btn btn--primary navbar__cta">
                Get Started
              </Link>
            </>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          className={`navbar__hamburger ${menuOpen ? 'navbar__hamburger--open' : ''}`}
          onClick={() => setMenuOpen((o) => !o)}
          aria-label="Toggle menu"
        >
          <span /><span /><span />
        </button>
      </div>

      {/* Mobile drawer */}
      {menuOpen && (
        <div className="navbar__drawer">
          {isLoggedIn ? (
            <>
              {!isDashboard && (
                <Link to="/dashboard" className="navbar__drawer-link" onClick={close}>
                  <span className="material-icons">dashboard</span>
                  Dashboard
                </Link>
              )}
              <button
                className="navbar__drawer-link navbar__drawer-link--danger"
                onClick={() => { handleLogout(); close() }}
              >
                <span className="material-icons">logout</span>
                Logout
              </button>
            </>
          ) : (
            <>
              <a href="#how-it-works" className="navbar__drawer-link" onClick={close}>
                <span className="material-icons">info</span>
                How It Works
              </a>
              <a href="#features" className="navbar__drawer-link" onClick={close}>
                <span className="material-icons">bolt</span>
                Features
              </a>
              <Link to="/login" className="navbar__drawer-cta" onClick={close}>
                Get Started
                <span className="material-icons">arrow_forward</span>
              </Link>
            </>
          )}
        </div>
      )}
    </nav>
  )
}
