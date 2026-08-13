import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  Filter,
  Clock,
  TrendingUp,
  Trash2,
  Edit3,
  ArrowRight,
  ArrowLeft,
  Plus,
  Calendar,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Library as LibraryIcon,
} from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { clearAppReferrer } from '@/components/layout/Layout';
import { quantgen } from '@/lib/api';

interface Strategy {
  id: string;
  name: string;
  description: string;
  code?: string;
  createdAt: string;
  updatedAt: string;
  status: 'draft' | 'backtested' | 'optimized' | 'live';
  metrics?: {
    totalReturn?: number;
    sharpeRatio?: number;
    maxDrawdown?: number;
    winRate?: number;
    trades?: number;
  };
}

type SortField = 'name' | 'updatedAt' | 'status' | 'return';
type SortDirection = 'asc' | 'desc';
type StatusFilter = 'all' | 'draft' | 'backtested' | 'optimized' | 'live';

const statusConfig: Record<Strategy['status'], { icon: typeof AlertCircle; label: string; dot: string }> = {
  draft: { icon: AlertCircle, label: 'Draft', dot: 'var(--subtle)' },
  backtested: { icon: Clock, label: 'Backtested', dot: '#3b82f6' },
  optimized: { icon: CheckCircle2, label: 'Optimized', dot: 'var(--accent)' },
  live: { icon: TrendingUp, label: 'Live', dot: '#a855f7' },
};

export default function Library() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortField, setSortField] = useState<SortField>('updatedAt');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'builtin' | 'saved'>('builtin');
  const [builtinStrategies, setBuiltinStrategies] = useState<Record<string, any[]>>({});
  const [builtinCategories, setBuiltinCategories] = useState<string[]>([]);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [isLoadingBuiltin, setIsLoadingBuiltin] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem('builderState');
      if (saved) {
        const state = JSON.parse(saved);
        if (state.strategies && Array.isArray(state.strategies)) setStrategies(state.strategies);
      }
    } catch {}
    setIsLoading(false);
  }, []);

  useEffect(() => {
    if (activeTab !== 'builtin') return;
    setIsLoadingBuiltin(true);
    quantgen.strategyCatalog()
      .then(data => {
        if (data.success && data.data) {
          setBuiltinStrategies(data.data.strategies_by_category || {});
          setBuiltinCategories(data.data.categories || []);
        }
      })
      .catch(() => {})
      .finally(() => setIsLoadingBuiltin(false));
  }, [activeTab]);

  const deleteStrategy = (id: string) => {
    if (!confirm('Are you sure?')) return;
    const newStrategies = strategies.filter((s) => s.id !== id);
    setStrategies(newStrategies);
    try {
      const saved = localStorage.getItem('builderState');
      if (saved) { const state = JSON.parse(saved); state.strategies = newStrategies; localStorage.setItem('builderState', JSON.stringify(state)); }
    } catch {}
  };

  const loadStrategy = (strategy: Strategy) => {
    sessionStorage.setItem('loadStrategy', JSON.stringify(strategy));
    window.location.href = '/quantgen/build';
  };

  const toggleSort = (field: SortField) => {
    if (sortField === field) setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    else { setSortField(field); setSortDirection('desc'); }
  };

  const filteredStrategies = strategies
    .filter((s) => {
      const q = searchQuery.toLowerCase();
      return (s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)) && (statusFilter === 'all' || s.status === statusFilter);
    })
    .sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'name': cmp = a.name.localeCompare(b.name); break;
        case 'updatedAt': cmp = new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime(); break;
        case 'status': cmp = a.status.localeCompare(b.status); break;
        case 'return': cmp = (a.metrics?.totalReturn || 0) - (b.metrics?.totalReturn || 0); break;
      }
      return sortDirection === 'asc' ? cmp : -cmp;
    });

  const formatDate = (dateStr: string) => new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <div style={{ minHeight: '100%', backgroundColor: 'var(--canvas)' }}>
      <div style={{ padding: '24px 80px 64px' }}>
        <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
            <div>
              <h1 style={{ fontSize: '24px', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--foreground)' }}>
                Strategy Library
              </h1>
              <p style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '2px' }}>
                Manage and organize your trading strategies
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <NavLink
                to="/quantgen/build"
                onClick={() => clearAppReferrer()}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 16px', borderRadius: '8px', fontSize: '13px', fontWeight: 600, textDecoration: 'none', backgroundColor: 'transparent', border: '1px solid var(--border)', color: 'var(--accent)' }}
              >
                <ArrowLeft size={15} />
                Back to Builder
              </NavLink>
              <NavLink
                to="/quantgen/build"
                onClick={() => {
                  try {
                    const saved = localStorage.getItem('builderState');
                    if (saved) {
                      const state = JSON.parse(saved);
                      delete state.code;
                      delete state.strategyPrompt;
                      delete state.currentFilename;
                      delete state.optParams;
                      delete state.output;
                      delete state.structuredError;
                      localStorage.setItem('builderState', JSON.stringify(state));
                    }
                    sessionStorage.removeItem('loadStrategy');
                    clearAppReferrer();
                  } catch {}
                }}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '8px 20px', borderRadius: '999px', fontSize: '13px', fontWeight: 600, textDecoration: 'none', backgroundColor: 'var(--accent)', color: 'var(--accent-ink)' }}
              >
                <Plus size={15} />
                New Strategy
              </NavLink>
            </div>
          </div>

          {/* Tab Switcher */}
          <div style={{ display: 'flex', gap: '4px', marginBottom: '20px', padding: '4px', borderRadius: '12px', backgroundColor: 'var(--surface)', border: '1px solid var(--border)', width: 'fit-content' }}>
            <button
              onClick={() => setActiveTab('builtin')}
              style={{
                padding: '8px 20px', borderRadius: '8px', fontSize: '13px', fontWeight: 600,
                border: 'none', cursor: 'pointer',
                backgroundColor: activeTab === 'builtin' ? 'var(--accent)' : 'transparent',
                color: activeTab === 'builtin' ? 'var(--accent-ink)' : 'var(--subtle)',
                display: 'flex', alignItems: 'center', gap: '6px',
              }}
            >
              <LibraryIcon size={14} />
              Built-in
            </button>
            <button
              onClick={() => setActiveTab('saved')}
              style={{
                padding: '8px 20px', borderRadius: '8px', fontSize: '13px', fontWeight: 600,
                border: 'none', cursor: 'pointer',
                backgroundColor: activeTab === 'saved' ? 'var(--accent)' : 'transparent',
                color: activeTab === 'saved' ? 'var(--accent-ink)' : 'var(--subtle)',
                display: 'flex', alignItems: 'center', gap: '6px',
              }}
            >
              <Edit3 size={14} />
              My Strategies
            </button>
          </div>

          {activeTab === 'builtin' ? (
            <div>
              {isLoadingBuiltin ? (
                <div style={{ textAlign: 'center', padding: '48px', color: 'var(--muted)', fontSize: '13px' }}>
                  Loading strategies...
                </div>
              ) : (
                <>
                  {/* Category filter chips */}
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
                    {['all', ...builtinCategories].map(cat => (
                      <button
                        key={cat}
                        onClick={() => setCategoryFilter(cat)}
                        style={{
                          padding: '6px 14px', borderRadius: '999px', fontSize: '12px', fontWeight: 600,
                          cursor: 'pointer',
                          backgroundColor: categoryFilter === cat ? 'var(--accent)' : 'var(--surface)',
                          color: categoryFilter === cat ? 'var(--accent-ink)' : 'var(--subtle)',
                          textTransform: 'capitalize',
                          border: categoryFilter !== cat ? '1px solid var(--border)' : 'none',
                        }}
                      >
                        {cat === 'all' ? 'All' : `${cat} (${(builtinStrategies[cat] || []).length})`}
                      </button>
                    ))}
                  </div>

                  {/* Strategy cards grid */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '12px' }}>
                    {Object.entries(builtinStrategies)
                      .filter(([cat]) => categoryFilter === 'all' || cat === categoryFilter)
                      .map(([category, strategies]) =>
                        strategies.map((strategy: any, idx: number) => (
                          <div key={`${category}-${idx}`} style={{
                            padding: '20px', borderRadius: '14px',
                            backgroundColor: 'var(--surface)', border: '1px solid var(--border)',
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                              <div>
                                <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--foreground)' }}>
                                  {strategy.name}
                                </span>
                                <span style={{
                                  display: 'inline-block', marginLeft: '8px', padding: '2px 8px',
                                  borderRadius: '4px', fontSize: '10px', fontWeight: 600,
                                  backgroundColor: 'var(--accent-glow)', color: 'var(--accent)',
                                  textTransform: 'capitalize',
                                }}>
                                  {strategy.category}
                                </span>
                              </div>
                            </div>
                            <p style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: 1.5, marginBottom: '12px' }}>
                              {strategy.description}
                            </p>
                            {strategy.parameters && (
                              <div style={{ marginBottom: '12px' }}>
                                <div style={{ fontSize: '10px', fontWeight: 600, color: 'var(--subtle)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>
                                  Parameters
                                </div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                  {Object.entries(strategy.parameters).slice(0, 4).map(([key, val]: [string, any]) => (
                                    <span key={key} style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '4px', backgroundColor: 'var(--canvas)', color: 'var(--muted)' }}>
                                      {key}={val.default}
                                    </span>
                                  ))}
                                  {Object.keys(strategy.parameters).length > 4 && (
                                    <span style={{ fontSize: '11px', color: 'var(--subtle)' }}>
                                      +{Object.keys(strategy.parameters).length - 4} more
                                    </span>
                                  )}
                                </div>
                              </div>
                            )}
                            <button
                              onClick={() => { window.location.href = `/quantgen/build?load=${strategy.slug}`; }}
                              style={{
                                display: 'inline-flex', alignItems: 'center', gap: '6px',
                                padding: '8px 16px', borderRadius: '8px', fontSize: '12px', fontWeight: 600,
                                border: 'none', cursor: 'pointer',
                                backgroundColor: 'var(--accent)', color: 'var(--accent-ink)',
                              }}
                            >
                              <Edit3 size={13} />
                              Load into Builder
                            </button>
                          </div>
                        ))
                      )}
                  </div>

                  {Object.keys(builtinStrategies).length === 0 && (
                    <div style={{ textAlign: 'center', padding: '48px', color: 'var(--muted)', fontSize: '13px' }}>
                      No built-in strategies available.
                    </div>
                  )}
                </>
              )}
            </div>
          ) : (
            <>
              {/* Filters */}
              <div
                style={{
                  display: 'flex',
                  gap: '12px',
                  marginBottom: '20px',
                  padding: '12px 16px',
                  borderRadius: '14px',
                  backgroundColor: 'var(--surface)',
                  border: '1px solid var(--border)',
                  alignItems: 'center',
                }}
              >
                <div style={{ position: 'relative', flex: 1 }}>
                  <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--subtle)' }} />
                  <input
                    type="text"
                    placeholder="Search strategies..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px 8px 32px',
                      borderRadius: '8px',
                      border: '1px solid var(--border)',
                      backgroundColor: 'var(--canvas)',
                      color: 'var(--foreground)',
                      fontSize: '13px',
                      outline: 'none',
                    }}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Filter size={14} style={{ color: 'var(--subtle)' }} />
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
                    style={{
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border)',
                      backgroundColor: 'var(--canvas)',
                      color: 'var(--foreground)',
                      fontSize: '12px',
                      outline: 'none',
                    }}
                  >
                    <option value="all">All Status</option>
                    <option value="draft">Draft</option>
                    <option value="backtested">Backtested</option>
                    <option value="optimized">Optimized</option>
                    <option value="live">Live</option>
                  </select>
                </div>
              </div>

              {/* Column headers */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '3fr 1.5fr 1fr 1.5fr 1.5fr 48px',
                  gap: '12px',
                  padding: '0 16px 10px',
                  fontSize: '11px',
                  fontWeight: 600,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  color: 'var(--subtle)',
                  borderBottom: '1px solid var(--border)',
                }}
              >
                <button onClick={() => toggleSort('name')} style={{ textAlign: 'left', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', padding: 0, fontSize: 'inherit', fontWeight: 'inherit', letterSpacing: 'inherit', textTransform: 'inherit' }}>
                  Name {sortField === 'name' && (sortDirection === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
                </button>
                <button onClick={() => toggleSort('status')} style={{ textAlign: 'left', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', padding: 0, fontSize: 'inherit', fontWeight: 'inherit', letterSpacing: 'inherit', textTransform: 'inherit' }}>
                  Status {sortField === 'status' && (sortDirection === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
                </button>
                <button onClick={() => toggleSort('return')} style={{ textAlign: 'right', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end', padding: 0, fontSize: 'inherit', fontWeight: 'inherit', letterSpacing: 'inherit', textTransform: 'inherit' }}>
                  Return {sortField === 'return' && (sortDirection === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
                </button>
                <div style={{ textAlign: 'right' }}>Metrics</div>
                <button onClick={() => toggleSort('updatedAt')} style={{ textAlign: 'right', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end', padding: 0, fontSize: 'inherit', fontWeight: 'inherit', letterSpacing: 'inherit', textTransform: 'inherit' }}>
                  Updated {sortField === 'updatedAt' && (sortDirection === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
                </button>
                <div />
              </div>

              {/* Strategy list */}
              <div style={{ marginTop: '4px' }}>
                <AnimatePresence mode="popLayout">
                  {isLoading ? (
                    <div style={{ textAlign: 'center', padding: '48px', color: 'var(--muted)', fontSize: '13px' }}>
                      <div style={{ width: '24px', height: '24px', border: '2px solid var(--accent)', borderTopColor: 'transparent', borderRadius: '50%', margin: '0 auto 12px' }} className="animate-spin" />
                      Loading strategies...
                    </div>
                  ) : filteredStrategies.length === 0 ? (
                    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} style={{ textAlign: 'center', padding: '64px 24px' }}>
                      <div style={{ width: '56px', height: '56px', margin: '0 auto 16px', borderRadius: '50%', backgroundColor: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Search size={22} style={{ color: 'var(--subtle)' }} />
                      </div>
                      <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--foreground)', marginBottom: '4px' }}>
                        {strategies.length === 0 ? 'No Strategies Yet' : 'No Results Found'}
                      </h3>
                      <p style={{ fontSize: '13px', color: 'var(--muted)', maxWidth: '360px', margin: '0 auto 20px' }}>
                        {strategies.length === 0 ? 'Create your first trading strategy to get started.' : 'Try adjusting your search or filter.'}
                      </p>
                      {strategies.length === 0 && (
                        <NavLink to="/quantgen/build" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '8px 20px', borderRadius: '999px', fontSize: '13px', fontWeight: 600, textDecoration: 'none', backgroundColor: 'var(--accent)', color: 'var(--accent-ink)' }}>
                          <Plus size={15} /> Create Strategy
                        </NavLink>
                      )}
                    </motion.div>
                  ) : (
                    filteredStrategies.map((strategy) => {
                      const sc = statusConfig[strategy.status];
                      const isExpanded = expandedId === strategy.id;
                      return (
                        <motion.div
                          key={strategy.id}
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, scale: 0.97 }}
                          layout
                          style={{ marginBottom: '4px' }}
                        >
                          <div
                            style={{
                              borderRadius: '12px',
                              backgroundColor: 'var(--surface)',
                              border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--border)'}`,
                              overflow: 'hidden',
                              transition: 'border-color 0.15s ease',
                            }}
                          >
                            {/* Main row */}
                            <div
                              onClick={() => setExpandedId(isExpanded ? null : strategy.id)}
                              style={{
                                display: 'grid',
                                gridTemplateColumns: '3fr 1.5fr 1fr 1.5fr 1.5fr 48px',
                                gap: '12px',
                                padding: '12px 16px',
                                alignItems: 'center',
                                cursor: 'pointer',
                              }}
                            >
                              <div>
                                <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--foreground)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {strategy.name}
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {strategy.description}
                                </div>
                              </div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: sc.dot, flexShrink: 0 }} />
                                <span style={{ fontSize: '12px', color: 'var(--foreground)' }}>{sc.label}</span>
                              </div>
                              <div style={{ textAlign: 'right' }}>
                                {strategy.metrics?.totalReturn !== undefined ? (
                                  <span style={{ fontSize: '13px', fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: strategy.metrics.totalReturn >= 0 ? 'var(--accent)' : 'var(--bad)' }}>
                                    {strategy.metrics.totalReturn.toFixed(2)}%
                                  </span>
                                ) : (
                                  <span style={{ color: 'var(--subtle)', fontSize: '12px' }}>—</span>
                                )}
                              </div>
                              <div style={{ textAlign: 'right' }}>
                                {strategy.metrics ? (
                                  <div style={{ fontSize: '11px', display: 'flex', gap: '6px', justifyContent: 'flex-end', color: 'var(--subtle)' }}>
                                    {strategy.metrics.sharpeRatio !== undefined && <span>SR: {strategy.metrics.sharpeRatio.toFixed(2)}</span>}
                                    {strategy.metrics.winRate !== undefined && <span>WR: {strategy.metrics.winRate.toFixed(1)}%</span>}
                                  </div>
                                ) : <span style={{ color: 'var(--subtle)', fontSize: '12px' }}>—</span>}
                              </div>
                              <div style={{ textAlign: 'right', fontSize: '12px', color: 'var(--muted)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end' }}>
                                  <Calendar size={11} />
                                  {formatDate(strategy.updatedAt)}
                                </div>
                              </div>
                              <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }}>
                                <button
                                  onClick={(e) => { e.stopPropagation(); loadStrategy(strategy); }}
                                  style={{ padding: '6px', borderRadius: '6px', border: 'none', background: 'none', color: 'var(--subtle)', cursor: 'pointer' }}
                                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--surface-overlay)'; e.currentTarget.style.color = 'var(--accent)'; }}
                                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; e.currentTarget.style.color = 'var(--subtle)'; }}
                                >
                                  <Edit3 size={13} />
                                </button>
                                <button
                                  onClick={(e) => { e.stopPropagation(); deleteStrategy(strategy.id); }}
                                  style={{ padding: '6px', borderRadius: '6px', border: 'none', background: 'none', color: 'var(--subtle)', cursor: 'pointer' }}
                                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--danger-hover)'; e.currentTarget.style.color = 'var(--bad)'; }}
                                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; e.currentTarget.style.color = 'var(--subtle)'; }}
                                >
                                  <Trash2 size={13} />
                                </button>
                              </div>
                            </div>

                            {/* Expanded details */}
                            <AnimatePresence>
                              {isExpanded && (
                                <motion.div
                                  initial={{ height: 0, opacity: 0 }}
                                  animate={{ height: 'auto', opacity: 1 }}
                                  exit={{ height: 0, opacity: 0 }}
                                  transition={{ duration: 0.15 }}
                                  style={{ borderTop: '1px solid var(--border)' }}
                                >
                                  <div style={{ padding: '16px', backgroundColor: 'var(--surface-raised)' }}>
                                    {strategy.description && (
                                      <div style={{ marginBottom: '16px' }}>
                                        <h4 style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '6px' }}>Description</h4>
                                        <p style={{ fontSize: '13px', color: 'var(--foreground)', lineHeight: 1.5 }}>{strategy.description}</p>
                                      </div>
                                    )}
                                    {strategy.metrics && (
                                      <div style={{ marginBottom: '16px' }}>
                                        <h4 style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '8px' }}>Performance</h4>
                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
                                          {strategy.metrics.totalReturn !== undefined && (
                                            <div style={{ padding: '12px', borderRadius: '10px', backgroundColor: 'var(--canvas)' }}>
                                              <div style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '2px' }}>Total Return</div>
                                              <div style={{ fontSize: '15px', fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: strategy.metrics.totalReturn >= 0 ? 'var(--accent)' : 'var(--bad)' }}>{strategy.metrics.totalReturn.toFixed(2)}%</div>
                                            </div>
                                          )}
                                          {strategy.metrics.sharpeRatio !== undefined && (
                                            <div style={{ padding: '12px', borderRadius: '10px', backgroundColor: 'var(--canvas)' }}>
                                              <div style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '2px' }}>Sharpe Ratio</div>
                                              <div style={{ fontSize: '15px', fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--foreground)' }}>{strategy.metrics.sharpeRatio.toFixed(2)}</div>
                                            </div>
                                          )}
                                          {strategy.metrics.maxDrawdown !== undefined && (
                                            <div style={{ padding: '12px', borderRadius: '10px', backgroundColor: 'var(--canvas)' }}>
                                              <div style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '2px' }}>Max Drawdown</div>
                                              <div style={{ fontSize: '15px', fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--bad)' }}>{strategy.metrics.maxDrawdown.toFixed(2)}%</div>
                                            </div>
                                          )}
                                          {strategy.metrics.winRate !== undefined && (
                                            <div style={{ padding: '12px', borderRadius: '10px', backgroundColor: 'var(--canvas)' }}>
                                              <div style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '2px' }}>Win Rate</div>
                                              <div style={{ fontSize: '15px', fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--foreground)' }}>{strategy.metrics.winRate.toFixed(1)}%</div>
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                    )}
                                    {strategy.code && (
                                      <div style={{ marginBottom: '16px' }}>
                                        <h4 style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '6px' }}>Code Preview</h4>
                                        <pre style={{ padding: '12px', borderRadius: '8px', overflow: 'auto', fontSize: '11px', lineHeight: 1.5, backgroundColor: 'var(--canvas)', color: 'var(--muted)', maxHeight: '100px' }}>{strategy.code.slice(0, 500)}...</pre>
                                      </div>
                                    )}
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                      <button
                                        onClick={() => loadStrategy(strategy)}
                                        style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 16px', borderRadius: '8px', fontSize: '12px', fontWeight: 600, border: 'none', cursor: 'pointer', backgroundColor: 'var(--accent)', color: 'var(--accent-ink)' }}
                                      >
                                        <Edit3 size={13} /> Edit Strategy
                                      </button>
                                      <NavLink
                                        to="/quantgen/dashboard"
                                        style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 16px', borderRadius: '8px', fontSize: '12px', fontWeight: 600, textDecoration: 'none', backgroundColor: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--foreground)' }}
                                      >
                                        View Results <ArrowRight size={13} />
                                      </NavLink>
                                    </div>
                                  </div>
                                </motion.div>
                              )}
                            </AnimatePresence>
                          </div>
                        </motion.div>
                      );
                    })
                  )}
                </AnimatePresence>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
