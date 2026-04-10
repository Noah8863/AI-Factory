import { useEffect, useState } from 'react'
import api from '../utils/api'
import './ConnectionStatus.scss'

export default function ConnectionStatus() {
  const [isConnected, setIsConnected] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const response = await api.get('/auth/jira/status')
        setIsConnected(response.data.connected)
      } catch (error) {
        console.error('Failed to check Jira connection status:', error)
        setIsConnected(false)
      } finally {
        setLoading(false)
      }
    }

    checkStatus()
  }, [])

  const handleConnect = () => {
    const token = localStorage.getItem('aif_token')
    const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    if (token) {
      window.location.href = `${apiBase}/api/auth/jira/login?token=${token}`
    }
  }

  if (loading) {
    return (
      <div className="connection-status connection-status--loading">
        <span className="material-icons">sync</span>
        <span className="connection-status__text">Checking…</span>
      </div>
    )
  }

  if (isConnected) {
    return (
      <div className="connection-status connection-status--connected">
        <span className="material-icons">check_circle</span>
        <span className="connection-status__text">Jira Connected</span>
      </div>
    )
  }

  return (
    <div className="connection-status connection-status--disconnected">
      <span className="material-icons">warning</span>
      <button
        className="connection-status__text connection-status__button"
        onClick={handleConnect}
        title="Click to connect your Jira account"
      >
        Jira Disconnected
      </button>
    </div>
  )
}
