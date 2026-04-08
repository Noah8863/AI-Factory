import { Link, useNavigate, useLocation } from 'react-router-dom'
import './Navbar.scss'

export default function Navbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const isLoggedIn = !!localStorage.getItem('aif_user')
  const isDashboard = location.pathname === '/dashboard'

  const handleLogout = () => {
    localStorage.removeItem('aif_user')
    navigate('/')
  }

  return (
    <nav className="navbar">
      <div className="navbar__inner">
        <Link to={isLoggedIn ? '/dashboard' : '/'} className="navbar__logo">
          <span className="material-icons">auto_awesome</span>
          AI Factory
        </Link>

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
      </div>
    </nav>
  )
}
