import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { io } from 'socket.io-client'
import api, { API_BASE_URL } from '../api'
import { useAuth } from './AuthContext'

// Sensible no-op defaults so anything calling useSocket() never hard-crashes
// if it's ever rendered outside a SocketProvider - the bell would just show
// no notifications instead of taking the whole page down with it.
const SocketContext = createContext({
  socket: null,
  notifications: [],
  unreadCount: 0,
  markAsRead: () => {},
  markAllAsRead: () => {},
  deleteNotification: () => {},
})

export function SocketProvider({ children }) {
  const { user } = useAuth()
  const [socket, setSocket] = useState(null)
  const [notifications, setNotifications] = useState([])

  // derived, not a separately-tracked counter - so it can never drift out of
  // sync with the actual list (e.g. after a delete or a bulk mark-all-read)
  const unreadCount = useMemo(
    () => notifications.filter(n => !n.is_read).length,
    [notifications]
  )

  useEffect(() => {
    if (!user) {
      setNotifications([])
      return
    }

    let cancelled = false
    let s = null

    async function init() {
      // Load persisted notifications FIRST, then connect the socket. Doing
      // it in this order (rather than in parallel) means a live event that
      // arrives right after connecting can never be wiped out by the GET
      // request's response resolving a moment later and overwriting state.
      try {
        const res = await api.get('/notifications')
        if (cancelled) return
        setNotifications(res.data)
      } catch {
        if (cancelled) return // the bell just starts empty; not worth a toast
      }
      if (cancelled) return

      // The same access token already used for REST calls authenticates the
      // socket too - the server decides which rooms to join from what's
      // actually inside that token, not from anything the client claims
      // after connecting.
      s = io(API_BASE_URL, { auth: { token: localStorage.getItem('access_token') } })
      setSocket(s)

      s.on('new_notification', data => {
        setNotifications(prev => [data, ...prev])
      })
    }

    init()

    return () => {
      cancelled = true
      if (s) s.disconnect()
      setSocket(null)
    }
  }, [user])

  async function markAsRead(id) {
    try {
      await api.put(`/notifications/${id}/read`)
      setNotifications(prev => prev.map(n => (n.id === id ? { ...n, is_read: true } : n)))
    } catch {
      // nothing to do locally if this fails - the item just stays unread
    }
  }

  async function markAllAsRead() {
    try {
      await api.put('/notifications/read-all')
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
    } catch {
      // leave everything as-is if the request failed
    }
  }

  async function deleteNotification(id) {
    try {
      await api.delete(`/notifications/${id}`)
      setNotifications(prev => prev.filter(n => n.id !== id))
    } catch {
      // leave it in the list if the delete failed
    }
  }

  return (
    <SocketContext.Provider value={{
      socket, notifications, unreadCount,
      markAsRead, markAllAsRead, deleteNotification,
    }}>
      {children}
    </SocketContext.Provider>
  )
}

export const useSocket = () => useContext(SocketContext)
