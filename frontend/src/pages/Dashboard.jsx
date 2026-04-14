import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api, { getIdeas, startConversation, sendMessage, startTasking, getIdeaConversation, deleteIdea, reopenConversation, getAgentTickets, getIdeaTickets, retryTicket, cancelAgents, deployIdea } from '../utils/api'
import ChatThread from '../components/ChatThread'
import DevProgress from '../components/DevProgress'
import Navbar from '../components/Navbar'
import './Dashboard.scss'

const JIRA_REQUIRED_MESSAGE = 'Please connect your Jira account before making a project.'
const JIRA_PROJECT_REQUIRED_MESSAGE = 'Please select a target Jira project on your Profile page before starting a chat.'

const PROJECT_TYPES = [
  { id: 'web-app',    label: 'Web App',      icon: 'layers',      pmLabel: 'Web App',      color: 'indigo'  },
  { id: 'backend',    label: 'Backend API',  icon: 'dns',         pmLabel: 'Backend API',  color: 'sky'     },
  { id: 'script',     label: 'Script / CLI', icon: 'terminal',    pmLabel: 'Script / CLI', color: 'emerald' },
  { id: 'mobile',     label: 'Mobile App',   icon: 'smartphone',  pmLabel: 'Mobile App',   color: 'violet'  },
  { id: 'devops',     label: 'DevOps Tool',  icon: 'build',       pmLabel: 'DevOps Tool',  color: 'amber'   },
]

const PROJECT_TYPE_PREFIX_RE = /^\s*\[PROJECT_TYPE:\s*([^\]]+)\]\s*/i

const PROJECT_TAG_KEYS = [
  'has_frontend',
  'has_backend',
  'is_script',
  'is_mobile_app',
  'is_devops_program',
  'is_full_stack',
  'has_mixed_technologies',
]

function normalizeProjectTags(tags) {
  if (!tags) return null

  let parsed = tags
  if (typeof parsed === 'string') {
    const trimmed = parsed.trim()
    if (!trimmed) return null
    try {
      parsed = JSON.parse(trimmed)
    } catch {
      return null
    }
  }

  const normalized = Object.fromEntries(PROJECT_TAG_KEYS.map((k) => [k, false]))

  if (Array.isArray(parsed)) {
    for (const key of parsed) {
      if (key in normalized) normalized[key] = true
    }
  } else if (typeof parsed === 'object' && parsed !== null) {
    for (const key of PROJECT_TAG_KEYS) {
      if (key in parsed) normalized[key] = !!parsed[key]
    }
  } else {
    return null
  }

  normalized.is_full_stack = normalized.has_frontend && normalized.has_backend
  return Object.values(normalized).some(Boolean) ? normalized : null
}

function normalizeConversation(conv) {
  if (!conv || typeof conv !== 'object') return conv
  return {
    ...conv,
    project_tags: normalizeProjectTags(conv.project_tags),
    deployment_status: conv.deployment_status || 'not_deployed',
    deployment_live_url: conv.deployment_live_url || null,
    deployment_error: conv.deployment_error || null,
  }
}

function parseJiraStatusPayload(payload) {
  const connected = !!payload?.connected
  const projectSelected = !!(
    payload?.project_selected ??
    payload?.jira_project_key ??
    payload?.selected_project_key
  )
  return {
    jiraStatus: connected ? 'connected' : 'disconnected',
    jiraProjectSelected: projectSelected,
  }
}


function getIdeaPill(idea, ideaTicketsMap) {
  const data = ideaTicketsMap[idea.id]
  if (!data || data.tickets.length === 0) {
    return { label: 'Requirements in Need', icon: null, color: 'rose' }
  }
  const hasCancelled = data.tickets.some(t => t.status === 'cancelled')
  if (hasCancelled) {
    return { label: 'Canceled', icon: 'cancel', color: 'amber' }
  }
  const hasFailed = data.tickets.some(t => t.status === 'failed')
  if (hasFailed) {
    return { label: 'Failed!', icon: 'cancel', color: 'rose' }
  }
  if (data.stillPending > 0) {
    return { label: 'Programming', icon: 'hardware', color: 'sky' }
  }
  return { label: 'Completed!', icon: 'check_circle', color: 'emerald' }
}

const DRAFT_KEY = 'aif_draft'
const DASHBOARD_NAV_KEY = 'aif_dashboard_nav'
const MAX_CHARS = 3000

function getInitialDashboardNav() {
  const stored = localStorage.getItem(DASHBOARD_NAV_KEY)
  return ['new', 'chat', 'history'].includes(stored) ? stored : 'new'
}

function formatDate(iso) {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function truncate(str, n = 160) {
  return str.length > n ? str.slice(0, n) + '…' : str
}

function getIdeaSummaryText(idea) {
  const rawContent = (idea?.content || '').trim()
  const cleanedContent = rawContent.replace(PROJECT_TYPE_PREFIX_RE, '').trim()
  return (idea?.title || '').trim() || cleanedContent || 'Project idea'
}

function getIdeaDisplayMeta(idea) {
  const rawContent = (idea?.content || '').trim()
  const typeMatch = rawContent.match(PROJECT_TYPE_PREFIX_RE)
  const rawTypeLabel = typeMatch?.[1]?.trim() || null
  const cleanedContent = rawContent.replace(PROJECT_TYPE_PREFIX_RE, '').trim()

  const normalizedType = rawTypeLabel?.toLowerCase() || ''
  const mappedType = PROJECT_TYPES.find((type) => {
    const options = [type.label, type.pmLabel]
      .filter(Boolean)
      .map((value) => value.toLowerCase())
    return options.includes(normalizedType)
  })

  const typePill = rawTypeLabel
    ? {
        label: mappedType?.label || rawTypeLabel,
        icon: mappedType?.icon || 'category',
        color: mappedType?.color || 'indigo',
      }
    : null

  const headlineSource = getIdeaSummaryText(idea)
  return {
    headline: truncate(headlineSource || 'Project idea', 170),
    typePill,
  }
}

export default function Dashboard() {
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('aif_user') || 'null')
  const avatar = localStorage.getItem(`aif_avatar_${user?.id}`)

  // ── Nav & view state ────────────────────────────────────────
  const [activeNav, setActiveNav] = useState(getInitialDashboardNav)

  // ── Idea input state ────────────────────────────────────────
  const [text, setText] = useState(() => localStorage.getItem(DRAFT_KEY) || '')
  const [selectedProjectType, setSelectedProjectType] = useState(null)
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
  const [taskingResult, setTaskingResult] = useState(null)   // { jira_tickets_created, jira_error }
  const [isTaskingLoading, setIsTaskingLoading] = useState(false)
  const [devInProcess, setDevInProcess] = useState(false)
  const [isDeployActionLoading, setIsDeployActionLoading] = useState(false)
  const [agentRunError, setAgentRunError] = useState('')
  const [agentTickets, setAgentTickets] = useState([])       // TicketRead[]

  // ── History state ────────────────────────────────────────────
  const [ideas, setIdeas] = useState([])
  const [loadingIdeas, setLoadingIdeas] = useState(true)
  const [openingIdeaId, setOpeningIdeaId] = useState(null)  // idea.id currently loading
  const [deleteConfirm, setDeleteConfirm] = useState(null)   // idea pending deletion
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)
  const [jiraStatus, setJiraStatus] = useState('loading')
  const [jiraProjectSelected, setJiraProjectSelected] = useState(true) // assume true until checked
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false)
  const [mobileTabsHeight, setMobileTabsHeight] = useState(72)

  // ── Idea-level ticket tracking (for My Ideas page) ──────────
  const [ideaTicketsMap, setIdeaTicketsMap] = useState({})  // { [ideaId]: { tickets, stillPending } }

  // ── Session-expired state ────────────────────────────────────
  const [sessionExpired, setSessionExpired] = useState(false)

  // Keep polling single-flight to avoid piling up pending /tickets requests.
  const ticketsRequestInFlightRef = useRef(false)
  const activeConversationIdRef = useRef(null)

  useEffect(() => {
    activeConversationIdRef.current = conversation?.id ?? null
  }, [conversation?.id])

  useEffect(() => {
    localStorage.setItem(DASHBOARD_NAV_KEY, activeNav)
  }, [activeNav])

  useEffect(() => {
    if (activeNav === 'chat' && !conversation) {
      setActiveNav('new')
    }
  }, [activeNav, conversation])

  useEffect(() => {
    if (typeof window === 'undefined' || !window.visualViewport) return

    const viewport = window.visualViewport
    const updateKeyboardState = () => {
      const keyboardInset = Math.max(0, window.innerHeight - viewport.height)
      setIsKeyboardOpen(keyboardInset > 120)
    }

    updateKeyboardState()
    viewport.addEventListener('resize', updateKeyboardState)
    viewport.addEventListener('scroll', updateKeyboardState)

    return () => {
      viewport.removeEventListener('resize', updateKeyboardState)
      viewport.removeEventListener('scroll', updateKeyboardState)
      setIsKeyboardOpen(false)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return

    const measureTabs = () => {
      if (!window.matchMedia('(max-width: 640px)').matches) return
      const tabs = document.querySelector('.bottom-tabs')
      if (!tabs) return
      const nextHeight = Math.round(tabs.getBoundingClientRect().height)
      if (nextHeight > 0) setMobileTabsHeight(nextHeight)
    }

    measureTabs()
    window.addEventListener('resize', measureTabs)
    return () => window.removeEventListener('resize', measureTabs)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return

    const isMobile = window.matchMedia('(max-width: 640px)').matches
    const shouldLockViewport = activeNav === 'chat' && isMobile
    if (!shouldLockViewport) return

    const prevBodyOverflow = document.body.style.overflow
    const prevHtmlOverflow = document.documentElement.style.overflow
    const prevBodyOverscroll = document.body.style.overscrollBehavior

    document.body.style.overflow = 'hidden'
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overscrollBehavior = 'none'

    return () => {
      document.body.style.overflow = prevBodyOverflow
      document.documentElement.style.overflow = prevHtmlOverflow
      document.body.style.overscrollBehavior = prevBodyOverscroll
    }
  }, [activeNav])

  // ── Auth guard ───────────────────────────────────────────────
  useEffect(() => { if (!user) navigate('/login') }, [])

  // ── 401 / session-expiry handler ─────────────────────────────
  useEffect(() => {
    const handleSessionExpired = () => {
      setSessionExpired(true)
      setTimeout(() => navigate('/login'), 3000)
    }
    window.addEventListener('aif:session-expired', handleSessionExpired)
    return () => window.removeEventListener('aif:session-expired', handleSessionExpired)
  }, [navigate])

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

  useEffect(() => {
    let cancelled = false

    api.get('/auth/jira/status')
      .then((res) => {
        if (!cancelled) {
          const parsed = parseJiraStatusPayload(res.data)
          setJiraStatus(parsed.jiraStatus)
          setJiraProjectSelected(parsed.jiraProjectSelected)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setJiraStatus('disconnected')
          setJiraProjectSelected(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  // ── Fetch ticket status on demand ───────────────────────────
  const fetchTickets = useCallback(async (convId) => {
    if (!convId || ticketsRequestInFlightRef.current) return

    ticketsRequestInFlightRef.current = true
    try {
      const res = await getAgentTickets(convId, { timeout: 15000 })

      // Ignore stale responses that arrive after the user switches conversations.
      if (activeConversationIdRef.current !== convId) return

      const { tickets, still_pending } = res.data
      setAgentTickets(tickets ?? [])
      setDevInProcess((still_pending ?? 0) > 0)

      if (activeConversationIdRef.current === convId) {
        setConversation((prev) => {
          if (!prev || prev.id !== convId) return prev
          return {
            ...prev,
            deployment_status: res.data.deployment_status || prev.deployment_status || 'not_deployed',
            deployment_live_url: res.data.deployment_live_url ?? prev.deployment_live_url ?? null,
            deployment_error: res.data.deployment_error ?? prev.deployment_error ?? null,
          }
        })
      }
    } catch (err) {
      // Timeouts/network blips should not clear state or stop polling.
      if (err?.code === 'ECONNABORTED' || err?.code === 'ERR_NETWORK') return

      // No tickets yet for this conversation — clear any stale state
      if (activeConversationIdRef.current === convId) {
        setAgentTickets([])
        setDevInProcess(false)
      }
    } finally {
      ticketsRequestInFlightRef.current = false
    }
  }, [])

  // ── Poll ticket status while agents are running ──────────────
  useEffect(() => {
    const shouldPoll = !!conversation?.id && (
      devInProcess || conversation?.deployment_status === 'deploying'
    )
    if (!shouldPoll) return

    let cancelled = false
    const tick = async () => {
      if (cancelled) return
      await fetchTickets(conversation.id)
    }

    tick()
    const interval = setInterval(tick, 1000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [devInProcess, conversation?.id, conversation?.deployment_status, fetchTickets])


  // ── Fetch tickets for all ideas (My Ideas page) ─────────────
  const fetchAllIdeaTickets = useCallback(async (ideaList) => {
    const results = {}
    await Promise.all(
      ideaList.map(async (idea) => {
        try {
          const res = await getIdeaTickets(idea.id)
          const { tickets, still_pending } = res.data
          if (tickets.length > 0) {
            results[idea.id] = { tickets, stillPending: still_pending }
          }
        } catch {
          // No conversation or tickets for this idea — skip
        }
      })
    )
    setIdeaTicketsMap(prev => ({ ...prev, ...results }))
    return results
  }, [])

  // Fetch idea tickets once when switching to history tab
  useEffect(() => {
    if (activeNav !== 'history' || ideas.length === 0) return
    fetchAllIdeaTickets(ideas)
  }, [activeNav, ideas, fetchAllIdeaTickets])

  // ── Auto-save draft ──────────────────────────────────────────
  useEffect(() => {
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      localStorage.setItem(DRAFT_KEY, text)
    }, 800)
    return () => clearTimeout(saveTimer.current)
  }, [text])

  // ── Submit idea → open conversation ──────────────────────────
  const handleSubmit = async () => {
    if (!text.trim()) return
    if (jiraStatus !== 'connected') {
      setInputError(JIRA_REQUIRED_MESSAGE)
      return
    }
    if (!jiraProjectSelected) {
      setInputError(JIRA_PROJECT_REQUIRED_MESSAGE)
      return
    }
    setSubmitting(true)
    setInputError('')
    // Reset all conversation-specific state before opening the new chat
    setAgentTickets([])
    setDevInProcess(false)
    setAgentRunError('')
    setTaskingResult(null)
    setSendError('')
    try {
      const ideaContent = selectedProjectType
        ? `[PROJECT_TYPE: ${selectedProjectType.pmLabel}]\n\n${text.trim()}`
        : text.trim()
      const res = await startConversation(ideaContent)
      const { conversation: conv, messages: msgs } = res.data
      const normalizedConv = normalizeConversation(conv)
      setConversation(normalizedConv)
      setMessages(msgs)
      setShowReadyBanner(normalizedConv.status === 'ready_to_task')
      setText('')
      setSelectedProjectType(null)
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
    // Clear previous idea's state immediately so there's no flash of stale data
    setConversation(null)
    setMessages([])
    setAgentTickets([])
    setDevInProcess(false)
    setAgentRunError('')
    setTaskingResult(null)
    setSendError('')
    setShowReadyBanner(false)
    try {
      const res = await getIdeaConversation(idea.id)
      const { conversation: conv, messages: msgs } = res.data
      const normalizedConv = normalizeConversation(conv)
      setConversation(normalizedConv)
      setMessages(msgs)
      setShowReadyBanner(normalizedConv.status === 'ready_to_task')
      setActiveNav('chat')

      // Fetch current ticket status for this conversation
      await fetchTickets(normalizedConv.id)
    } catch {
      // no conversation yet or error — nothing to open
    } finally {
      setOpeningIdeaId(null)
    }
  }

  const getMostRecentIdea = () => {
    if (ideas.length === 0) return null
    return [...ideas].sort((a, b) => {
      const aTime = new Date(a.created_at || 0).getTime()
      const bTime = new Date(b.created_at || 0).getTime()
      if (bTime !== aTime) return bTime - aTime
      return (b.id || 0) - (a.id || 0)
    })[0]
  }

  const handleOpenActiveChat = async () => {
    if (openingIdeaId) return

    const mostRecentIdea = getMostRecentIdea()
    if (mostRecentIdea) {
      await handleOpenIdeaChat(mostRecentIdea)
      return
    }

    if (conversation) {
      setActiveNav('chat')
      return
    }

    setActiveNav('new')
  }

  // ── Delete idea ──────────────────────────────────────────────
  const handleDeleteIdea = (idea) => {
    setDeleteError('')
    setDeleteConfirm(idea)
  }

  const confirmDeleteIdea = async () => {
    if (!deleteConfirm) return
    setDeleting(true)
    setDeleteError('')
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
      setDeleteError('Failed to delete. Please try again.')
    } finally {
      setDeleting(false)
    }
  }

  // ── Send message in active conversation ──────────────────────
  const handleSendMessage = async (content) => {
    if (!conversation) return
    if (jiraStatus !== 'connected') {
      setSendError(JIRA_REQUIRED_MESSAGE)
      return
    }
    if (!jiraProjectSelected) {
      setSendError(JIRA_PROJECT_REQUIRED_MESSAGE)
      return
    }
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
      const normalizedConv = normalizeConversation(conv)
      setConversation(normalizedConv)
      setMessages(msgs)
      if (normalizedConv.status === 'ready_to_task') setShowReadyBanner(true)
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
    if (jiraStatus !== 'connected') {
      setSendError(JIRA_REQUIRED_MESSAGE)
      return
    }
    if (!jiraProjectSelected) {
      setSendError(JIRA_PROJECT_REQUIRED_MESSAGE)
      return
    }
    setShowReadyBanner(false)
    setTaskingResult(null)
    setIsTaskingLoading(true)
    setDevInProcess(false)
    setAgentRunError('')
    setAgentTickets([])
    const previousStatus = conversation.status
    // Optimistically mark the conversation as "tasking" in local state so that
    // if the user navigates away via the sidebar and comes back (React state
    // preserved), the ready banner will not re-appear mid-call.
    setConversation(prev => prev ? { ...prev, status: 'tasking' } : prev)
    try {
      const res = await startTasking(conversation.id)
      const { conversation: conv, messages: msgs, jira_tickets_created, jira_error } = res.data
      const normalizedConv = normalizeConversation(conv)
      setConversation(normalizedConv)
      setMessages(msgs)
      setTaskingResult({ jira_tickets_created, jira_error })

      // Backend auto-triggers dev agents after storing tickets.
      // Fetch ticket state once after a short delay so the UI shows them.
      setDevInProcess(true)
      setTimeout(() => fetchTickets(normalizedConv.id), 3000)
    } catch {
      // Revert optimistic status if start-tasking fails.
      setConversation(prev => prev ? { ...prev, status: previousStatus } : prev)
      setSendError('Failed to start tasking. Please try again.')
    } finally {
      setIsTaskingLoading(false)
    }
  }

  const handleRefreshTickets = () => conversation && fetchTickets(conversation.id)

  // ── Stop running agents ───────────────────────────────────────
  const handleCancelAgents = async () => {
    if (!conversation) {
      return { ok: false, error: 'No active conversation found.' }
    }

    try {
      await cancelAgents(conversation.id)
      setDevInProcess(false)
      await fetchTickets(conversation.id)
      return { ok: true }
    } catch (err) {
      const error = err?.response?.data?.detail || 'Failed to stop agents. Please try again.'
      setAgentRunError(error)
      return { ok: false, error }
    }
  }

  const handleContinueChat = () => setShowReadyBanner(false)
  const handleBackFromChat  = () => { setActiveNav('new'); setTaskingResult(null) }

  const handleDeployIdea = async (mode = 'deploy') => {
    if (!conversation || isDeployActionLoading) return
    setIsDeployActionLoading(true)
    setAgentRunError('')

    try {
      const res = await deployIdea(conversation.id, mode)
      const nextConversation = normalizeConversation(res.data?.conversation)
      if (nextConversation) {
        setConversation(nextConversation)
      } else {
        setConversation((prev) => prev ? { ...prev, deployment_status: 'deploying', deployment_error: null } : prev)
      }
      // Start polling immediately so the header state transitions when deployment finishes.
      await fetchTickets(conversation.id)
    } catch (err) {
      const detail = err?.response?.data?.detail || 'Failed to start deployment. Please try again.'
      setAgentRunError(detail)
    } finally {
      setIsDeployActionLoading(false)
    }
  }

  // ── Retry a single failed ticket ─────────────────────────────
  const handleRetryTicket = async (ticketDbId) => {
    if (!conversation) return
    try {
      const res = await retryTicket(conversation.id, ticketDbId)
      const { tickets } = res.data
      setAgentTickets(tickets)
      setDevInProcess(true)
      setAgentRunError('')
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to retry ticket. Please try again.'
      setAgentRunError(detail)
    }
  }

  // ── Add more requirements ─────────────────────────────────────
  const handleAddMoreRequirements = async () => {
    if (!conversation) return
    try {
      const res = await reopenConversation(conversation.id)
      const { conversation: conv, messages: msgs } = res.data
      setConversation(normalizeConversation(conv))
      setMessages(msgs)
      setTaskingResult(null)
      setShowReadyBanner(false)
      setDevInProcess(false)
      setAgentRunError('')
      setAgentTickets([])
    } catch {
      setSendError('Failed to reopen conversation. Please try again.')
    }
  }

  // Placeholder for future bug-report workflow.
  const handleReportBug = () => {}

  const handleLogout = () => {
    setShowLogoutConfirm(true)
  }

  const confirmLogout = () => {
    localStorage.removeItem('aif_user')
    localStorage.removeItem(DRAFT_KEY)
    navigate('/')
  }

  const charCount = text.length
  const charColor = charCount > MAX_CHARS * 0.9 ? 'rose' : charCount > MAX_CHARS * 0.7 ? 'amber' : 'default'
  const activeChatAvailable = ideas.length > 0 || !!conversation
  const activeChatDisabled = !activeChatAvailable || !!openingIdeaId
  const uiLockedByTasking = isTaskingLoading
  const navLockedHint = 'Please wait while Jira tickets are being created.'
  const activeChatTitle = ideas.length > 0
    ? 'Open most recent idea chat'
    : conversation
      ? 'Open active chat'
      : 'No active chat yet'
  const isDecisionMode =
    activeNav === 'chat' &&
    !!conversation &&
    showReadyBanner

  const effectiveMobileOffset = (activeNav === 'chat' && !isKeyboardOpen && !isDecisionMode)
    ? mobileTabsHeight
    : 0
  const deletePreviewText = deleteConfirm
    ? truncate(getIdeaSummaryText(deleteConfirm), 110)
    : ''

  const dashboardClassName = `dashboard${activeNav === 'chat' ? ' dashboard--chat' : ''}${isKeyboardOpen ? ' dashboard--keyboard-open' : ''}${isDecisionMode ? ' dashboard--decision-active' : ''}`
  const dashboardStyle = {
    '--mobile-chat-offset': `${effectiveMobileOffset}px`,
  }

  return (
    <div className={dashboardClassName} style={dashboardStyle}>

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
        <div className="confirm-overlay" onClick={() => !deleting && (setDeleteConfirm(null), setDeleteError(''))}>
          <div className="confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-modal__icon">
              <span className="material-icons">delete_forever</span>
            </div>
            <h2 className="confirm-modal__title">Delete this idea?</h2>
            <p className="confirm-modal__body">
              This will permanently delete the idea and its entire chat history. This action cannot be undone.
              <br /><br />
              <span className="confirm-modal__preview">"{deletePreviewText}"</span>
            </p>
            {deleteError && (
              <p className="confirm-modal__error">{deleteError}</p>
            )}
            <div className="confirm-modal__actions">
              <button
                className="confirm-modal__cancel"
                onClick={() => { setDeleteConfirm(null); setDeleteError('') }}
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

      {showLogoutConfirm && (
        <div className="confirm-overlay" onClick={() => setShowLogoutConfirm(false)}>
          <div className="confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-modal__icon">
              <span className="material-icons">logout</span>
            </div>
            <h2 className="confirm-modal__title">Log out of AI Factory?</h2>
            <p className="confirm-modal__body">
              You will be signed out from this session and returned to the home page.
            </p>
            <div className="confirm-modal__actions">
              <button
                className="confirm-modal__cancel"
                onClick={() => setShowLogoutConfirm(false)}
              >
                Cancel
              </button>
              <button
                className="confirm-modal__confirm"
                onClick={confirmLogout}
              >
                Logout
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
          disabled={uiLockedByTasking}
          title={uiLockedByTasking ? navLockedHint : undefined}
        >
          <span className="material-icons">add_circle</span>
          New
        </button>
        <button
          className={`bottom-tabs__item ${activeNav === 'chat' ? 'bottom-tabs__item--active' : ''} ${activeChatDisabled || uiLockedByTasking ? 'bottom-tabs__item--disabled' : ''}`}
          onClick={handleOpenActiveChat}
          disabled={activeChatDisabled || uiLockedByTasking}
          title={uiLockedByTasking ? navLockedHint : activeChatTitle}
        >
          <span className="material-icons">forum</span>
          Active
        </button>
        <button
          className={`bottom-tabs__item ${activeNav === 'history' ? 'bottom-tabs__item--active' : ''}`}
          onClick={() => setActiveNav('history')}
          disabled={uiLockedByTasking}
          title={uiLockedByTasking ? navLockedHint : undefined}
        >
          <span className="material-icons">history</span>
          Ideas
        </button>
        <Link
          to="/profile"
          className={`bottom-tabs__item ${uiLockedByTasking ? 'bottom-tabs__item--disabled' : ''}`}
          onClick={(event) => {
            if (uiLockedByTasking) {
              event.preventDefault()
            }
          }}
          aria-disabled={uiLockedByTasking}
          title={uiLockedByTasking ? navLockedHint : undefined}
        >
          <span className="material-icons">person</span>
          Profile
        </Link>
        <button
          className="bottom-tabs__item bottom-tabs__item--danger"
          onClick={handleLogout}
          disabled={uiLockedByTasking}
          title={uiLockedByTasking ? navLockedHint : undefined}
        >
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
            disabled={uiLockedByTasking}
            title={uiLockedByTasking ? navLockedHint : undefined}
          >
            <span className="material-icons">add_circle</span>
            New Idea
          </button>

          <button
            className={`sidebar__item ${activeNav === 'chat' ? 'sidebar__item--active' : ''} ${activeChatDisabled || uiLockedByTasking ? 'sidebar__item--disabled' : ''}`}
            onClick={handleOpenActiveChat}
            disabled={activeChatDisabled || uiLockedByTasking}
            title={uiLockedByTasking ? navLockedHint : activeChatTitle}
          >
            <span className="material-icons">forum</span>
            Active Chat
            {conversation?.status === 'ready_to_task' && (
              <span className="sidebar__dot sidebar__dot--green" title="Ready to task" />
            )}
            {conversation?.status === 'tasking' && (
              <span className="sidebar__dot sidebar__dot--indigo" title="Tasking" />
            )}
          </button>

          <button
            className={`sidebar__item ${activeNav === 'history' ? 'sidebar__item--active' : ''}`}
            onClick={() => setActiveNav('history')}
            disabled={uiLockedByTasking}
            title={uiLockedByTasking ? navLockedHint : undefined}
          >
            <span className="material-icons">history</span>
            My Ideas
            {ideas.length > 0 && (
              <span className="sidebar__badge">{ideas.length}</span>
            )}
          </button>
        </nav>

        <div className="sidebar__footer">
          <Link
            to="/profile"
            className={`sidebar__user sidebar__user--link ${uiLockedByTasking ? 'sidebar__user--disabled' : ''}`}
            onClick={(event) => {
              if (uiLockedByTasking) {
                event.preventDefault()
              }
            }}
            aria-disabled={uiLockedByTasking}
            title={uiLockedByTasking ? navLockedHint : undefined}
          >
            <div className="sidebar__avatar">
              {avatar
                ? <img src={avatar} alt="avatar" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                : (user?.username?.[0]?.toUpperCase() ?? 'U')
              }
            </div>
            <span className="sidebar__username">{user?.display_name || user?.username}</span>
          </Link>
          <button
            className="sidebar__logout"
            onClick={handleLogout}
            title={uiLockedByTasking ? navLockedHint : 'Logout'}
            disabled={uiLockedByTasking}
          >
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

            {jiraStatus !== 'connected' && (
              <div className="jira-required-banner">
                <div className="jira-required-banner__icon">
                  <span className="material-icons">link_off</span>
                </div>
                <div className="jira-required-banner__body">
                  <p className="jira-required-banner__title">Jira connection required</p>
                  <p className="jira-required-banner__text">{JIRA_REQUIRED_MESSAGE}</p>
                </div>
                <button
                  className="jira-required-banner__action"
                  onClick={() => navigate('/profile')}
                >
                  Connect Jira
                </button>
              </div>
            )}

            {jiraStatus === 'connected' && !jiraProjectSelected && (
              <div className="jira-required-banner">
                <div className="jira-required-banner__icon">
                  <span className="material-icons">folder_off</span>
                </div>
                <div className="jira-required-banner__body">
                  <p className="jira-required-banner__title">Jira project required</p>
                  <p className="jira-required-banner__text">
                    {JIRA_PROJECT_REQUIRED_MESSAGE}
                  </p>
                </div>
                <button
                  className="jira-required-banner__action"
                  onClick={() => navigate('/profile')}
                >
                  Go to Profile
                </button>
              </div>
            )}

            <div className="project-type-picker">
              {PROJECT_TYPES.map((type) => (
                <button
                  key={type.id}
                  className={`type-chip type-chip--${type.color} ${selectedProjectType?.id === type.id ? 'type-chip--active' : ''}`}
                  onClick={() => setSelectedProjectType(prev => prev?.id === type.id ? null : type)}
                  disabled={jiraStatus !== 'connected' || !jiraProjectSelected}
                >
                  <span className="material-icons">{type.icon}</span>
                  {type.label}
                </button>
              ))}
            </div>

            <div className="idea-input">
              <textarea
                ref={textareaRef}
                className="idea-input__textarea"
                placeholder="e.g. Build a SaaS app where users can upload CSV files, visualize the data in charts, and share dashboards with their team via link…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    if (!submitting && text.trim() && jiraStatus === 'connected' && jiraProjectSelected && charCount <= MAX_CHARS) {
                      handleSubmit()
                    }
                  }
                }}
                maxLength={MAX_CHARS}
                spellCheck
                disabled={jiraStatus !== 'connected' || !jiraProjectSelected}
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
                  disabled={jiraStatus !== 'connected' || !jiraProjectSelected || !text.trim() || submitting || charCount > MAX_CHARS}
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
            projectTags={conversation.project_tags ?? null}
            isSending={isSending}
            sendError={sendError}
            showReadyBanner={showReadyBanner}
            taskingResult={taskingResult}
            isTaskingLoading={isTaskingLoading}
            repoUrl={conversation.github_repo_url ?? null}
            deploymentStatus={conversation.deployment_status ?? 'not_deployed'}
            deploymentLiveUrl={conversation.deployment_live_url ?? null}
            devInProcess={devInProcess}
            isDeployActionLoading={isDeployActionLoading}
            agentRunError={agentRunError}
            agentTickets={agentTickets}
            jiraStatus={jiraStatus}
            jiraProjectSelected={jiraProjectSelected}
            jiraRequiredMessage={jiraStatus !== 'connected' ? JIRA_REQUIRED_MESSAGE : JIRA_PROJECT_REQUIRED_MESSAGE}
            sessionExpired={sessionExpired}
            onSendMessage={handleSendMessage}
            onContinueChat={handleContinueChat}
            onStartTasking={handleStartTasking}
            onAddMoreRequirements={handleAddMoreRequirements}
            onReportBug={handleReportBug}
            onRetryTicket={handleRetryTicket}
            onRefreshTickets={handleRefreshTickets}
            onDeployIdea={() => handleDeployIdea('deploy')}
            onRedeployIdea={() => handleDeployIdea('redeploy')}
            onCancelAgents={handleCancelAgents}
            onGoToProfile={() => navigate('/profile')}
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
                  const pill = getIdeaPill(idea, ideaTicketsMap)
                  const displayMeta = getIdeaDisplayMeta(idea)
                  const isLoading = openingIdeaId === idea.id
                  return (
                    <div key={idea.id} className="idea-card">
                      <div className="idea-card__top">
                        <div className="idea-card__pills">
                          <span className={`idea-card__status idea-card__status--${pill.color}`}>
                            {pill.icon && <span className="material-icons">{pill.icon}</span>}
                            {pill.label}
                          </span>
                          {displayMeta.typePill && (
                            <span className={`idea-card__status idea-card__status--${displayMeta.typePill.color}`}>
                              <span className="material-icons">{displayMeta.typePill.icon}</span>
                              {displayMeta.typePill.label}
                            </span>
                          )}
                        </div>
                        <div className="idea-card__meta-right">
                          <span className="idea-card__id">#{idea.id}</span>
                          <span className="idea-card__date">{formatDate(idea.created_at)}</span>
                        </div>
                      </div>
                      <p className="idea-card__content">{displayMeta.headline}</p>
                      {ideaTicketsMap[idea.id] && (
                        <DevProgress
                          devInProcess={ideaTicketsMap[idea.id].stillPending > 0}
                          agentTickets={ideaTicketsMap[idea.id].tickets}
                          onRefreshTickets={() => {
                            getIdeaTickets(idea.id).then(res => {
                              const { tickets, still_pending } = res.data
                              setIdeaTicketsMap(prev => ({
                                ...prev,
                                [idea.id]: { tickets, stillPending: still_pending },
                              }))
                            }).catch(() => {})
                          }}
                          compact
                        />
                      )}
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
