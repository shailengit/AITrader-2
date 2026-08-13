import { useState, useEffect, useMemo } from 'react'
import { request } from '@/lib/api'
import { Calendar as CalendarIcon, Clock, DollarSign, TrendingUp, AlertCircle, Loader2 } from 'lucide-react'

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
  bmo: { label: 'BMO', color: 'var(--good)' },
  amc: { label: 'AMC', color: '#F59E0B' },
  dmh: { label: 'DMH', color: 'var(--bad)' },
  tns: { label: 'TNS', color: 'var(--muted)' },
}

export default function EarningsCalendar() {
  const [events, setEvents] = useState<EarningsEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(14)

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
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--canvas)', color: 'var(--foreground)', padding: '32px 40px' }}>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32 }}>
          <div>
            <h1 style={{ fontSize: 32, fontWeight: 700, margin: 0, letterSpacing: '-0.02em' }}>Earnings Calendar</h1>
            <p style={{ color: 'var(--muted)', margin: '8px 0 0 0', fontSize: 16 }}>
              Upcoming earnings announcements with EPS estimates
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <label style={{ color: 'var(--muted)', fontSize: 14 }}>
              Next
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                style={{
                  marginLeft: 8,
                  padding: '8px 12px',
                  borderRadius: 8,
                  border: `1px solid var(--border)`,
                  backgroundColor: 'var(--surface)',
                  color: 'var(--foreground)',
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
                backgroundColor: 'var(--accent)',
                color: 'var(--accent-ink)',
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'background-color 0.2s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--accent-dark)')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--accent)')}
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
            <span style={{ color: 'var(--muted)' }}>Loading earnings calendar...</span>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: 20, borderRadius: 12,
            backgroundColor: 'var(--danger-hover)',
            border: '1px solid var(--bad)',
            color: 'var(--bad)',
          }}>
            <AlertCircle size={20} />
            <span>{error}</span>
          </div>
        )}

        {/* Calendar Grid */}
        {!loading && !error && grouped.length === 0 && (
          <div style={{ textAlign: 'center', padding: 80, color: 'var(--muted)' }}>
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
                  backgroundColor: 'var(--surface)',
                  border: `1px solid var(--border)`,
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
                  backgroundColor: isToday(date) ? 'var(--accent-glow)' : 'transparent',
                  borderBottom: `1px solid var(--border)`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <CalendarIcon size={18} color="var(--accent)" />
                    <span style={{ fontSize: 16, fontWeight: 600 }}>
                      {formatDate(date)}
                    </span>
                    {isToday(date) && (
                      <span style={{
                        fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em',
                        padding: '4px 10px', borderRadius: 20,
                        backgroundColor: 'var(--accent-glow)',
                        color: 'var(--accent-light)',
                      }}>
                        Today
                      </span>
                    )}
                  </div>
                  <span style={{ color: 'var(--muted)', fontSize: 13 }}>
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
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--surface-raised)')}
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
                            backgroundColor: 'var(--surface-raised)',
                          }}>
                            <Clock size={12} color={badge.color} />
                            <span style={{ fontSize: 12, fontWeight: 600, color: badge.color }}>
                              {badge.label}
                            </span>
                          </div>

                          {evt.eps_estimate != null && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <DollarSign size={14} color="var(--muted)" />
                              <span style={{ fontSize: 14, color: 'var(--foreground)' }}>
                                EPS est <strong>{evt.eps_estimate.toFixed(2)}</strong>
                              </span>
                            </div>
                          )}

                          {evt.revenue_estimate != null && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <TrendingUp size={14} color="var(--muted)" />
                              <span style={{ fontSize: 14, color: 'var(--foreground)' }}>
                                Rev est <strong>${(evt.revenue_estimate / 1e9).toFixed(1)}B</strong>
                              </span>
                            </div>
                          )}

                          {evt.eps_actual != null && (
                            <div style={{
                              display: 'flex', alignItems: 'center', gap: 6,
                              padding: '3px 10px', borderRadius: 20,
                              backgroundColor: evt.eps_actual >= (evt.eps_estimate || 0)
                                ? 'var(--accent-glow)'
                                : 'var(--danger-hover)',
                            }}>
                              <span style={{
                                fontSize: 12, fontWeight: 600,
                                color: evt.eps_actual >= (evt.eps_estimate || 0) ? 'var(--good)' : 'var(--bad)',
                              }}>
                                {evt.eps_actual >= (evt.eps_estimate || 0) ? 'Beat' : 'Miss'} {evt.eps_actual.toFixed(2)}
                              </span>
                            </div>
                          )}
                        </div>

                        <div style={{ minWidth: 80, textAlign: 'right' }}>
                          {evt.days_until != null && evt.days_until === 0 ? (
                            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--bad)' }}>TODAY</span>
                          ) : evt.days_until != null && evt.days_until === 1 ? (
                            <span style={{ fontSize: 12, fontWeight: 700, color: '#F59E0B' }}>Tomorrow</span>
                          ) : evt.days_until != null ? (
                            <span style={{ fontSize: 12, color: 'var(--muted)' }}>{evt.days_until} days</span>
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
