import { useState, useMemo } from 'react';
import { Search, X, ChevronDown, ChevronRight, Lock } from 'lucide-react';
import {
  FILTER_CATALOG,
  FILTER_CATEGORIES,
  type FilterSpec,
} from '../../../data/filterCatalog';

interface FilterPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (filterKey: string) => void;
  customFilters?: FilterSpec[];
}

export default function FilterPicker({ open, onOpenChange, onSelect, customFilters }: FilterPickerProps) {
  const [search, setSearch] = useState('');
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    () => new Set(FILTER_CATEGORIES.map((c) => c.id)),
  );

  const colors = {
    bg: 'var(--surface-overlay)',
    overlay: 'rgba(0,0,0,0.5)',
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    subtle: 'var(--subtle)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    hoverBg: 'var(--surface-raised)',
    inputBg: 'var(--canvas)',
    disabled: 'var(--disabled)',
    disabledText: 'var(--disabled)',
  };

  const allFilters = useMemo(() => {
    const base = [...FILTER_CATALOG];
    if (customFilters) {
      // Deduplicate by key — custom filters override built-in ones
      const existingKeys = new Set(base.map((f) => f.key));
      for (const cf of customFilters) {
        if (!existingKeys.has(cf.key)) {
          base.push(cf);
        }
      }
    }
    return base;
  }, [customFilters]);

  const filteredCategories = useMemo(() => {
    if (!search.trim()) {
      return FILTER_CATEGORIES.map((cat) => ({
        ...cat,
        filters: allFilters.filter((f) => f.category === cat.id),
      })).filter((cat) => cat.filters.length > 0);
    }

    const q = search.toLowerCase();
    return FILTER_CATEGORIES.map((cat) => ({
      ...cat,
      filters: allFilters.filter(
        (f) =>
          f.category === cat.id &&
          (f.label.toLowerCase().includes(q) ||
            f.description.toLowerCase().includes(q) ||
            f.key.toLowerCase().includes(q)),
      ),
    })).filter((cat) => cat.filters.length > 0);
  }, [search, allFilters]);

  const toggleCategory = (id: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  if (!open) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {/* Overlay */}
      <div
        style={{ position: 'absolute', inset: 0, backgroundColor: colors.overlay }}
        onClick={() => onOpenChange(false)}
      />

      {/* Dialog */}
      <div
        style={{
          position: 'relative',
          width: 480,
          maxHeight: '70vh',
          backgroundColor: colors.bg,
          borderRadius: 16,
          border: `1px solid ${colors.border}`,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 25px 50px rgba(0,0,0,0.3)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: `1px solid ${colors.border}`,
          }}
        >
          <span style={{ fontSize: 17, fontWeight: 600, color: colors.text }}>
            Add Filter
          </span>
          <button
            onClick={() => onOpenChange(false)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: colors.subtle,
              padding: 4,
              display: 'flex',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: '12px 20px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 12px',
              borderRadius: 8,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.inputBg,
            }}
          >
            <Search size={16} color={colors.subtle} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search filters..."
              autoFocus
              style={{
                flex: 1,
                background: 'none',
                border: 'none',
                outline: 'none',
                color: colors.text,
                fontSize: 14,
              }}
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: colors.subtle,
                  padding: 0,
                  display: 'flex',
                }}
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Filter list */}
        <div style={{ flex: 1, overflow: 'auto', padding: '0 20px 16px' }}>
          {filteredCategories.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: '32px 16px',
                color: colors.muted,
                fontSize: 14,
              }}
            >
              No filters match "{search}"
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {filteredCategories.map((cat) => (
                <div key={cat.id}>
                  {/* Category header */}
                  <button
                    onClick={() => toggleCategory(cat.id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      width: '100%',
                      padding: '10px 12px',
                      borderRadius: 8,
                      border: 'none',
                      background: 'none',
                      cursor: 'pointer',
                      color: colors.text,
                      fontSize: 13,
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = colors.hoverBg;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = 'transparent';
                    }}
                  >
                    {expandedCategories.has(cat.id) ? (
                      <ChevronDown size={14} color={colors.subtle} />
                    ) : (
                      <ChevronRight size={14} color={colors.subtle} />
                    )}
                    {cat.label}
                    <span
                      style={{
                        fontSize: 11,
                        color: colors.subtle,
                        marginLeft: 4,
                      }}
                    >
                      ({cat.filters.length})
                    </span>
                  </button>

                  {/* Filter items */}
                  {expandedCategories.has(cat.id) && (
                    <div style={{ paddingLeft: 8 }}>
                      {cat.filters.map((filter) => (
                        <FilterItem
                          key={filter.key}
                          filter={filter}
                          colors={colors}
                          onSelect={(key) => {
                            onSelect(key);
                            onOpenChange(false);
                          }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Individual filter item ────────────────────────────────

function FilterItem({
  filter,
  colors,
  onSelect,
}: {
  filter: FilterSpec;
  colors: Record<string, string>;
  onSelect: (key: string) => void;
}) {
  const isDisabled = filter.comingSoon;

  return (
    <button
      onClick={() => !isDisabled && onSelect(filter.key)}
      disabled={isDisabled}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        width: '100%',
        padding: '10px 12px',
        borderRadius: 8,
        border: 'none',
        background: 'none',
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        textAlign: 'left',
        opacity: isDisabled ? 0.4 : 1,
      }}
      onMouseEnter={(e) => {
        if (!isDisabled) e.currentTarget.style.backgroundColor = colors.hoverBg;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent';
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginBottom: 2,
          }}
        >
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: isDisabled ? colors.disabledText : colors.text,
            }}
          >
            {filter.label}
          </span>
          {isDisabled && (
            <Lock size={12} color={colors.disabledText} />
          )}
          {filter.unit && (
            <span
              style={{
                fontSize: 11,
                color: colors.subtle,
                padding: '1px 6px',
                borderRadius: 4,
                border: `1px solid ${colors.border}`,
              }}
            >
              {filter.unit}
            </span>
          )}
        </div>
        <span
          style={{
            fontSize: 12,
            color: isDisabled ? colors.disabledText : colors.muted,
            lineHeight: 1.4,
            display: 'block',
          }}
        >
          {filter.description}
        </span>
      </div>
      {isDisabled && (
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: colors.disabledText,
            whiteSpace: 'nowrap',
            padding: '2px 6px',
            borderRadius: 4,
            border: `1px solid ${colors.border}`,
          }}
        >
          Soon
        </span>
      )}
    </button>
  );
}
