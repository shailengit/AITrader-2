import { useState, useEffect, useRef } from 'react';
import { request } from '@/lib/api';
import { Search, Plus, ChevronDown, ChevronRight } from 'lucide-react';
import { idFromCatalog, formatOverlayLabel } from '../../../../data/indicatorMap';

interface CatalogIndicator {
  name: string;
  source: string;
  category: string;
  description: string;
  params: Array<{ name: string; type: string; default: number | string; min?: number; max?: number; description?: string }>;
}

interface IndicatorPickerPanelProps {
  onAdd: (descriptor: { id: string; label: string; params?: Record<string, number> }) => void;
  alreadyAdded: string[];
}

const CATEGORY_CHIPS = ['all', 'momentum', 'trend', 'volatility', 'volume'];

/**
 * Catalog-driven indicator picker. Pulls the full indicator catalog from
 * /api/indicators/catalog and lets the user search, filter by category,
 * and add an overlay with custom params.
 *
 * Each indicator card collapses to show its description + per-param input
 * fields. The "Add overlay" button computes the unique id and label
 * (via indicatorMap helpers) and passes them to the parent.
 */
export default function IndicatorPickerPanel({ onAdd, alreadyAdded }: IndicatorPickerPanelProps) {
  const [indicators, setIndicators] = useState<CatalogIndicator[]>([]);
  const [filtered, setFiltered] = useState<CatalogIndicator[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  // Per-indicator param overrides, keyed by indicator name.
  const [paramValues, setParamValues] = useState<Record<string, Record<string, number>>>({});
  // Ref to the "Add overlay" action row of the currently-expanded card.
  // Used to scroll the button into view after expanding — without this,
  // indicators with long descriptions + many params (e.g. Ichimoku
  // Cloud) push the button below the nested scroll viewport and the
  // user can't reach it.
  const actionRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (expandedIdx != null && actionRef.current) {
      actionRef.current.scrollIntoView({ block: 'nearest' });
    }
  }, [expandedIdx]);

  useEffect(() => {
    request<{ success?: boolean; data?: { indicators?: CatalogIndicator[] } }>('/indicators/catalog')
      .then((data) => {
        if (data.success && data.data?.indicators) {
          setIndicators(data.data.indicators);
          setFiltered(data.data.indicators);
        }
      })
      .catch(() => {})
      .finally(() => setIsLoaded(true));
  }, []);

  useEffect(() => {
    let result = indicators;
    if (activeCategory !== 'all') {
      result = result.filter((i) => i.category === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (i) => i.name.toLowerCase().includes(q) || i.description.toLowerCase().includes(q),
      );
    }
    setFiltered(result);
    setExpandedIdx(null);
  }, [searchQuery, activeCategory, indicators]);

  if (!isLoaded) {
    return <div style={{ padding: 12, color: 'var(--muted)', fontSize: 12 }}>Loading indicators...</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div style={{ position: 'relative', marginBottom: 8 }}>
        <Search
          size={12}
          style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--subtle)' }}
        />
        <input
          type="text"
          placeholder="Search..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            width: '100%',
            padding: '6px 8px 6px 26px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            backgroundColor: 'var(--canvas)',
            color: 'var(--foreground)',
            fontSize: 12,
            outline: 'none',
          }}
        />
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
        {CATEGORY_CHIPS.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            style={{
              padding: '2px 8px',
              borderRadius: 999,
              fontSize: 10,
              fontWeight: 600,
              border: 'none',
              cursor: 'pointer',
              backgroundColor: activeCategory === cat ? 'var(--accent)' : 'var(--surface)',
              color: activeCategory === cat ? 'var(--accent-ink)' : 'var(--subtle)',
              textTransform: 'capitalize',
            }}
          >
            {cat === 'all' ? 'All' : cat}
          </button>
        ))}
      </div>
      <div style={{ fontSize: 10, color: 'var(--subtle)', marginBottom: 6 }}>
        {filtered.length} indicator{filtered.length !== 1 ? 's' : ''}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {filtered.map((ind, idx) => {
          const isExpanded = expandedIdx === idx;
          const values = paramValues[ind.name] ?? {};
          // Resolve each param to its current value (edited override or
          // catalog default). Coerce string defaults to numbers for
          // consistent type in the id codec.
          const effectiveValues: Record<string, number> = {};
          for (const p of ind.params) {
            const raw = values[p.name] ?? p.default;
            effectiveValues[p.name] = typeof raw === 'number' ? raw : Number(raw);
          }
          const id = idFromCatalog(ind.name, effectiveValues);
          const label = formatOverlayLabel(ind.name, effectiveValues);
          const alreadyAddedThis = alreadyAdded.includes(id);
          return (
            <div
              key={`${ind.name}-${idx}`}
              style={{
                borderRadius: 6,
                border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--border)'}`,
                overflow: 'hidden',
              }}
            >
              <div
                onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '6px 8px',
                  cursor: 'pointer',
                  backgroundColor: 'var(--surface)',
                }}
              >
                {isExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                <span style={{ flex: 1, fontSize: 11, fontWeight: 600, color: 'var(--foreground)' }}>{ind.name}</span>
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 600,
                    color: 'var(--muted)',
                    padding: '1px 4px',
                    borderRadius: 3,
                    backgroundColor: 'var(--canvas)',
                  }}
                >
                  {ind.source}
                </span>
              </div>
              {isExpanded && (
                <div style={{ padding: '6px 8px 8px', backgroundColor: 'var(--canvas)' }}>
                  <p
                    style={{
                      fontSize: 10,
                      color: 'var(--muted)',
                      margin: '0 0 6px',
                      lineHeight: 1.4,
                      // Cap the description height so a very long
                      // description (e.g. Ichimoku Cloud) scrolls inside
                      // its own box instead of pushing the params +
                      // "Add overlay" button below the picker's nested
                      // scroll viewport. Keeps the action reachable.
                      maxHeight: 72,
                      overflowY: 'auto',
                    }}
                  >
                    {ind.description}
                  </p>
                  {ind.params.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      {ind.params.map((p) => (
                        <div key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, marginBottom: 2 }}>
                          <span style={{ color: 'var(--muted)', flex: 1 }}>{p.name}</span>
                          <input
                            type="number"
                            value={values[p.name] ?? (typeof p.default === 'number' ? p.default : Number(p.default))}
                            min={p.min}
                            max={p.max}
                            onChange={(e) => {
                              const v = parseFloat(e.target.value);
                              if (Number.isFinite(v)) {
                                setParamValues((prev) => ({
                                  ...prev,
                                  [ind.name]: { ...(prev[ind.name] ?? {}), [p.name]: v },
                                }));
                              }
                            }}
                            style={{
                              width: 60,
                              padding: '2px 4px',
                              borderRadius: 3,
                              border: '1px solid var(--border)',
                              backgroundColor: 'var(--surface)',
                              color: 'var(--foreground)',
                              fontSize: 10,
                              outline: 'none',
                            }}
                          />
                          {p.min != null && p.max != null && (
                            <span style={{ color: 'var(--subtle)', fontSize: 9 }}>[{p.min}-{p.max}]</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <div ref={actionRef}>
                    <button
                      onClick={() => onAdd({ id, label, params: effectiveValues })}
                      disabled={alreadyAddedThis}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        padding: '3px 8px',
                        borderRadius: 4,
                        fontSize: 10,
                        fontWeight: 600,
                        border: 'none',
                        cursor: alreadyAddedThis ? 'default' : 'pointer',
                        backgroundColor: alreadyAddedThis ? 'var(--border)' : 'var(--accent)',
                        color: alreadyAddedThis ? 'var(--muted)' : 'var(--accent-ink)',
                      }}
                    >
                      <Plus size={9} />
                      {alreadyAddedThis ? 'Added' : 'Add overlay'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 16, color: 'var(--muted)', fontSize: 11 }}>
            No indicators match.
          </div>
        )}
      </div>
    </div>
  );
}
