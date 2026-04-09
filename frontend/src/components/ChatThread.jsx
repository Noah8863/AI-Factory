import { useEffect, useRef, useState } from 'react'
import './ChatThread.scss'

function parseMarkdownBold(text) {
  const parts = text.split(/\*\*(.*?)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  )
}

/**
 * SQLite stores datetimes as UTC without a 'Z' suffix.
 * Appending 'Z' tells JS to treat it as UTC so toLocaleTimeString()
 * converts correctly to the user's local timezone.
 */
function formatTime(isoString) {
  if (!isoString) return ''
  const utc = isoString.endsWith('Z') ? isoString : isoString + 'Z'
  return new Date(utc).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  return (
    <div className={`chat-bubble chat-bubble--${isUser ? 'user' : 'agent'} ${message._optimistic ? 'chat-bubble--optimistic' : ''}`}>
      {!isUser && (
        <div className="chat-bubble__avatar">
          <span className="material-icons">smart_toy</span>
        </div>
      )}
      <div className="chat-bubble__body">
        {!isUser && <span className="chat-bubble__name">PM Agent</span>}
        <div className="chat-bubble__text">
          {message.content.split('\n\n').map((para, i) => (
            <p key={i}>{parseMarkdownBold(para)}</p>
          ))}
        </div>
        <span className="chat-bubble__time">
          {message._optimistic ? 'Sending…' : formatTime(message.created_at)}
        </span>
      </div>
      {isUser && (
        <div className="chat-bubble__avatar chat-bubble__avatar--user">
          <span className="material-icons">person</span>
        </div>
      )}
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="chat-bubble chat-bubble--agent">
      <div className="chat-bubble__avatar">
        <span className="material-icons">smart_toy</span>
      </div>
      <div className="chat-bubble__body">
        <span className="chat-bubble__name">PM Agent</span>
        <div className="chat-typing">
          <span /><span /><span />
        </div>
      </div>
    </div>
  )
}

export default function ChatThread({
  messages,
  status,
  isSending,
  sendError,
  showReadyBanner,
  onSendMessage,
  onContinueChat,
  onStartTasking,
  onBack,
}) {
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const isTasking = status === 'tasking'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isSending])

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed || isSending || isTasking) return
    setInput('')
    onSendMessage(trimmed)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-thread">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="chat-thread__header">
        <button className="chat-thread__back" onClick={onBack}>
          <span className="material-icons">arrow_back</span>
          <span>Back</span>
        </button>
        <div className="chat-thread__info">
          <div className="chat-thread__agent-icon">
            <span className="material-icons">smart_toy</span>
          </div>
          <div>
            <p className="chat-thread__agent-name">PM Agent</p>
            <p className="chat-thread__agent-status">
              {isTasking ? 'Creating tasks…' : isSending ? 'Typing…' : 'Active'}
            </p>
          </div>
        </div>
        <div className="chat-thread__header-badge">
          <span className="material-icons">forum</span>
          {messages.length} messages
        </div>
      </div>

      {/* ── Messages ───────────────────────────────────────────── */}
      <div className="chat-thread__messages">
        <div className="chat-thread__start-label">
          <span>Conversation started</span>
        </div>

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isSending && <TypingIndicator />}

        <div ref={bottomRef} />
      </div>

      {/* ── Send error ─────────────────────────────────────────── */}
      {sendError && (
        <div className="chat-thread__error">
          <span className="material-icons">error_outline</span>
          {sendError}
        </div>
      )}

      {/* ── Ready-to-task banner ───────────────────────────────── */}
      {showReadyBanner && !isTasking && (
        <div className="chat-ready-banner">
          <div className="chat-ready-banner__icon">
            <span className="material-icons">check_circle</span>
          </div>
          <div className="chat-ready-banner__body">
            <p className="chat-ready-banner__title">Ready to start building</p>
            <p className="chat-ready-banner__sub">
              The PM has enough context to generate tasks. How would you like to proceed?
            </p>
          </div>
          <div className="chat-ready-banner__actions">
            <button
              className="chat-ready-banner__btn chat-ready-banner__btn--ghost"
              onClick={onContinueChat}
            >
              <span className="material-icons">chat</span>
              Continue Chat
            </button>
            <button
              className="chat-ready-banner__btn chat-ready-banner__btn--primary"
              onClick={onStartTasking}
            >
              Start Building
              <span className="material-icons">rocket_launch</span>
            </button>
          </div>
        </div>
      )}

      {/* ── Tasking in progress ────────────────────────────────── */}
      {isTasking && (
        <div className="chat-tasking-banner">
          <div className="chat-tasking-banner__spinner" />
          <div>
            <p className="chat-tasking-banner__title">Generating tasks…</p>
            <p className="chat-tasking-banner__sub">
              The PM agent is breaking your idea into development tasks.
            </p>
          </div>
        </div>
      )}

      {/* ── Input ──────────────────────────────────────────────── */}
      {!isTasking && (
        <div className="chat-thread__input-bar">
          <textarea
            ref={inputRef}
            className="chat-thread__input"
            placeholder="Reply to the PM agent…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={isSending}
          />
          <button
            className="chat-thread__send"
            onClick={handleSend}
            disabled={!input.trim() || isSending}
            aria-label="Send message"
          >
            <span className="material-icons">send</span>
          </button>
        </div>
      )}
    </div>
  )
}
