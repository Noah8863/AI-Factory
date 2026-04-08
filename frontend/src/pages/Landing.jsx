import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import './Landing.scss'

const steps = [
  {
    number: '01',
    icon: 'edit_note',
    title: 'Describe',
    detail: 'Write your idea in plain English — no technical specs needed.',
  },
  {
    number: '02',
    icon: 'account_tree',
    title: 'Generate',
    detail: 'AI breaks your idea into structured, actionable development tasks.',
  },
  {
    number: '03',
    icon: 'smart_toy',
    title: 'Develop',
    detail: 'Specialized agents write, test, and iterate on your codebase.',
  },
  {
    number: '04',
    icon: 'rocket_launch',
    title: 'Ship',
    detail: 'Review the output and deploy with confidence.',
  },
]

const features = [
  {
    icon: 'psychology',
    title: 'Natural Language Input',
    description:
      'No forms, no templates. Just describe what you want and the system handles interpretation.',
  },
  {
    icon: 'hub',
    title: 'Multi-Agent Orchestration',
    description:
      'Tasks are distributed across specialized AI agents — architect, developer, tester — working in parallel.',
  },
  {
    icon: 'history',
    title: 'Full Idea History',
    description:
      'Every idea you submit is saved. Track status, revisit past projects, and iterate over time.',
  },
  {
    icon: 'bolt',
    title: 'Instant Task Breakdown',
    description:
      'Your input is parsed and decomposed into prioritized subtasks the moment you hit submit.',
  },
  {
    icon: 'lock',
    title: 'Private by Default',
    description:
      'Your ideas are yours. Each workspace is isolated and only accessible by you.',
  },
  {
    icon: 'tune',
    title: 'Iterative Refinement',
    description:
      'Not happy with the output? Refine your idea and re-submit — agents pick up from where they left off.',
  },
]

export default function Landing() {
  return (
    <div className="landing">
      <Navbar />

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="hero">
        <div className="hero__bg">
          <div className="hero__orb hero__orb--1" />
          <div className="hero__orb hero__orb--2" />
          <div className="hero__orb hero__orb--3" />
          <div className="hero__grid" />
        </div>

        <div className="hero__content">
          <div className="hero__badge">
            <span className="material-icons">auto_awesome</span>
            AI-Powered Development Platform
          </div>

          <h1 className="hero__title">
            From Idea<br />
            to Code.<br />
            <span className="gradient-text">Instantly.</span>
          </h1>

          <p className="hero__subtitle">
            Describe your vision in plain English. AI Factory orchestrates
            intelligent agents to plan, architect, and build your software —
            end to end.
          </p>

          <div className="hero__actions">
            <Link to="/login" className="btn btn--primary btn--lg">
              Start Building
              <span className="material-icons">arrow_forward</span>
            </Link>
            <a href="#how-it-works" className="btn btn--ghost btn--lg">
              See How It Works
            </a>
          </div>

          <div className="hero__stats">
            <div className="hero__stat">
              <span className="hero__stat-value">4</span>
              <span className="hero__stat-label">AI Agent Types</span>
            </div>
            <div className="hero__stat-divider" />
            <div className="hero__stat">
              <span className="hero__stat-value">∞</span>
              <span className="hero__stat-label">Ideas Supported</span>
            </div>
            <div className="hero__stat-divider" />
            <div className="hero__stat">
              <span className="hero__stat-value">0</span>
              <span className="hero__stat-label">Code Required</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── How It Works ─────────────────────────────────────────── */}
      <section className="steps-section" id="how-it-works">
        <div className="container">
          <div className="section-header">
            <p className="section-label">Process</p>
            <h2 className="section-title">How It Works</h2>
            <p className="section-sub">
              Four steps from imagination to implementation.
            </p>
          </div>

          <div className="steps-grid">
            {steps.map((step, i) => (
              <div key={i} className="step-card">
                <div className="step-card__top">
                  <span className="step-card__number">{step.number}</span>
                  <div className="step-card__icon-wrap">
                    <span className="material-icons">{step.icon}</span>
                  </div>
                </div>
                <h3 className="step-card__title">{step.title}</h3>
                <p className="step-card__detail">{step.detail}</p>
                {i < steps.length - 1 && (
                  <div className="step-card__arrow">
                    <span className="material-icons">arrow_forward</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────────────────── */}
      <section className="features-section" id="features">
        <div className="container">
          <div className="section-header">
            <p className="section-label">Capabilities</p>
            <h2 className="section-title">Everything You Need</h2>
            <p className="section-sub">
              A complete pipeline from imagination to deployed code.
            </p>
          </div>

          <div className="features-grid">
            {features.map((f, i) => (
              <div key={i} className="feature-card">
                <div className="feature-card__icon">
                  <span className="material-icons">{f.icon}</span>
                </div>
                <h3 className="feature-card__title">{f.title}</h3>
                <p className="feature-card__desc">{f.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────── */}
      <section className="cta-section">
        <div className="container">
          <div className="cta-card">
            <div className="cta-card__orb" />
            <p className="section-label">Get Started</p>
            <h2 className="cta-card__title">
              Ready to Build<br />
              <span className="gradient-text">Something Great?</span>
            </h2>
            <p className="cta-card__sub">
              Start with a single sentence. AI Factory takes it from there.
            </p>
            <Link to="/login" className="btn btn--primary btn--lg">
              Open the Factory
              <span className="material-icons">arrow_forward</span>
            </Link>
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────── */}
      <footer className="footer">
        <div className="container">
          <div className="footer__inner">
            <div className="footer__logo">
              <span className="material-icons">auto_awesome</span>
              AI Factory
            </div>
            <p className="footer__copy">© 2026 AI Factory. All rights reserved.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
