import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
})

// ── Ideas ────────────────────────────────────────────────────────────────────
export const submitIdea = (content) => api.post('/ideas', { content })
export const getIdeas   = ()        => api.get('/ideas')

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
