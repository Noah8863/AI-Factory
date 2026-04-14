import { useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import './Navbar.scss'

export default function Navbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const isLoggedIn = !!localStorage.getItem('aif_user')
  const isDashboard = location.pathname === '/dashboard'
  const [menuOpen, setMenuOpen] = useState(false)
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)

  const openLogoutConfirm = () => {
    setShowLogoutConfirm(true)
    setMenuOpen(false)
  }

  const handleLogout = () => {
    localStorage.removeItem('aif_user')
    navigate('/')
    setShowLogoutConfirm(false)
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
              <Link to="/profile" className="navbar__link">Profile</Link>
              <button onClick={openLogoutConfirm} className="navbar__logout">
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
              <Link to="/profile" className="navbar__drawer-link" onClick={close}>
                <span className="material-icons">person</span>
                Profile
              </Link>
              <button
                className="navbar__drawer-link navbar__drawer-link--danger"
                onClick={openLogoutConfirm}
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

      {showLogoutConfirm && (
        <div className="navbar__confirm-overlay" onClick={() => setShowLogoutConfirm(false)}>
          <div className="navbar__confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="navbar__confirm-icon">
              <span className="material-icons">logout</span>
            </div>
            <h3 className="navbar__confirm-title">Log out of AI Factory?</h3>
            <p className="navbar__confirm-text">
              You will be signed out and returned to the home page.
            </p>
            <div className="navbar__confirm-actions">
              <button className="navbar__confirm-cancel" onClick={() => setShowLogoutConfirm(false)}>
                Cancel
              </button>
              <button className="navbar__confirm-logout" onClick={handleLogout}>
                Logout
              </button>
            </div>
          </div>
        </div>
      )}
    </nav>
  )
}
