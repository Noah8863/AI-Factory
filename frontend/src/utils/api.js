import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
})

// Add Bearer token to all requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('aif_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── Ideas ────────────────────────────────────────────────────────────────────
export const submitIdea          = (content) => api.post('/ideas', { content })
export const getIdeas            = ()        => api.get('/ideas')
export const getIdeaConversation = (ideaId)  => api.get(`/ideas/${ideaId}/conversation`)
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

export default api
