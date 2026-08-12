import { useState, useEffect, useMemo } from 'react'
import { request } from '@/lib/api'
import { Calendar as CalendarIcon, Clock, DollarSign, TrendingUp, AlertCircle, Loader2 } from 'lucide-react'
import { useTheme } from '../context/ThemeContext'

interface EarningsEvent {
  ticker: string
  report_date: string
  fiscal_year: number | null
  fiscal_quarter: number | null
  eps_estimate: number | null
  revenue_estimate: number | null
  eps_actual: number | null
  revenue_actual: number | null
  time_of_day: string
  source: string
  days_until: number | null
}

const TIME_BADGES: Record<string, { label: string; color: string }> = {
  bmo: { label: 'BMO', color: '#10B981' },
  amc: { label: 'AMC', color: '#F59E0B' },
  dmh: { label: 'DMH', color: '#EF4444' },
  tns: { label: 'TNS', color: '#6B7280' },
}

export default function EarningsCalendar() {
  const { isDarkMode } = useTheme()
  const [events, setEvents] = useState<EarningsEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(14)

  const colors = useMemo(() => ({
    bg: isDarkMode ? '#050505' : '#fafaf8',
    surface: isDarkMode ? '#0a0a0a' : '#ffffff',
    text: isDarkMode ? '#ffffff' : '#1a1a18',
    muted: isDarkMode ? 'rgba(255,255,255,0.55)' : '#6b6b65',
    subtle: isDarkMode ? 'rgba(255,255,255,0.32)' : '#8e8e88',
    border: isDarkMode ? 'rgba(255,255,255,0.07)' : '#e5e5e0',
    accent: '#10B981',
    accentHover: '#059669',
    cardBg: isDarkMode ? 'rgba(255,255,255,0.02)' : '#ffffff',
    cardBorder: isDarkMode ? 'rgba(255,255,255,0.06)' : '#e5e5e0',
    badgeBg: isDarkMode ? 'rgba(16,185,129,0.12)' : 'rgba(16,185,129,0.1)',
    badgeText: isDarkMode ? '#6EE7B7' : '#059669',
  }), [isDarkMode])

  useEffect(() => {
    fetchCalendar()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days])

  async function fetchCalendar() {
    setLoading(true)
    setError(null)
    try {
      const today = new Date().toISOString().split('T')[0]
      const future = new Date()
      future.setDate(future.getDate() + days)
      const to = future.toISOString().split('T')[0]

      const data = await request<EarningsEvent[]>(`/earnings/calendar?from=${today}&to=${to}`)
      setEvents(data || [])
    } catch (e: any) {
      setError(e.message || 'Failed to load earnings calendar')
    } finally {
      setLoading(false)
    }
  }

  const grouped = useMemo(() => {
    const map: Record<string, EarningsEvent[]> = {}
    for (const evt of events) {
      const date = evt.report_date
      if (!map[date]) map[date] = []
      map[date].push(evt)
    }
    return Object.entries(map).sort(([a], [b]) => a.localeCompare(b))
  }, [events])

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr + 'T00:00:00')
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  }

  const isToday = (dateStr: string) => {
    return dateStr === new Date().toISOString().split('T')[0]
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: colors.bg, color: colors.text, padding: '32px 40px' }}>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32 }}>
          <div>
            <h1 style={{ fontSize: 32, fontWeight: 700, margin: 0, letterSpacing: '-0.02em' }}>Earnings Calendar</h1>
            <p style={{ color: colors.muted, margin: '8px 0 0 0', fontSize: 16 }}>
              Upcoming earnings announcements with EPS estimates
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <label style={{ color: colors.muted, fontSize: 14 }}>
              Next
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                style={{
                  marginLeft: 8,
                  padding: '8px 12px',
                  borderRadius: 8,
                  border: `1px solid ${colors.border}`,
                  backgroundColor: colors.surface,
                  color: colors.text,
                  fontSize: 14,
                  cursor: 'pointer',
                }}
              >
                <option value={7}>7 days</option>
                <option value={14}>14 days</option>
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
              </select>
            </label>

            <button
              onClick={fetchCalendar}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '10px 18px',
                borderRadius: 10,
                border: 'none',
                backgroundColor: colors.accent,
                color: '#fff',
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'background-color 0.2s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = colors.accentHover)}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = colors.accent)}
            >
              <CalendarIcon size={16} />
              Refresh
            </button>
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80, gap: 12 }}>
            <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />
            <span style={{ color: colors.muted }}>Loading earnings calendar...</span>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: 20, borderRadius: 12,
            backgroundColor: isDarkMode ? 'rgba(239,68,68,0.1)' : 'rgba(239,68,68,0.06)',
            border: `1px solid ${isDarkMode ? 'rgba(239,68,68,0.2)' : 'rgba(239,68,68,0.15)'}`,
            color: '#EF4444',
          }}>
            <AlertCircle size={20} />
            <span>{error}</span>
          </div>
        )}

        {/* Calendar Grid */}
        {!loading && !error && grouped.length === 0 && (
          <div style={{ textAlign: 'center', padding: 80, color: colors.muted }}>
            <CalendarIcon size={48} style={{ marginBottom: 16, opacity: 0.3 }} />
            <p style={{ fontSize: 18, fontWeight: 600 }}>No upcoming earnings</p>
            <p>Try extending the date range or trigger a sync from the backend.</p>
          </div>
        )}

        {!loading && !error && (
          <div style={{ display: 'grid', gap: 16 }}>
            {grouped.map(([date, dayEvents]) => (
              <div
                key={date}
                style={{
                  backgroundColor: colors.cardBg,
                  border: `1px solid ${colors.cardBorder}`,
                  borderRadius: 16,
                  overflow: 'hidden',
                }}
              >
                {/* Date header */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '16px 20px',
                  backgroundColor: isToday(date) ? colors.badgeBg : 'transparent',
                  borderBottom: `1px solid ${colors.cardBorder}`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <CalendarIcon size={18} color={colors.accent} />
                    <span style={{ fontSize: 16, fontWeight: 600 }}>
                      {formatDate(date)}
                    </span>
                    {isToday(date) && (
                      <span style={{
                        fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em',
                        padding: '4px 10px', borderRadius: 20,
                        backgroundColor: colors.badgeBg,
                        color: colors.badgeText,
                      }}>
                        Today
                      </span>
                    )}
                  </div>
                  <span style={{ color: colors.muted, fontSize: 13 }}>
                    {dayEvents.length} reporting
                  </span>
                </div>

                {/* Events list */}
                <div style={{ padding: '8px 12px' }}>
                  {dayEvents.map((evt) => {
                    const badge = TIME_BADGES[evt.time_of_day] || TIME_BADGES.tns
                    return (
                      <div
                        key={`${evt.ticker}-${evt.report_date}`}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '12px 16px',
                          borderRadius: 10,
                          transition: 'background-color 0.15s',
                          cursor: 'default',
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = isDarkMode ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flex: 1 }}>
                          <div style={{ minWidth: 60 }}>
                            <span style={{ fontSize: 15, fontWeight: 700, fontFamily: 'monospace' }}>
                              {evt.ticker}
                            </span>
                          </div>

                          <div style={{
                            display: 'flex', alignItems: 'center', gap: 6,
                            padding: '4px 10px', borderRadius: 20,
                            backgroundColor: isDarkMode ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
                          }}>
                            <Clock size={12} color={badge.color} />
                            <span style={{ fontSize: 12, fontWeight: 600, color: badge.color }}>
                              {badge.label}
                            </span>
                          </div>

                          {evt.eps_estimate != null && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <DollarSign size={14} color={colors.muted} />
                              <span style={{ fontSize: 14, color: colors.text }}>
                                EPS est <strong>{evt.eps_estimate.toFixed(2)}</strong>
                              </span>
                            </div>
                          )}

                          {evt.revenue_estimate != null && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <TrendingUp size={14} color={colors.muted} />
                              <span style={{ fontSize: 14, color: colors.text }}>
                                Rev est <strong>${(evt.revenue_estimate / 1e9).toFixed(1)}B</strong>
                              </span>
                            </div>
                          )}

                          {evt.eps_actual != null && (
                            <div style={{
                              display: 'flex', alignItems: 'center', gap: 6,
                              padding: '3px 10px', borderRadius: 20,
                              backgroundColor: evt.eps_actual >= (evt.eps_estimate || 0)
                                ? (isDarkMode ? 'rgba(16,185,129,0.12)' : 'rgba(16,185,129,0.1)')
                                : (isDarkMode ? 'rgba(239,68,68,0.12)' : 'rgba(239,68,68,0.1)'),
                            }}>
                              <span style={{
                                fontSize: 12, fontWeight: 600,
                                color: evt.eps_actual >= (evt.eps_estimate || 0) ? '#10B981' : '#EF4444',
                              }}>
                                {evt.eps_actual >= (evt.eps_estimate || 0) ? 'Beat' : 'Miss'} {evt.eps_actual.toFixed(2)}
                              </span>
                            </div>
                          )}
                        </div>

                        <div style={{ minWidth: 80, textAlign: 'right' }}>
                          {evt.days_until != null && evt.days_until === 0 ? (
                            <span style={{ fontSize: 12, fontWeight: 700, color: '#EF4444' }}>TODAY</span>
                          ) : evt.days_until != null && evt.days_until === 1 ? (
                            <span style={{ fontSize: 12, fontWeight: 700, color: '#F59E0B' }}>Tomorrow</span>
                          ) : evt.days_until != null ? (
                            <span style={{ fontSize: 12, color: colors.muted }}>{evt.days_until} days</span>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
