import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
})

export const submitIdea = (content) => api.post('/ideas', { content })
export const getIdeas = () => api.get('/ideas')

export default api
