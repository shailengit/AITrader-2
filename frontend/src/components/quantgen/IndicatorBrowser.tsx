import { useState, useEffect, useCallback } from 'react';
import { quantgen } from '@/lib/api';
import { Search, Plus, ChevronDown, ChevronRight, Code2 } from 'lucide-react';

interface IndicatorParam {
  name: string;
  type: string;
  default: number | string;
  min?: number;
  max?: number;
  description?: string;
}

interface Indicator {
  name: string;
  source: string;
  category: string;
  description: string;
  params: IndicatorParam[];
  code_snippet: string;
  pine_equivalent?: string;
}

interface IndicatorBrowserProps {
  onInsertSnippet: (snippet: string) => void;
}

const SOURCE_BADGE_COLORS: Record<string, string> = {
  ta: 'rgba(59, 130, 246, 0.12)',
  vectorbt: 'rgba(139, 92, 246, 0.12)',
  'pandas-ta': 'rgba(16, 185, 129, 0.12)',
};

const SOURCE_TEXT_COLORS: Record<string, string> = {
  ta: '#3b82f6',
  vectorbt: '#8b5cf6',
  'pandas-ta': '#10b981',
};

const CATEGORY_CHIPS = ['all', 'momentum', 'trend', 'volatility', 'volume'];

export function IndicatorBrowser({ onInsertSnippet }: IndicatorBrowserProps) {
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [filtered, setFiltered] = useState<Indicator[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');
  const [expandedIndices, setExpandedIndices] = useState<Set<number>>(new Set());
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    quantgen.indicatorCatalog()
      .then(data => {
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
      result = result.filter(i => i.category === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        i => i.name.toLowerCase().includes(q) || i.description.toLowerCase().includes(q)
      );
    }
    setFiltered(result);
    setExpandedIndices(new Set());
  }, [searchQuery, activeCategory, indicators]);

  const toggleExpand = (idx: number) => {
    setExpandedIndices(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleInsert = useCallback((snippet: string) => {
    onInsertSnippet(snippet);
  }, [onInsertSnippet]);

  if (!isLoaded) {
    return (
      <div style={{ padding: '16px', color: 'var(--muted)', fontSize: '13px', textAlign: 'center' }}>
        Loading indicators...
      </div>
    );
  }

  return (
    <div>
      {/* Search */}
      <div style={{ position: 'relative', marginBottom: '12px' }}>
        <Search size={13} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--subtle)' }} />
        <input
          type="text"
          placeholder="Search indicators..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            width: '100%',
            padding: '7px 10px 7px 30px',
            borderRadius: '8px',
            border: '1px solid var(--border)',
            backgroundColor: 'var(--canvas)',
            color: 'var(--foreground)',
            fontSize: '12px',
            outline: 'none',
          }}
        />
      </div>

      {/* Category chips */}
      <div style={{ display: 'flex', gap: '6px', marginBottom: '12px', flexWrap: 'wrap' }}>
        {CATEGORY_CHIPS.map(cat => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            style={{
              padding: '4px 10px',
              borderRadius: '999px',
              fontSize: '11px',
              fontWeight: 600,
              border: 'none',
              cursor: 'pointer',
              backgroundColor: activeCategory === cat ? 'var(--accent)' : 'var(--surface)',
              color: activeCategory === cat ? '#000000' : 'var(--subtle)',
              textTransform: 'capitalize',
            }}
          >
            {cat === 'all' ? 'All' : cat}
          </button>
        ))}
      </div>

      {/* Results count */}
      <div style={{ fontSize: '11px', color: 'var(--subtle)', marginBottom: '8px', padding: '0 4px' }}>
        {filtered.length} indicator{filtered.length !== 1 ? 's' : ''}
      </div>

      {/* Indicator list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {filtered.map((indicator, idx) => {
          const isExpanded = expandedIndices.has(idx);
          const sourceColor = SOURCE_BADGE_COLORS[indicator.source] || 'var(--surface)';
          const sourceTextColor = SOURCE_TEXT_COLORS[indicator.source] || 'var(--muted)';

          return (
            <div key={idx} style={{
              borderRadius: '8px',
              border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--border)'}`,
              overflow: 'hidden',
              transition: 'border-color 0.1s',
            }}>
              {/* Header row */}
              <div
                onClick={() => toggleExpand(idx)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '8px 10px',
                  cursor: 'pointer',
                  backgroundColor: 'var(--surface)',
                }}
              >
                {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <span style={{ flex: 1, fontSize: '12px', fontWeight: 600, color: 'var(--foreground)' }}>
                  {indicator.name}
                </span>
                <span style={{
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontWeight: 600,
                  backgroundColor: sourceColor,
                  color: sourceTextColor,
                }}>
                  {indicator.source}
                </span>
              </div>

              {/* Expanded content */}
              {isExpanded && (
                <div style={{
                  padding: '8px 10px 10px',
                  borderTop: '1px solid var(--border)',
                  backgroundColor: 'var(--canvas)',
                }}>
                  <p style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '8px', lineHeight: 1.5 }}>
                    {indicator.description}
                  </p>

                  {indicator.params.length > 0 && (
                    <div style={{ marginBottom: '8px' }}>
                      <div style={{ fontSize: '10px', fontWeight: 600, color: 'var(--subtle)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Parameters
                      </div>
                      {indicator.params.map((p, pi) => (
                        <div key={pi} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', padding: '2px 0', color: 'var(--muted)' }}>
                          <span>{p.name}</span>
                          <span style={{ color: 'var(--subtle)' }}>
                            {p.type}={p.default}
                            {p.min != null && p.max != null ? ` [${p.min}-${p.max}]` : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {indicator.code_snippet && (
                    <div style={{ marginBottom: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '10px', fontWeight: 600, color: 'var(--subtle)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        <Code2 size={10} />
                        Code
                      </div>
                      <pre style={{
                        margin: 0,
                        padding: '8px',
                        borderRadius: '6px',
                        fontSize: '10px',
                        lineHeight: 1.4,
                        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                        backgroundColor: 'var(--surface)',
                        color: 'var(--foreground)',
                        overflowX: 'auto',
                        whiteSpace: 'pre-wrap',
                      }}>
                        {indicator.code_snippet}
                      </pre>
                    </div>
                  )}

                  <button
                    onClick={() => handleInsert(indicator.code_snippet)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '4px 10px',
                      borderRadius: '6px',
                      fontSize: '11px',
                      fontWeight: 600,
                      border: 'none',
                      cursor: 'pointer',
                      backgroundColor: 'var(--accent)',
                      color: '#000000',
                    }}
                  >
                    <Plus size={11} />
                    Insert at Cursor
                  </button>
                </div>
              )}
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: '24px 16px', color: 'var(--muted)', fontSize: '12px' }}>
            No indicators match your search.
          </div>
        )}
      </div>
    </div>
  );
}
