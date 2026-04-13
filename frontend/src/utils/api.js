import axios from 'axios'

// In production (built static files), use VITE_API_BASE_URL if set.
// In local dev, fall back to '/api' which is proxied by Vite to localhost:8001.
const baseURL = import.meta.env.VITE_API_BASE_URL
  ? `${import.meta.env.VITE_API_BASE_URL}/api`
  : '/api'

const api = axios.create({ baseURL })

// Add Bearer token to all requests (except preflight OPTIONS)
api.interceptors.request.use((config) => {
  if (config.method !== 'options') {
    const token = localStorage.getItem('aif_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// Handle errors and 401 session expiry; success responses pass through silently
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error(`[${error.response?.status || 'NO_RESPONSE'}] ${error.config?.url}`, {
      message: error.message,
      data: error.response?.data,
    })

    if (error.response?.status === 401) {
      // Clear auth data from localStorage
      const user = JSON.parse(localStorage.getItem('aif_user') || '{}')
      localStorage.removeItem('aif_token')
      localStorage.removeItem('aif_user')
      if (user?.id) localStorage.removeItem(`aif_avatar_${user.id}`)

      // Notify the React tree so it can show a banner and redirect
      window.dispatchEvent(new CustomEvent('aif:session-expired'))
    }

    return Promise.reject(error)
  }
)

// ── Ideas ────────────────────────────────────────────────────────────────────
export const submitIdea          = (content) => api.post('/ideas', { content })
export const getIdeas            = ()        => api.get('/ideas')
export const getIdeaConversation = (ideaId)  => api.get(`/ideas/${ideaId}/conversation`)
export const getIdeaTickets      = (ideaId)  => api.get(`/ideas/${ideaId}/tickets`)
export const deleteIdea          = (ideaId)  => api.delete(`/ideas/${ideaId}`)

// ── Conversations ────────────────────────────────────────────────────────────
/** Create a conversation from idea text. Returns ConversationDetail. */
export const startConversation = (content) =>
  api.post('/conversations', { content })

/** Fetch a full conversation with all messages. */
export const getConversation = (id) =>
  api.get(`/conversations/${id}`)

/** Send a user message; returns updated ConversationDetail. */
export const sendMessage = (conversationId, content) =>
  api.post(`/conversations/${conversationId}/messages`, { content })

/** Transition the conversation to 'tasking'. Returns ConversationRead. */
export const startTasking = (conversationId) =>
  api.post(`/conversations/${conversationId}/start-tasking`)

/** Reopen a tasking/done conversation for additional requirements (Yes / Add more). */
export const reopenConversation = (conversationId) =>
  api.post(`/conversations/${conversationId}/reopen`)

/** Decline further requirements after tasking — transitions to 'done'. */
export const declineTasking = (conversationId) =>
  api.post(`/conversations/${conversationId}/decline-tasking`)

// ── Agent runner ─────────────────────────────────────────────────────────────

/** Kick off AI developer agents for all pending tickets. Returns immediately;
 *  agents run in the background. Poll getAgentTickets() for progress. */
export const runAgents = (conversationId) =>
  api.post(`/agents/${conversationId}/run`)

/** Poll ticket execution status for a conversation. */
export const getAgentTickets = (conversationId) =>
  api.get(`/agents/${conversationId}/tickets`)

/** Retry a single failed ticket and re-queue agent execution. */
export const retryTicket = (conversationId, ticketDbId) =>
  api.post(`/agents/${conversationId}/tickets/${ticketDbId}/retry`)

/** Signal all running agents for a conversation to stop. */
export const cancelAgents = (conversationId) =>
  api.post(`/agents/${conversationId}/cancel`)

export default api
