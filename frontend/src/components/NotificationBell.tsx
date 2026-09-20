import React, { useState, useEffect, useRef } from 'react'
import { Bell, CheckCheck } from 'lucide-react'
import { apiClient } from '@/lib/apiClient'

interface NotificationItem {
  id: string
  title: string
  message: string
  notification_type: string
  is_read: boolean
  created_at: string
}

export const NotificationBell: React.FC = () => {
  const [unreadCount, setUnreadCount] = useState<number>(0)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const fetchCount = async () => {
    try {
      const res = await apiClient.get('/notifications/count')
      setUnreadCount(res.data.unread_count || 0)
    } catch {
      // Best-effort
    }
  }

  const fetchNotifications = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get('/notifications?limit=20')
      setNotifications(res.data || [])
    } catch {
      // Best-effort
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCount()
    const interval = setInterval(fetchCount, 30_000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (isOpen) {
      fetchNotifications()
    }
  }, [isOpen])

  // Close when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const markAsRead = async (id: string) => {
    try {
      await apiClient.patch(`/notifications/${id}/read`)
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
      setUnreadCount((c) => Math.max(0, c - 1))
    } catch {
      // ignore
    }
  }

  const markAllAsRead = async () => {
    try {
      await apiClient.patch('/notifications/read-all')
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
      setUnreadCount(0)
    } catch {
      // ignore
    }
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 rounded-lg text-surface-600 hover:text-surface-900 hover:bg-surface-100 transition-colors focus:outline-none"
        aria-label="Notifications"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 flex items-center justify-center min-w-4 h-4 px-1 text-[10px] font-bold text-white bg-primary-600 rounded-full animate-pulse">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 sm:w-96 bg-white rounded-xl shadow-modal border border-surface-200 z-50 overflow-hidden animate-fade-in">
          <div className="flex items-center justify-between px-4 py-3 border-b border-surface-200 bg-surface-50">
            <span className="font-semibold text-sm text-surface-800">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={markAllAsRead}
                className="text-xs text-primary-600 hover:text-primary-700 font-medium flex items-center gap-1"
              >
                <CheckCheck className="w-3.5 h-3.5" /> Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-surface-100">
            {loading ? (
              <div className="p-4 text-center text-xs text-surface-500">Loading notifications...</div>
            ) : notifications.length === 0 ? (
              <div className="p-6 text-center text-xs text-surface-400">No notifications yet.</div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  onClick={() => !n.is_read && markAsRead(n.id)}
                  className={`p-3 text-left transition-colors cursor-pointer ${
                    !n.is_read ? 'bg-primary-50/50 hover:bg-primary-50' : 'hover:bg-surface-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className={`text-xs font-medium ${!n.is_read ? 'text-surface-900 font-semibold' : 'text-surface-700'}`}>
                      {n.title}
                    </p>
                    {!n.is_read && (
                      <span className="w-2 h-2 rounded-full bg-primary-600 shrink-0 mt-1" />
                    )}
                  </div>
                  <p className="text-[11px] text-surface-500 mt-1 line-clamp-2">{n.message}</p>
                  <span className="text-[10px] text-surface-400 mt-1 block">
                    {new Date(n.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
