import { useState, useEffect } from 'react'
import { request } from '@/lib/api'
import { useNavigate } from 'react-router-dom'
import {
  TrendingUp,
  Activity,
  ArrowUpRight,
  BarChart2,
  CheckCircle2,
  X,
  Maximize2
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts'
import { motion, AnimatePresence } from 'framer-motion'
import { Card } from '../components/ui/Card'
import { StatusBadge } from '../components/ui/Badge'
import { ProgressMetric } from '../components/ui/Metric'
import { useTheme } from '../context/ThemeContext'
import { recordAppReferrer } from '../components/layout/Layout'
import { CandleStickChart } from '../components/quantgen/CandleStickChart'
import { SaveHypothesisPopover } from '../components/shared/SaveHypothesisPopover'
import { fetchRegimes, SectorRegime } from '../lib/regime'

interface Sector {
  ticker: string
  name: string
  perf_3m: number
  perf_6m: number
  spread: number
  ref_date: string | null
  forward_return: number | null
  is_real_data: boolean
}

interface Stock {
  ticker: string
  name: string
  price: number
  perf_3m: number
  sector_perf_3m: number
  volume_today: number
  volume_avg_20d: number
  high_10d: number
  bb_expanding: boolean
  bb_upper: number
  bb_middle: number
  bb_lower: number
  sma50: number | null
  sma200: number | null
  ref_date: string | null
  forward_return: number | null
  is_real_data: boolean
  sector?: string
  perf_1m?: number
  perf_6m?: number
}

const SECTOR_ROTATION_STATE_KEY = 'sectorRotation:lastView'

function getSavedSectorRotationState() {
  try {
    const raw = sessionStorage.getItem(SECTOR_ROTATION_STATE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return null
}

export default function SectorRotation() {
  const navigate = useNavigate()
  const savedState = getSavedSectorRotationState()
  const oneMonthAgo = new Date()
  oneMonthAgo.setMonth(oneMonthAgo.getMonth() - 1)

  const [sectors, setSectors] = useState<Sector[]>([])
  const [selectedSector, setSelectedSector] = useState<Sector | null>(savedState?.selectedSector || null)
  const [stocks, setStocks] = useState<Stock[]>([])
  const [topLeaders, setTopLeaders] = useState<Stock[]>([])
  const [loadingTopLeaders, setLoadingTopLeaders] = useState(false)
  const [viewMode, setViewMode] = useState<'sector' | 'top20'>(savedState?.viewMode || 'sector')
  const [analyzedStock, setAnalyzedStock] = useState<Stock | null>(null)
  const [chartTicker, setChartTicker] = useState<string | null>(null)
  const [chartData, setChartData] = useState<any[]>([])
  const [isChartLoading, setIsChartLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [isDbConnected, setIsDbConnected] = useState(false)
  const [regimes, setRegimes] = useState<Record<string, SectorRegime>>({})
  const [lastUpdated, setLastUpdated] = useState(new Date().toLocaleTimeString())
  const [cutoffDate, setCutoffDate] = useState(savedState?.cutoffDate || oneMonthAgo.toISOString().split('T')[0])
  const [holdingDays, setHoldingDays] = useState(savedState?.holdingDays ?? 30)
  const { isDarkMode } = useTheme()

  // Theme-aware colors
  const colors = {
    text: isDarkMode ? '#ffffff' : '#1d1d1f',
    muted: isDarkMode ? '#A1A1AA' : '#6e6e73',
    subtle: isDarkMode ? '#52525B' : '#86868b',
    surface: isDarkMode ? 'rgba(255, 255, 255, 0.02)' : '#ffffff',
    border: isDarkMode ? 'rgba(255, 255, 255, 0.05)' : '#e5e5ea',
    grid: isDarkMode ? 'rgba(255, 255, 255, 0.05)' : '#e5e5e7',
    tooltip: {
      bg: isDarkMode ? 'rgba(10, 10, 10, 0.85)' : '#ffffff',
      border: isDarkMode ? 'rgba(255, 255, 255, 0.1)' : '#d2d2d7',
    },
    negative: isDarkMode ? '#3f3f46' : '#9ca3af',
    accent: isDarkMode ? '#10B981' : '#0071e3',
    glow: isDarkMode ? 'rgba(16, 185, 129, 0.15)' : 'rgba(0, 113, 227, 0.05)'
  }

  useEffect(() => {
    checkDbStatus()
    fetchSectors()
    fetchRegimes().then(list => {
      const map: Record<string, SectorRegime> = {}
      for (const r of list) map[r.etf] = r
      setRegimes(map)
    }).catch(() => {})
  }, [])

  const checkDbStatus = async () => {
    try {
      const data = await request<{ connected: boolean }>('/db-status')
      setIsDbConnected(data.connected)
    } catch {
      setIsDbConnected(false)
    }
  }

  const handleRefresh = () => {
    checkDbStatus()
    fetchSectors()
    setLastUpdated(new Date().toLocaleTimeString())
  }

  useEffect(() => {
    if (selectedSector) {
      fetchStocks(selectedSector.ticker)
    }
  }, [selectedSector, cutoffDate, holdingDays])

  useEffect(() => {
    if (viewMode === 'top20') {
      fetchTopMomentumLeaders()
    }
  }, [viewMode, cutoffDate, holdingDays])

  // Persist view state so returning from QuantGen restores the exact Sector Rotation view
  useEffect(() => {
    try {
      sessionStorage.setItem(
        SECTOR_ROTATION_STATE_KEY,
        JSON.stringify({ selectedSector, viewMode, cutoffDate, holdingDays })
      )
    } catch {}
  }, [selectedSector, viewMode, cutoffDate, holdingDays])

  const buildQueryParams = () => {
    const params = new URLSearchParams()
    if (cutoffDate) {
      params.set('cutoff_date', cutoffDate)
      params.set('holding_days', String(holdingDays))
    }
    return params.toString()
  }

  const fetchSectors = async () => {
    try {
      setLoading(true)
      const qs = buildQueryParams()
      const url = qs ? `/sectors?${qs}` : '/sectors'
      const data = await request<Sector[]>(url)
      setSectors(data)
      if (data.length > 0) {
        const restored = savedState?.selectedSector
        const stillValid = restored && data.some((s: Sector) => s.ticker === restored.ticker)
        if (!stillValid) {
          setSelectedSector(data[0])
        }
      }
    } catch (err) {
      console.error('Failed to fetch sectors:', err)
    } finally {
      setLoading(false)
    }
  }

  const fetchStocks = async (sectorTicker: string) => {
    try {
      const qs = buildQueryParams()
      const url = qs ? `/stocks/${sectorTicker}?${qs}` : `/stocks/${sectorTicker}`
      const data = await request<Stock[]>(url)
      setStocks(data)
    } catch (err) {
      console.error(err)
    }
  }

  const fetchTopMomentumLeaders = async () => {
    try {
      setLoadingTopLeaders(true)
      const qs = buildQueryParams()
      const url = qs ? `/top-momentum-leaders?${qs}` : '/top-momentum-leaders'
      const data = await request<Stock[]>(url)
      setTopLeaders(data)
    } catch (err) {
      console.error('Failed to fetch top momentum leaders:', err)
    } finally {
      setLoadingTopLeaders(false)
    }
  }

  const exportToQuantGen = (stockList: Stock[]) => {
    const tickers = stockList.map(s => s.ticker).join(',')
    const fromDate = cutoffDate || new Date().toISOString().split('T')[0]
    recordAppReferrer('/sectors', 'Sector Rotation')
    navigate(`/quantgen/build?tickers=${encodeURIComponent(tickers)}&from_date=${fromDate}`)
  }

  const fetchChartData = async (ticker: string) => {
    try {
      setIsChartLoading(true)
      setChartTicker(ticker)
      const data = await request<any[]>(`/ohlcv/${ticker}`)
      
      const processedData = data.map((d: any, i: number) => {
        const result = { ...d }
        
        // Calculate Price SMAs
        if (i >= 19) {
          const slice20 = data.slice(i - 19, i + 1)
          const sum20 = slice20.reduce((a: any, b: any) => a + b.close, 0)
          result.sma20 = sum20 / 20
          
          const volSum20 = slice20.reduce((a: any, b: any) => a + b.volume, 0)
          result.vol_sma20 = volSum20 / 20

          // BB calculation
          const variance = slice20.reduce((a: any, b: any) => a + Math.pow(b.close - result.sma20, 2), 0) / 20
          const stdDev = Math.sqrt(variance)
          result.bb_middle = result.sma20
          result.bb_upper = result.sma20 + (2 * stdDev)
          result.bb_lower = result.sma20 - (2 * stdDev)
        }
        
        if (i >= 49) {
          const slice50 = data.slice(i - 49, i + 1)
          const sum50 = slice50.reduce((a: any, b: any) => a + b.close, 0)
          result.sma50 = sum50 / 50
          
          const volSum50 = slice50.reduce((a: any, b: any) => a + b.volume, 0)
          result.vol_sma50 = volSum50 / 50
        }
        
        return result
      })
      
      setChartData(processedData)
    } catch (err) {
      console.error('Error fetching chart data:', err)
    } finally {
      setIsChartLoading(false)
    }
  }

  const formatPercent = (val: number) => (val * 100).toFixed(2) + '%'

  const getStrengthScore = (stock: Stock): number => {
    let score = 0
    if (stock.bb_expanding) score += 25
    const isPriceBreakout = stock.price > stock.high_10d
    if (isPriceBreakout) score += 25
    if (stock.price > (stock.sma50 || 0)) score += 25
    if (stock.price > (stock.sma200 || 0)) score += 25
    return score
  }

  if (loading && sectors.length === 0) {
    return (
      <div className="min-h-screen bg-canvas flex items-center justify-center">
        <div className="flex flex-col items-center gap-6">
          <Activity className="w-16 h-16 text-emerald-500 animate-pulse" />
          <p className="font-mono text-lg tracking-widest uppercase" style={{ color: colors.muted }}>Scanning Market Sectors...</p>
        </div>
      </div>
    )
  }

  return (
    <div style={{ 
      width: '100%', 
      padding: '40px 4vw', // Responsive padding using viewport width
      boxSizing: 'border-box',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center'
    }}>
      <div style={{ width: '100%', maxWidth: '2400px' }}>
        {/* Header */}
        <div className="flex items-center justify-between mb-10">
          <div className="flex items-center gap-4">
            <div 
              className="rounded-2xl p-3" 
              style={{ 
                background: isDarkMode ? 'linear-gradient(135deg, rgba(16,185,129,0.2) 0%, rgba(16,185,129,0.05) 100%)' : colors.accent,
                border: `1px solid ${isDarkMode ? 'rgba(16,185,129,0.3)' : 'transparent'}`,
                boxShadow: isDarkMode ? '0 0 20px rgba(16,185,129,0.2)' : 'none'
              }}
            >
              <TrendingUp className="w-7 h-7" style={{ color: isDarkMode ? '#34D399' : '#fff' }} />
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>Sector Rotation Scanner</h1>
              <p className="text-base" style={{ color: colors.muted }}>Identify momentum and rotation patterns</p>
            </div>
          </div>
          <div className="flex items-center gap-4 text-sm font-mono" style={{ color: colors.muted }}>
            {/* Cutoff Date Picker */}
            <div className="flex items-center gap-2">
              <label className="text-xs uppercase tracking-wider" style={{ color: colors.subtle }}>As of</label>
              <input
                type="date"
                value={cutoffDate}
                onChange={(e) => {
                  setCutoffDate(e.target.value)
                  setTimeout(() => handleRefresh(), 0)
                }}
                max={new Date().toISOString().split('T')[0]}
                className="px-3 py-2 rounded-lg text-sm border outline-none focus:ring-2 focus:ring-emerald-500/50"
                style={{
                  backgroundColor: isDarkMode ? 'rgba(255,255,255,0.05)' : '#ffffff',
                  borderColor: colors.border,
                  color: colors.text,
                }}
              />
            </div>

            {/* Holding Period */}
            {cutoffDate && (
              <div className="flex items-center gap-2">
                <label className="text-xs uppercase tracking-wider" style={{ color: colors.subtle }}>Fwd</label>
                <select
                  value={holdingDays}
                  onChange={(e) => {
                    setHoldingDays(Number(e.target.value))
                    setTimeout(() => handleRefresh(), 0)
                  }}
                  className="px-3 py-2 rounded-lg text-sm border outline-none focus:ring-2 focus:ring-emerald-500/50"
                  style={{
                    backgroundColor: isDarkMode ? 'rgba(255,255,255,0.05)' : '#ffffff',
                    borderColor: colors.border,
                    color: colors.text,
                  }}
                >
                  <option value={7}>7d</option>
                  <option value={30}>30d</option>
                  <option value={60}>60d</option>
                  <option value={90}>90d</option>
                </select>
              </div>
            )}

            <StatusBadge
              status={isDbConnected ? 'connected' : 'disconnected'}
              label={isDbConnected ? 'S&P 1500 Connected' : 'Demo Mode'}
            />
            <button
              onClick={handleRefresh}
              className="p-2.5 rounded-xl transition-all"
              style={{ backgroundColor: 'transparent' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = colors.surface
                e.currentTarget.style.transform = 'scale(1.05)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
                e.currentTarget.style.transform = 'scale(1)'
              }}
            >
              <Activity className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} style={{ color: colors.accent }} />
            </button>
            <span style={{ color: colors.muted }}>Last: {lastUpdated}</span>
          </div>
        </div>

        {/* Sector Performance */}
        <div className="flex flex-col xl:flex-row gap-8 mb-10">
          {/* Bar Chart - ~35% width */}
          <Card variant="base" className="flex-grow xl:w-[35%] shrink-0 p-8 relative overflow-hidden" style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            backdropFilter: 'blur(10px)',
            boxShadow: isDarkMode ? '0 10px 40px rgba(0,0,0,0.3)' : '0 10px 40px rgba(0,0,0,0.05)'
        }}>
          {/* Subtle background glow */}
          {isDarkMode && <div style={{ position: 'absolute', top: '-50%', left: '-20%', width: '150%', height: '150%', background: 'radial-gradient(circle, rgba(16,185,129,0.03) 0%, transparent 60%)', pointerEvents: 'none' }} />}
          
          <h2 className="text-sm font-semibold uppercase tracking-widest mb-6 relative z-10" style={{ color: colors.muted }}>
            Sector Acceleration Scan
          </h2>
          <div className="h-[400px] relative z-10">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sectors}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} vertical={false} />
                <XAxis dataKey="ticker" stroke={colors.muted} fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke={colors.muted} fontSize={12} tickLine={false} axisLine={false}
                  tickFormatter={(val) => (val * 100).toFixed(0) + '%'} />
                <Tooltip
                  cursor={{ fill: isDarkMode ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }}
                  contentStyle={{
                    backgroundColor: colors.tooltip.bg,
                    border: `1px solid ${colors.tooltip.border}`,
                    borderRadius: '12px',
                    backdropFilter: 'blur(10px)',
                    fontSize: '14px',
                    color: colors.text
                  }}
                  itemStyle={{ color: colors.text }}
                />
                <Bar dataKey="spread" radius={[6, 6, 0, 0]}>
                  {sectors.map((entry) => {
                    const isSelected = selectedSector?.ticker === entry.ticker
                    let fill = isDarkMode ? '#34d399' : '#10B981' // Emerald
                    if (isSelected) {
                      fill = isDarkMode ? '#10b981' : '#059669' 
                    } else if (entry.spread <= 0) {
                      fill = colors.negative // Theme-aware for negative
                    }
                    return (
                      <Cell
                        key={`cell-${entry.ticker}`}
                        fill={fill}
                        style={{ cursor: 'pointer', transition: 'fill 0.3s ease' }}
                        onClick={() => setSelectedSector(entry)}
                      />
                    )
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* All 11 Sectors - sorted by acceleration best to worst */}
        <div className="xl:w-[65%]">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3 gap-4">
            {sectors.map((sector, index) => {
              const isSelected = selectedSector?.ticker === sector.ticker;
              const rankColors = [
                '#fbbf24', // 1st - Gold
                '#9ca3af', // 2nd - Silver
                '#b45309', // 3rd - Bronze
              ];
              const rankBg = index < 3 ? rankColors[index] : (isDarkMode ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)');
              const rankText = index < 3 ? '#000' : colors.muted;

              return (
                <Card
                  key={sector.ticker}
                  className="p-4 relative overflow-hidden cursor-pointer hover-lift flex flex-col justify-between"
                  onClick={() => setSelectedSector(sector)}
                  style={{
                    background: isSelected
                      ? (isDarkMode ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(16, 185, 129, 0.02) 100%)' : 'rgba(16, 185, 129, 0.08)')
                      : colors.surface,
                    border: `1px solid ${isSelected ? (isDarkMode ? 'rgba(16, 185, 129, 0.4)' : 'rgba(16, 185, 129, 0.5)') : colors.border}`,
                    boxShadow: isSelected ? '0 10px 30px rgba(16,185,129,0.15)' : 'none',
                    backdropFilter: 'blur(10px)',
                    transition: 'all 0.3s ease',
                    minHeight: 180,
                  }}
                >
                  {isSelected && isDarkMode && <div style={{ position: 'absolute', top: '0', right: '0', width: '150px', height: '150px', background: 'radial-gradient(circle, rgba(16,185,129,0.2) 0%, transparent 70%)', filter: 'blur(20px)', pointerEvents: 'none' }} />}

                  <div className="relative z-10">
                    <div className="flex justify-between items-start mb-3">
                      <div
                        className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                        style={{
                          backgroundColor: rankBg,
                          color: rankText,
                          boxShadow: index < 3 ? '0 2px 10px rgba(0,0,0,0.2)' : 'none',
                        }}
                      >
                        {index + 1}
                      </div>
                      <div className="flex items-center gap-2">
                        {isSelected && <CheckCircle2 className="w-5 h-5 text-emerald-500" />}
                        <SaveHypothesisPopover
                          source="sectors"
                          ticker={sector.ticker}
                          sector={sector.name}
                          sourceMeta={{ page: 'sectors', tile: sector.ticker, perf_3m: sector.perf_3m }}
                        />
                      </div>
                    </div>

                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>{sector.ticker}</h3>
                      {regimes[sector.ticker] && (
                        <span style={{
                          padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                          background: regimes[sector.ticker].regime === 'BULL' ? 'rgba(16,185,129,.15)' : 'rgba(239,68,68,.15)',
                          color: regimes[sector.ticker].regime === 'BULL' ? '#10B981' : '#EF4444',
                        }}>
                          {regimes[sector.ticker].regime}
                        </span>
                      )}
                    </div>
                    <p className="text-xs truncate mb-4" style={{ color: colors.muted }}>{sector.name}</p>
                  </div>

                  <div className="space-y-3 relative z-10">
                    <div>
                      <p className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: colors.muted }}>Acceleration</p>
                      <p className={`text-lg font-mono ${sector.spread >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>
                        {sector.spread >= 0 ? '+' : ''}{formatPercent(sector.spread)}
                      </p>
                    </div>
                    <div className="pt-2" style={{ borderTop: `1px solid ${colors.border}` }}>
                      <p className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: colors.muted }}>3M Perf</p>
                      <p className="text-sm font-mono" style={{ color: colors.text }}>{(sector.perf_3m * 100).toFixed(2)}%</p>
                    </div>
                    {sector.forward_return != null && (
                      <div className="pt-2" style={{ borderTop: `1px solid ${colors.border}` }}>
                        <p className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: colors.muted }}>{holdingDays}d Fwd</p>
                        <p className={`text-sm font-mono font-bold ${sector.forward_return >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>
                          {sector.forward_return >= 0 ? '+' : ''}{(sector.forward_return * 100).toFixed(2)}%
                        </p>
                      </div>
                    )}
                  </div>
                </Card>
              )
            })}
          </div>
        </div>
      </div>

      {/* Stock Leaders */}
      <div style={{ marginTop: '100px', marginBottom: '60px' }}>
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <div className="flex flex-col xl:flex-row items-start xl:items-center justify-between gap-6 mb-4">
            <div className="text-left">
              <h2 className="text-3xl font-bold tracking-tight mb-2" style={{ color: colors.text }}>
                {viewMode === 'sector'
                  ? `Momentum Leaders in ${selectedSector?.ticker}`
                  : 'Top 20 Momentum Leaders (All Sectors)'}
              </h2>
              <p className="text-base" style={{ color: colors.muted }}>
                {viewMode === 'sector'
                  ? 'Top performing stocks currently exhibiting technical strength'
                  : 'Highest 3-month performers across all 11 sectors, regardless of industry'}
              </p>
            </div>
            <div className="flex items-center gap-4">
              <div
                className="flex p-1 rounded-xl"
                style={{
                  backgroundColor: isDarkMode ? 'rgba(255,255,255,0.05)' : '#f5f5f7',
                  border: `1px solid ${colors.border}`,
                }}
              >
                <button
                  onClick={() => setViewMode('sector')}
                  className="px-4 py-2 rounded-lg text-sm font-semibold transition-all"
                  style={{
                    backgroundColor: viewMode === 'sector' ? (isDarkMode ? 'rgba(16,185,129,0.2)' : '#10B981') : 'transparent',
                    color: viewMode === 'sector' ? (isDarkMode ? '#34D399' : '#000000') : colors.muted,
                    border: viewMode === 'sector' ? `1px solid ${isDarkMode ? 'rgba(16,185,129,0.4)' : '#10B981'}` : '1px solid transparent',
                  }}
                >
                  Sector Leaders
                </button>
                <button
                  onClick={() => setViewMode('top20')}
                  className="px-4 py-2 rounded-lg text-sm font-semibold transition-all"
                  style={{
                    backgroundColor: viewMode === 'top20' ? (isDarkMode ? 'rgba(16,185,129,0.2)' : '#10B981') : 'transparent',
                    color: viewMode === 'top20' ? (isDarkMode ? '#34D399' : '#000000') : colors.muted,
                    border: viewMode === 'top20' ? `1px solid ${isDarkMode ? 'rgba(16,185,129,0.4)' : '#10B981'}` : '1px solid transparent',
                  }}
                >
                  Top 20 All Sectors
                </button>
              </div>
              {viewMode === 'sector' && stocks.length > 0 && (
                <button
                  onClick={() => exportToQuantGen(stocks)}
                  className="px-5 py-3 rounded-xl text-sm font-bold uppercase tracking-wider transition-all hover:scale-105"
                  style={{
                    backgroundColor: '#10B981',
                    color: '#000000',
                    border: '1px solid #10B981',
                    boxShadow: '0 0 20px rgba(16,185,129,0.3)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = '#34D399'
                    e.currentTarget.style.boxShadow = '0 0 30px rgba(16,185,129,0.5)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = '#10B981'
                    e.currentTarget.style.boxShadow = '0 0 20px rgba(16,185,129,0.3)'
                  }}
                >
                  Export {stocks.length} Tickers to QuantGen
                </button>
              )}
              {viewMode === 'top20' && topLeaders.length > 0 && (
                <button
                  onClick={() => exportToQuantGen(topLeaders)}
                  className="px-5 py-3 rounded-xl text-sm font-bold uppercase tracking-wider transition-all hover:scale-105"
                  style={{
                    backgroundColor: '#10B981',
                    color: '#000000',
                    border: '1px solid #10B981',
                    boxShadow: '0 0 20px rgba(16,185,129,0.3)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = '#34D399'
                    e.currentTarget.style.boxShadow = '0 0 30px rgba(16,185,129,0.5)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = '#10B981'
                    e.currentTarget.style.boxShadow = '0 0 20px rgba(16,185,129,0.3)'
                  }}
                >
                  Export {topLeaders.length} Tickers to QuantGen
                </button>
              )}
            </div>
          </div>
        </div>

        {viewMode === 'sector' ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '24px' }}>
            {stocks.map((stock) => {
              const volumeRatio = stock.volume_today / stock.volume_avg_20d
              const isVolumeSpike = volumeRatio > 1.5
              const isPriceBreakout = stock.price > stock.high_10d
              const isSqueezeTriggered = isVolumeSpike && isPriceBreakout && stock.bb_expanding

              return (
                <motion.div
                  key={stock.ticker}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="border rounded-2xl p-7 overflow-hidden relative hover-lift"
                  style={{
                    backgroundColor: isDarkMode ? (isSqueezeTriggered ? 'rgba(16, 185, 129, 0.05)' : colors.surface) : (isSqueezeTriggered ? '#f0fdf4' : '#ffffff'),
                    borderColor: isSqueezeTriggered ? 'rgba(16, 185, 129, 0.6)' : colors.border,
                    boxShadow: isSqueezeTriggered
                      ? (isDarkMode ? '0 0 30px rgba(16, 185, 129, 0.3), inset 0 0 20px rgba(16,185,129,0.1)' : '0 10px 30px rgba(16, 185, 129, 0.2)')
                      : (isDarkMode ? '0 10px 30px rgba(0,0,0,0.4)' : '0 5px 15px rgba(0,0,0,0.05)'),
                    backdropFilter: 'blur(10px)',
                    transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
                  }}
                >
                  {isSqueezeTriggered && (
                    <div
                      className="absolute top-0 right-0 text-xs font-bold px-4 py-1.5 rounded-bl-2xl uppercase tracking-tight"
                      style={{
                        backgroundColor: '#10B981',
                        color: '#ffffff',
                        boxShadow: '0 4px 15px rgba(16,185,129,0.4)'
                      }}
                    >
                      Triggered
                    </div>
                  )}

                  <div className="flex justify-between items-start mb-6">
                    <div>
                      <h4 className="text-3xl font-bold leading-none mb-2" style={{ color: colors.text }}>{stock.ticker}</h4>
                      <p className="text-sm" style={{ color: colors.muted }}>{stock.name}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-2xl font-mono" style={{ color: colors.text }}>${stock.price.toFixed(2)}</p>
                      <p className="text-xs uppercase mt-1" style={{ color: colors.muted }}>Price on {stock.ref_date || 'latest'}</p>
                      {stock.forward_return != null && (
                        <p className={`text-sm font-mono font-bold mt-1 ${stock.forward_return >= 0 ? 'text-emerald-500' : 'text-red-400'}`}>
                          {stock.forward_return >= 0 ? '+' : ''}{(stock.forward_return * 100).toFixed(2)}% ({holdingDays}d fwd)
                        </p>
                      )}
                    </div>
                  </div>

                  <ProgressMetric
                    value={((stock.perf_3m - stock.sector_perf_3m) * 100).toFixed(2)}
                    label="3M Outperformance"
                    progress={Math.min(100, Math.max(0, ((stock.perf_3m - stock.sector_perf_3m) * 100 + 50)))}
                    progressColor="emerald"
                    suffix={`% vs ${selectedSector?.ticker}`}
                  />

                  <div className="grid grid-cols-3 gap-3 mt-6">
                    <button
                      onClick={() => fetchChartData(stock.ticker)}
                      className="p-3 rounded-xl border flex flex-col items-center justify-center gap-2 transition-all hover:scale-[1.02] active:scale-95 group relative"
                      style={{
                        backgroundColor: isPriceBreakout ? 'rgba(16, 185, 129, 0.1)' : isDarkMode ? 'rgba(63, 63, 70, 0.3)' : 'rgba(0, 0, 0, 0.05)',
                        borderColor: isPriceBreakout ? 'rgba(16, 185, 129, 0.4)' : colors.border
                      }}
                    >
                      <ArrowUpRight className={`w-5 h-5 ${isPriceBreakout ? 'text-emerald-500' : isDarkMode ? 'text-zinc-600' : 'text-zinc-400'}`} />
                      <span className={`text-xs uppercase font-bold ${isPriceBreakout ? 'text-emerald-500' : isDarkMode ? 'text-zinc-600' : 'text-zinc-500'}`}>Price</span>
                      <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Maximize2 className="w-3 h-3 text-emerald-500" />
                      </div>
                    </button>
                    <button
                      onClick={() => fetchChartData(stock.ticker)}
                      className="p-3 rounded-xl border flex flex-col items-center justify-center gap-2 transition-all hover:scale-[1.02] active:scale-95 group relative"
                      style={{
                        backgroundColor: isVolumeSpike ? 'rgba(16, 185, 129, 0.1)' : isDarkMode ? 'rgba(63, 63, 70, 0.3)' : 'rgba(0, 0, 0, 0.05)',
                        borderColor: isVolumeSpike ? 'rgba(16, 185, 129, 0.4)' : colors.border
                      }}
                    >
                      <Activity className={`w-5 h-5 ${isVolumeSpike ? 'text-emerald-500' : isDarkMode ? 'text-zinc-600' : 'text-zinc-400'}`} />
                      <span className={`text-xs uppercase font-bold ${isVolumeSpike ? 'text-emerald-500' : isDarkMode ? 'text-zinc-600' : 'text-zinc-500'}`}>Volume</span>
                      <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Maximize2 className="w-3 h-3 text-emerald-500" />
                      </div>
                    </button>
                    <button
                      onClick={() => fetchChartData(stock.ticker)}
                      className="p-3 rounded-xl border flex flex-col items-center justify-center gap-2 transition-all hover:scale-[1.02] active:scale-95 group relative"
                      style={{
                        backgroundColor: stock.bb_expanding ? 'rgba(16, 185, 129, 0.1)' : isDarkMode ? 'rgba(63, 63, 70, 0.3)' : 'rgba(0, 0, 0, 0.05)',
                        borderColor: stock.bb_expanding ? 'rgba(16, 185, 129, 0.4)' : colors.border
                      }}
                    >
                      <BarChart2 className={`w-5 h-5 ${stock.bb_expanding ? 'text-emerald-500' : isDarkMode ? 'text-zinc-600' : 'text-zinc-400'}`} />
                      <span className={`text-xs uppercase font-bold ${stock.bb_expanding ? 'text-emerald-500' : isDarkMode ? 'text-zinc-600' : 'text-zinc-500'}`}>Bands</span>
                      <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Maximize2 className="w-3 h-3 text-emerald-500" />
                      </div>
                    </button>
                  </div>

                  <button
                    onClick={() => setAnalyzedStock(stock)}
                    className="w-full mt-6 py-4 rounded-full text-sm font-bold uppercase tracking-widest transition-all hover-lift"
                    style={{
                      backgroundColor: isSqueezeTriggered ? '#10B981' : isDarkMode ? 'rgba(255,255,255,0.05)' : '#f5f5f7',
                      color: isSqueezeTriggered ? '#000000' : colors.text,
                      border: `1px solid ${isSqueezeTriggered ? '#10B981' : isDarkMode ? 'rgba(255,255,255,0.1)' : '#d2d2d7'}`,
                      boxShadow: isSqueezeTriggered ? '0 0 20px rgba(16,185,129,0.3)' : 'none'
                    }}
                    onMouseEnter={(e) => {
                      if (isSqueezeTriggered) {
                        e.currentTarget.style.backgroundColor = '#34D399';
                        e.currentTarget.style.boxShadow = '0 0 30px rgba(16,185,129,0.5)';
                      } else {
                        e.currentTarget.style.backgroundColor = isDarkMode ? 'rgba(255,255,255,0.1)' : '#e5e5e7';
                      }
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = isSqueezeTriggered ? '#10B981' : isDarkMode ? 'rgba(255,255,255,0.05)' : '#f5f5f7';
                      e.currentTarget.style.boxShadow = isSqueezeTriggered ? '0 0 20px rgba(16,185,129,0.3)' : 'none';
                    }}
                  >
                    Analyze Setup
                  </button>
                </motion.div>
              )
            })}
          </div>
        ) : (
          <div
            className="rounded-2xl overflow-hidden border"
            style={{
              backgroundColor: colors.surface,
              borderColor: colors.border,
              boxShadow: isDarkMode ? '0 10px 30px rgba(0,0,0,0.4)' : '0 5px 15px rgba(0,0,0,0.05)',
            }}
          >
            {loadingTopLeaders ? (
              <div className="flex flex-col items-center justify-center py-24 gap-4">
                <Activity className="w-10 h-10 text-emerald-500 animate-spin" />
                <p className="font-mono text-sm uppercase tracking-widest" style={{ color: colors.muted }}>Scanning all sectors...</p>
              </div>
            ) : topLeaders.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 gap-4">
                <p className="text-lg" style={{ color: colors.muted }}>No cross-sector momentum leaders available.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${colors.border}`, backgroundColor: isDarkMode ? 'rgba(255,255,255,0.03)' : '#f5f5f7' }}>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono" style={{ color: colors.muted }}>Rank</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono" style={{ color: colors.muted }}>Ticker</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono" style={{ color: colors.muted }}>Sector</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono text-right" style={{ color: colors.muted }}>1M Perf</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono text-right" style={{ color: colors.muted }}>3M Perf</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono text-right" style={{ color: colors.muted }}>6M Perf</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono text-right" style={{ color: colors.muted }}>Price</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono text-right" style={{ color: colors.muted }}>Volume</th>
                      <th className="p-4 text-xs uppercase tracking-wider font-mono text-center" style={{ color: colors.muted }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topLeaders.map((stock, index) => {
                      const volumeRatio = stock.volume_today / stock.volume_avg_20d
                      const rankColors = ['#fbbf24', '#9ca3af', '#b45309']
                      const rankBg = index < 3 ? rankColors[index] : (isDarkMode ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)')
                      const rankText = index < 3 ? '#000000' : colors.muted

                      return (
                        <tr
                          key={stock.ticker}
                          style={{ borderBottom: `1px solid ${colors.border}` }}
                          className="transition-colors hover:bg-emerald-500/5"
                        >
                          <td className="p-4">
                            <div
                              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                              style={{
                                backgroundColor: rankBg,
                                color: rankText,
                                boxShadow: index < 3 ? '0 2px 10px rgba(0,0,0,0.2)' : 'none',
                              }}
                            >
                              {index + 1}
                            </div>
                          </td>
                          <td className="p-4">
                            <button
                              onClick={() => setAnalyzedStock(stock)}
                              className="text-lg font-bold transition-colors hover:text-emerald-500"
                              style={{ color: colors.text }}
                            >
                              {stock.ticker}
                            </button>
                            <p className="text-xs" style={{ color: colors.muted }}>{stock.name}</p>
                          </td>
                          <td className="p-4">
                            <span className="text-sm" style={{ color: colors.text }}>{stock.sector}</span>
                          </td>
                          <td className="p-4 text-right font-mono text-sm" style={{ color: (stock.perf_1m || 0) >= 0 ? '#10B981' : '#f87171' }}>
                            {formatPercent(stock.perf_1m || 0)}
                          </td>
                          <td className="p-4 text-right font-mono text-sm font-bold" style={{ color: stock.perf_3m >= 0 ? '#10B981' : '#f87171' }}>
                            {formatPercent(stock.perf_3m)}
                          </td>
                          <td className="p-4 text-right font-mono text-sm" style={{ color: (stock.perf_6m || 0) >= 0 ? '#10B981' : '#f87171' }}>
                            {formatPercent(stock.perf_6m || 0)}
                          </td>
                          <td className="p-4 text-right font-mono text-sm" style={{ color: colors.text }}>
                            ${stock.price.toFixed(2)}
                          </td>
                          <td className="p-4 text-right">
                            <span className="text-sm font-mono" style={{ color: colors.text }}>{(stock.volume_today / 1_000_000).toFixed(2)}M</span>
                            <span className="text-xs ml-2 px-2 py-0.5 rounded-full" style={{
                              backgroundColor: volumeRatio > 1.5 ? 'rgba(16,185,129,0.15)' : (isDarkMode ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'),
                              color: volumeRatio > 1.5 ? '#10B981' : colors.muted
                            }}>
                              {volumeRatio.toFixed(2)}x
                            </span>
                          </td>
                          <td className="p-4 text-center">
                            <div className="flex items-center justify-center gap-2">
                              <button
                                onClick={() => fetchChartData(stock.ticker)}
                                className="p-2 rounded-lg transition-colors"
                                style={{
                                  backgroundColor: isDarkMode ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
                                  color: colors.muted,
                                }}
                                title="View chart"
                              >
                                <BarChart2 className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => setAnalyzedStock(stock)}
                                className="px-3 py-2 rounded-lg text-xs font-bold uppercase tracking-wider transition-colors"
                                style={{
                                  backgroundColor: '#10B981',
                                  color: '#000000',
                                }}
                              >
                                Analyze
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Analysis Modal */}
      <AnimatePresence>
        {analyzedStock && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setAnalyzedStock(null)}
            className="fixed inset-0 backdrop-blur-sm z-50 flex items-center justify-center p-8"
            style={{ backgroundColor: isDarkMode ? 'rgba(0, 0, 0, 0.8)' : 'rgba(0, 0, 0, 0.6)' }}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="rounded-3xl max-w-lg w-full relative overflow-hidden"
              style={{ 
                backgroundColor: isDarkMode ? 'rgba(20,20,22,0.95)' : '#ffffff', 
                border: `1px solid ${colors.border}`,
                boxShadow: isDarkMode ? '0 30px 60px rgba(0,0,0,0.6), 0 0 100px rgba(16,185,129,0.15)' : '0 20px 40px rgba(0,0,0,0.1)',
                backdropFilter: 'blur(20px)',
                padding: '40px'
              }}
            >
              {isDarkMode && <div style={{ position: 'absolute', top: '-10%', left: '-10%', width: '120%', height: '120%', background: 'radial-gradient(circle at 50% 0%, rgba(16,185,129,0.15) 0%, transparent 60%)', pointerEvents: 'none' }} />}
              
              <div className="flex justify-between items-start mb-8 relative z-10">
                <div>
                  <h3 className="text-4xl font-bold tracking-tight" style={{ color: colors.text }}>{analyzedStock.ticker}</h3>
                  <p className="text-lg mt-1 font-mono uppercase" style={{ color: colors.muted }}>{analyzedStock.name}</p>
                </div>
                <button
                  onClick={() => setAnalyzedStock(null)}
                  className="p-2 rounded-full transition-colors backdrop-blur-sm"
                  style={{ color: colors.muted, backgroundColor: isDarkMode ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = colors.text;
                    e.currentTarget.style.backgroundColor = isDarkMode ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.1)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = colors.muted;
                    e.currentTarget.style.backgroundColor = isDarkMode ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)';
                  }}
                >
                  <X size={24} />
                </button>
              </div>

              <div className="relative z-10">
                <Card variant="raised" className="mb-6" style={{ backgroundColor: isDarkMode ? 'rgba(255,255,255,0.02)' : '#ffffff', border: `1px solid ${colors.border}`, padding: '24px' }}>
                <h4 className="text-sm font-mono uppercase mb-4" style={{ color: colors.muted }}>Bollinger Bands (20, 2)</h4>
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-sm" style={{ color: colors.muted }}>Upper Band</span>
                    <span className="text-base font-mono text-emerald-400">${analyzedStock.bb_upper.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm" style={{ color: colors.muted }}>Middle (SMA20)</span>
                    <span className="text-base font-mono" style={{ color: colors.text }}>${analyzedStock.bb_middle.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm" style={{ color: colors.muted }}>Lower Band</span>
                    <span className="text-base font-mono text-red-400">${analyzedStock.bb_lower.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between pt-3" style={{ borderTop: `1px solid ${colors.border}` }}>
                    <span className="text-sm" style={{ color: colors.muted }}>Current Price</span>
                    <span className="text-lg font-mono font-bold" style={{ color: colors.text }}>${analyzedStock.price.toFixed(2)}</span>
                  </div>
                </div>
              </Card>

              <div className="grid grid-cols-2 gap-4 mb-6">
                <Card
                  style={{
                    backgroundColor: analyzedStock.price > (analyzedStock.sma50 || 0) ? 'rgba(16, 185, 129, 0.1)' : colors.surface,
                    borderColor: analyzedStock.price > (analyzedStock.sma50 || 0) ? 'rgba(16, 185, 129, 0.3)' : colors.border,
                    padding: '20px'
                  }}
                >
                  <span className="text-xs uppercase" style={{ color: colors.muted }}>Price vs SMA50</span>
                  <p className={`text-base font-mono mt-2 ${analyzedStock.price > (analyzedStock.sma50 || 0) ? 'text-emerald-400' : 'text-red-400'}`}>
                    {analyzedStock.price > (analyzedStock.sma50 || 0) ? 'Above' : 'Below'} ${analyzedStock.sma50?.toFixed(2) || 'N/A'}
                  </p>
                </Card>
                <Card
                  style={{
                    backgroundColor: analyzedStock.price > (analyzedStock.sma200 || 0) ? 'rgba(16, 185, 129, 0.1)' : colors.surface,
                    borderColor: analyzedStock.price > (analyzedStock.sma200 || 0) ? 'rgba(16, 185, 129, 0.3)' : colors.border,
                    padding: '20px'
                  }}
                >
                  <span className="text-xs uppercase" style={{ color: colors.muted }}>Price vs SMA200</span>
                  <p className={`text-base font-mono mt-2 ${analyzedStock.price > (analyzedStock.sma200 || 0) ? 'text-emerald-400' : 'text-red-400'}`}>
                    {analyzedStock.price > (analyzedStock.sma200 || 0) ? 'Above' : 'Below'} ${analyzedStock.sma200?.toFixed(2) || 'N/A'}
                  </p>
                </Card>
              </div>

              <Card variant="raised" style={{ backgroundColor: isDarkMode ? 'rgba(255,255,255,0.02)' : '#ffffff', border: `1px solid ${colors.border}`, padding: '20px' }}>
                <h4 className="text-sm font-mono uppercase mb-3" style={{ color: colors.muted }}>Setup Strength</h4>
                <div className="flex items-center gap-5">
                  <div
                    className="flex-1 h-4 rounded-full overflow-hidden"
                    style={{ backgroundColor: isDarkMode ? '#3f3f46' : '#e5e5e7' }}
                  >
                    <div
                      className="h-full transition-all"
                      style={{
                        width: `${getStrengthScore(analyzedStock)}%`,
                        background: getStrengthScore(analyzedStock) >= 75
                          ? 'linear-gradient(to right, #059669, #34D399)'
                          : getStrengthScore(analyzedStock) >= 50
                            ? 'linear-gradient(to right, #d97706, #fbbf24)'
                            : 'linear-gradient(to right, #dc2626, #f87171)'
                      }}
                    />
                  </div>
                  <span
                    className="text-xl font-mono font-bold"
                    style={{
                      color: getStrengthScore(analyzedStock) >= 75
                        ? '#34D399'
                        : getStrengthScore(analyzedStock) >= 50
                          ? '#fbbf24'
                          : '#f87171'
                    }}
                  >
                    {getStrengthScore(analyzedStock)}%
                  </span>
                </div>
              </Card>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Chart Modal */}
      <AnimatePresence>
        {chartTicker && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setChartTicker(null)}
            className="fixed inset-0 backdrop-blur-md z-[60] flex items-center justify-center p-4 md:p-12"
            style={{ backgroundColor: 'rgba(0, 0, 0, 0.85)' }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 20 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-[#0c0c0e] border border-white/10 rounded-3xl w-full max-w-[90vw] max-h-[95vh] overflow-y-auto shadow-2xl shadow-emerald-500/10"
            >
              {/* Chart Header */}
              <div className="flex items-center justify-between p-6 border-b border-white/5 bg-white/5 sticky top-0 z-20 backdrop-blur-md">
                <div className="flex items-center gap-4">
                  <div className="bg-emerald-500/20 p-2.5 rounded-xl border border-emerald-500/30">
                    <TrendingUp className="w-6 h-6 text-emerald-500" />
                  </div>
                  <div>
                    <h3 className="text-2xl font-bold text-white leading-tight">{chartTicker} Technical Chart</h3>
                    <p className="text-sm text-zinc-400 font-mono uppercase tracking-widest mt-0.5">Bollinger Bands (20, 2) Overlay</p>
                  </div>
                </div>
                <button
                  onClick={() => setChartTicker(null)}
                  className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-all"
                >
                  <X size={24} />
                </button>
              </div>

              {/* Chart Content */}
              <div className="p-2 relative min-h-[750px]">
                {isChartLoading ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
                    <Activity className="w-12 h-12 text-emerald-500 animate-spin" />
                    <p className="text-zinc-500 font-mono text-sm tracking-widest uppercase">Fetching Market Data...</p>
                  </div>
                ) : chartData.length > 0 ? (
                  <div className="p-4">
                    <CandleStickChart
                      key={chartTicker}
                      height={750}
                      data={chartData}
                      indicators={[
                        {
                          name: 'Upper Band',
                          type: 'line',
                          color: 'rgba(16, 185, 129, 0.4)',
                          data: chartData.filter(d => d.bb_upper !== undefined).map(d => ({ time: d.time, value: d.bb_upper }))
                        },
                        {
                          name: 'Middle Band',
                          type: 'line',
                          color: 'rgba(16, 185, 129, 0.2)',
                          data: chartData.filter(d => d.bb_middle !== undefined).map(d => ({ time: d.time, value: d.bb_middle }))
                        },
                        {
                          name: 'Lower Band',
                          type: 'line',
                          color: 'rgba(16, 185, 129, 0.4)',
                          data: chartData.filter(d => d.bb_lower !== undefined).map(d => ({ time: d.time, value: d.bb_lower }))
                        },
                        {
                          name: 'SMA 50',
                          type: 'line',
                          color: 'rgba(59, 130, 246, 0.4)',
                          data: chartData.filter(d => d.sma50 !== undefined).map(d => ({ time: d.time, value: d.sma50 }))
                        }
                      ]}
                    />


                    <div className="mt-8 grid grid-cols-3 gap-6 px-4 pb-6">
                      <div className="bg-white/5 border border-white/5 rounded-3xl p-8">
                        <div className="flex justify-between items-end mb-6">
                          <p className="text-sm text-emerald-500 uppercase font-bold tracking-widest">Price Action</p>
                          <p className="text-4xl font-mono text-white font-bold leading-none">${chartData[chartData.length - 1]?.close.toFixed(2)}</p>
                        </div>
                        <div className="space-y-4 pt-6 border-t border-white/5">
                          <div className="flex justify-between text-xl font-mono">
                            <span className="text-zinc-500 uppercase">SMA 20</span>
                            <span className="text-emerald-400 font-bold">${chartData[chartData.length - 1]?.sma20?.toFixed(2) || 'N/A'}</span>
                          </div>
                          <div className="flex justify-between text-xl font-mono">
                            <span className="text-zinc-500 uppercase">SMA 50</span>
                            <span className="text-emerald-400 font-bold">${chartData[chartData.length - 1]?.sma50?.toFixed(2) || 'N/A'}</span>
                          </div>
                        </div>
                      </div>
                      
                      <div className="bg-white/5 border border-white/5 rounded-3xl p-8">
                        <div className="flex justify-between items-end mb-6">
                          <p className="text-sm text-blue-500 uppercase font-bold tracking-widest">Volume Metrics</p>
                          <p className="text-4xl font-mono text-white font-bold leading-none">{(chartData[chartData.length - 1]?.volume / 1000000).toFixed(2)}M</p>
                        </div>
                        <div className="space-y-4 pt-6 border-t border-white/5">
                          <div className="flex justify-between text-xl font-mono">
                            <span className="text-zinc-500 uppercase">SMA 20 (V)</span>
                            <span className="text-blue-400 font-bold">{(chartData[chartData.length - 1]?.vol_sma20 / 1000000).toFixed(2)}M</span>
                          </div>
                          <div className="flex justify-between text-xl font-mono">
                            <span className="text-zinc-500 uppercase">SMA 50 (V)</span>
                            <span className="text-blue-400 font-bold">{(chartData[chartData.length - 1]?.vol_sma50 / 1000000).toFixed(2)}M</span>
                          </div>
                        </div>
                      </div>

                      <div className="bg-white/5 border border-white/5 rounded-3xl p-8 flex flex-col justify-center items-center">
                        <div className="text-center w-full">
                          <p className="text-sm text-zinc-500 uppercase font-bold tracking-widest mb-2">Timeframe</p>
                          <p className="text-4xl font-mono text-white font-bold">Daily (150D)</p>
                          <div className="mt-6 pt-6 border-t border-white/5 w-full">
                            <p className="text-sm text-zinc-500 uppercase font-bold tracking-widest mb-2">Market Status</p>
                            <p className="text-xl font-mono text-emerald-500 font-bold uppercase tracking-widest">Live Data Active</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center text-zinc-500">
                    Unable to load chart data for {chartTicker}
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      </div>
    </div>
  )
}