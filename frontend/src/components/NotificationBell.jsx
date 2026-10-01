import { useEffect, useRef, useState } from 'react'
import { useSocket } from '../context/SocketContext'

const TYPE_ICON = { order: '🛒', info: 'ℹ️', alert: '⚠️' }

// "2026-01-01T10:00:00" -> "2 mins ago" / "3 hours ago" / "5 days ago" / a date for anything older
function formatRelativeTime(isoString) {
  const then = new Date(isoString).getTime()
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000))

  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min${minutes === 1 ? '' : 's'} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`
  return new Date(isoString).toLocaleDateString()
}

export default function NotificationBell() {
  const { notifications, unreadCount, markAsRead, markAllAsRead, deleteNotification } = useSocket()
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  // close the dropdown on an outside click
  useEffect(() => {
    if (!open) return
    function handleClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const visible = notifications.slice(0, 10)

  return (
    <div className="notification-bell" ref={containerRef}>
      <button
        className="notification-bell-btn"
        onClick={() => setOpen(o => !o)}
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
      >
        🔔
        {unreadCount > 0 && <span className="cart-badge">{unreadCount}</span>}
      </button>

      {open && (
        <div className="notification-dropdown">
          <div className="notification-dropdown-header">
            <strong>Notifications</strong>
            {unreadCount > 0 && (
              <button className="btn btn-link" onClick={markAllAsRead}>Mark all as read</button>
            )}
          </div>

          {visible.length === 0 ? (
            <p className="notification-empty">No notifications</p>
          ) : (
            <div className="notification-list">
              {visible.map(n => (
                <div
                  key={n.id}
                  className={`notification-row ${n.is_read ? '' : 'notification-row-unread'}`}
                  onClick={() => !n.is_read && markAsRead(n.id)}
                >
                  <span className="notification-icon">{TYPE_ICON[n.type] || 'ℹ️'}</span>
                  <div className="notification-body">
                    <p className="notification-message">{n.message}</p>
                    <span className="notification-time">{formatRelativeTime(n.created_at)}</span>
                  </div>
                  {!n.is_read && <span className="notification-dot" aria-hidden="true" />}
                  <button
                    className="notification-dismiss"
                    onClick={e => { e.stopPropagation(); deleteNotification(n.id) }}
                    aria-label="Dismiss notification"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
