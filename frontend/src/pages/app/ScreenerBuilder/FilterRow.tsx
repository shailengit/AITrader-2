import { useState } from 'react';
import { X, ArrowLeftRight, Settings } from 'lucide-react';
import { useTheme } from '../../../context/ThemeContext';
import { getFilterByKey, FILTER_CATALOG, getDynamicLabel } from '../../../data/filterCatalog';
import type { FilterCondition } from '../../../hooks/useScreens';
import FilterPicker from './FilterPicker';

// Friendly labels for indicator parameter names
const PARAM_LABELS: Record<string, string> = {
  window: 'Period',
  window_dev: 'Dev',
  window_fast: 'Fast',
  window_slow: 'Slow',
  window_sign: 'Signal',
  smooth_window: 'Smooth',
  lbp: 'Lookback',
  pow1: 'Pow 1',
  pow2: 'Pow 2',
};

interface FilterRowProps {
  condition: FilterCondition;
  index: number;
  total: number;
  groupMatch: 'all' | 'any';
  onChange: (condition: FilterCondition) => void;
  onRemove: () => void;
  onGroupMatchChange: (match: 'all' | 'any') => void;
}

const NUMBER_OPERATORS = [
  { value: 'gte', label: '≥' },
  { value: 'gt', label: '>' },
  { value: 'lte', label: '≤' },
  { value: 'lt', label: '<' },
  { value: 'eq', label: '=' },
  { value: 'neq', label: '≠' },
];

const CROSS_OPERATORS = [
  { value: 'crossed_above', label: 'Crossed above' },
  { value: 'crossed_below', label: 'Crossed below' },
];

const LOOKBACK_OPTIONS = [1, 2, 3, 5, 10, 20];

export default function FilterRow({
  condition,
  index,
  total,
  groupMatch,
  onChange,
  onRemove,
  onGroupMatchChange,
}: FilterRowProps) {
  const { isDarkMode } = useTheme();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [showParams, setShowParams] = useState(false);
  const [showRefParams, setShowRefParams] = useState(false);

  const filterSpec = getFilterByKey(condition.filterKey);
  const refFilterSpec = condition.referenceFilterKey ? getFilterByKey(condition.referenceFilterKey) : undefined;

  const colors = {
    text: isDarkMode ? '#FAFAFA' : '#1d1d1f',
    muted: isDarkMode ? 'rgba(255,255,255,0.48)' : 'rgba(0,0,0,0.48)',
    subtle: isDarkMode ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)',
    border: isDarkMode ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
    surface: isDarkMode ? '#272729' : '#f5f5f7',
    inputBg: isDarkMode ? '#000000' : '#ffffff',
    hoverBg: isDarkMode ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
    accent: '#10B981',
    danger: '#EF4444',
  };

  const handleFilterSelect = (filterKey: string) => {
    const spec = getFilterByKey(filterKey);
    if (!spec) return;
    const hasOptions = spec.type === 'categorical' && (spec.options?.length ?? 0) > 0;
    onChange({
      ...condition,
      filterKey,
      operator:
        spec.type === 'number' ? 'gte'
          : spec.type === 'cross' ? 'crossed_above'
          : hasOptions ? 'eq'
          : 'is_true',
      value:
        spec.type === 'number' ? 0
          : spec.type === 'boolean' ? true
          : hasOptions ? spec.options![0].value
          : null,
      referenceFilterKey: undefined,
      lookbackDays: undefined,
      compareToIndicator: false,
    });
  };

  const isCrossoverOp = condition.operator === 'crossed_above' || condition.operator === 'crossed_below';
  const isIndicatorMode = condition.compareToIndicator === true;

  const renderValueControl = () => {
    if (!filterSpec) return null;

    // ── Crossover mode (Crossed Above / Crossed Below) ──────────────
    if (isCrossoverOp) {
      return (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            value={condition.referenceFilterKey || ''}
            onChange={(e) =>
              onChange({ ...condition, referenceFilterKey: e.target.value || undefined, referenceParams: undefined })
            }
            style={{ ...selectStyle(colors), minWidth: 120 }}
          >
            <option value="">Select reference...</option>
            {FILTER_CATALOG.filter((f) => {
              // Allow same-key reference IF the filter is tunable — the user
              // can then set different `params` on the reference to compute
              // a different window of the same indicator (e.g. EMA 20
              // crossed above EMA 200, both rooted at the `ema_20` filter).
              // Non-tunable filters must still differ from the primary.
              if (f.type !== 'number') return false;
              if (f.key === condition.filterKey) return f.tunable === true;
              return true;
            }).map((f) => {
              const isSelected = f.key === condition.referenceFilterKey;
              const label = isSelected && condition.referenceParams
                ? getDynamicLabel(f, condition.referenceParams)
                : f.label;
              return (
                <option key={f.key} value={f.key}>
                  {label}
                </option>
              );
            })}
          </select>

          {/* Gear icon for reference indicator params */}
          {refFilterSpec && refFilterSpec.tunable && refFilterSpec.defaultParams && (
            <button
              onClick={() => setShowRefParams(!showRefParams)}
              title="Adjust reference indicator parameters"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 28,
                height: 28,
                borderRadius: 6,
                border: `1px solid ${showRefParams ? colors.accent : colors.border}`,
                backgroundColor: showRefParams ? 'rgba(16,185,129,0.1)' : 'transparent',
                color: showRefParams ? colors.accent : colors.subtle,
                cursor: 'pointer',
                flexShrink: 0,
                transition: 'all 150ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
              }}
              onMouseLeave={(e) => {
                if (!showRefParams) {
                  e.currentTarget.style.borderColor = colors.border;
                  e.currentTarget.style.color = colors.subtle;
                }
              }}
            >
              <Settings size={14} />
            </button>
          )}

          <select
            value={condition.lookbackDays ?? 5}
            onChange={(e) =>
              onChange({ ...condition, lookbackDays: parseInt(e.target.value, 10) })
            }
            style={selectStyle(colors)}
          >
            {LOOKBACK_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {d} {d === 1 ? 'day' : 'days'}
              </option>
            ))}
          </select>
        </div>
      );
    }

    // ── Indicator comparison mode (e.g. SMA20 > SMA200) ──────────
    if (isIndicatorMode) {
      return (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            value={condition.referenceFilterKey || ''}
            onChange={(e) =>
              onChange({ ...condition, referenceFilterKey: e.target.value || undefined, referenceParams: undefined })
            }
            style={{ ...selectStyle(colors), minWidth: 120 }}
          >
            <option value="">Select indicator...</option>
            {FILTER_CATALOG.filter((f) => {
              // See crossover block above — same-key reference is allowed
              // only for tunable filters so the user can pick e.g. EMA 20
              // vs EMA 200 rooted at `ema_20` with different `params`.
              if (f.type !== 'number') return false;
              if (f.key === condition.filterKey) return f.tunable === true;
              return true;
            }).map((f) => {
              const isSelected = f.key === condition.referenceFilterKey;
              const label = isSelected && condition.referenceParams
                ? getDynamicLabel(f, condition.referenceParams)
                : f.label;
              return (
                <option key={f.key} value={f.key}>
                  {label}
                </option>
              );
            })}
          </select>

          {/* Gear icon for reference indicator params */}
          {refFilterSpec && refFilterSpec.tunable && refFilterSpec.defaultParams && (
            <button
              onClick={() => setShowRefParams(!showRefParams)}
              title="Adjust reference indicator parameters"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 28,
                height: 28,
                borderRadius: 6,
                border: `1px solid ${showRefParams ? colors.accent : colors.border}`,
                backgroundColor: showRefParams ? 'rgba(16,185,129,0.1)' : 'transparent',
                color: showRefParams ? colors.accent : colors.subtle,
                cursor: 'pointer',
                flexShrink: 0,
                transition: 'all 150ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
              }}
              onMouseLeave={(e) => {
                if (!showRefParams) {
                  e.currentTarget.style.borderColor = colors.border;
                  e.currentTarget.style.color = colors.subtle;
                }
              }}
            >
              <Settings size={14} />
            </button>
          )}

          <button
            onClick={() =>
              onChange({ ...condition, compareToIndicator: false, referenceFilterKey: undefined })
            }
            title="Switch to value comparison"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '4px 8px',
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              backgroundColor: 'rgba(16,185,129,0.08)',
              color: colors.accent,
              fontSize: 11,
              fontWeight: 600,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            <ArrowLeftRight size={12} />
            vs Value
          </button>
        </div>
      );
    }

    // ── Regular value comparison mode ──────────────────────────────
    switch (filterSpec.type) {
      case 'number':
        return (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="number"
              value={String(condition.value ?? '')}
              onChange={(e) =>
                onChange({
                  ...condition,
                  value: e.target.value ? parseFloat(e.target.value) : null,
                })
              }
              placeholder="0"
              style={{
                ...inputStyle(colors),
                width: 100,
              }}
            />
            {filterSpec.unit && (
              <span style={{ fontSize: 12, color: colors.muted, whiteSpace: 'nowrap' }}>
                {filterSpec.unit}
              </span>
            )}
            <button
              onClick={() =>
                onChange({
                  ...condition,
                  compareToIndicator: true,
                  value: null,
                  referenceFilterKey: undefined,
                })
              }
              title="Compare against another indicator"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                padding: '4px 8px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: 'transparent',
                color: colors.subtle,
                fontSize: 11,
                fontWeight: 500,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all 150ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
                e.currentTarget.style.backgroundColor = 'rgba(16,185,129,0.05)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.subtle;
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              <ArrowLeftRight size={12} />
              vs Indicator
            </button>
          </div>
        );

      case 'cross':
        return (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <select
              value={condition.referenceFilterKey || ''}
              onChange={(e) =>
                onChange({ ...condition, referenceFilterKey: e.target.value || undefined })
              }
              style={{ ...selectStyle(colors), minWidth: 120 }}
            >
              <option value="">Select reference...</option>
              {FILTER_CATALOG.filter(
                (f) => f.key !== condition.filterKey && f.type === 'number',
              ).map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>
            <select
              value={condition.lookbackDays ?? 5}
              onChange={(e) =>
                onChange({ ...condition, lookbackDays: parseInt(e.target.value, 10) })
              }
              style={selectStyle(colors)}
            >
              {LOOKBACK_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d} {d === 1 ? 'day' : 'days'}
                </option>
              ))}
            </select>
          </div>
        );

      case 'boolean':
        return (
          <button
            onClick={() =>
              onChange({
                ...condition,
                operator: condition.operator === 'is_true' ? 'is_false' : 'is_true',
                value: condition.operator !== 'is_true',
              })
            }
            style={{
              padding: '6px 16px',
              borderRadius: 8,
              border: `1px solid ${colors.border}`,
              backgroundColor:
                condition.operator === 'is_true' ? 'rgba(16,185,129,0.15)' : colors.inputBg,
              color: condition.operator === 'is_true' ? colors.accent : colors.muted,
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 150ms ease',
            }}
          >
            {condition.operator === 'is_true' ? 'Yes' : 'No'}
          </button>
        );

      case 'categorical':
        // Categorical filters that declare fixed `options` (e.g. Sector Regime
        // BULL/BEAR) render a dropdown storing the selection in condition.value.
        // Filters without options (e.g. legacy `sector`) fall back to the text
        // placeholder — they have no value-editing UI.
        if (filterSpec.options && filterSpec.options.length > 0) {
          return (
            <select
              value={String(condition.value ?? filterSpec.options[0].value)}
              onChange={(e) => onChange({ ...condition, value: e.target.value })}
              style={selectStyle(colors)}
            >
              {filterSpec.options.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          );
        }
        return (
          <span style={{ fontSize: 12, color: colors.muted, fontStyle: 'italic' }}>
            Categorical filter
          </span>
        );

      default:
        return null;
    }
  };

  // Determine which operators to show in the dropdown
  const availableOperators = (() => {
    if (!filterSpec) return [];
    let ops: { value: string; label: string }[];
    if (filterSpec.type === 'number') {
      if (isIndicatorMode) {
        // In indicator mode, show comparison operators (no ≠) + crossover
        ops = [...NUMBER_OPERATORS.filter((op) => op.value !== 'neq'), ...CROSS_OPERATORS];
      } else {
        // In value mode, show all number operators + crossover
        ops = [...NUMBER_OPERATORS, ...CROSS_OPERATORS];
      }
    } else if (filterSpec.type === 'cross') {
      ops = [...CROSS_OPERATORS];
    } else {
      ops = filterSpec.operators.map((op) => ({ value: op.operator, label: op.label }));
    }
    // Ensure the saved operator is always present so React's controlled <select>
    // doesn't silently fall back to the first option (e.g. showing ≥ when the
    // saved data has crossed_above but a stale render omitted it).
    if (condition.operator && !ops.some((op) => op.value === condition.operator)) {
      const labels: Record<string, string> = {
        crossed_above: 'Crossed above',
        crossed_below: 'Crossed below',
        gte: '≥',
        gt: '>',
        lte: '≤',
        lt: '<',
        eq: '=',
        neq: '≠',
      };
      ops = [...ops, { value: condition.operator, label: labels[condition.operator] ?? condition.operator }];
    }
    return ops;
  })();

  return (
    <>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          borderRadius: 10,
          border: `1px solid ${colors.border}`,
          backgroundColor: colors.surface,
        }}
      >
        {/* Filter picker button */}
        <button
          onClick={() => setPickerOpen(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 12px',
            borderRadius: 6,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.inputBg,
            color: filterSpec ? colors.text : colors.muted,
            fontSize: 13,
            fontWeight: 500,
            cursor: 'pointer',
            minWidth: 120,
            whiteSpace: 'nowrap',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = colors.accent;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = colors.border;
          }}
        >
          {filterSpec ? getDynamicLabel(filterSpec, condition.params) : 'Select filter...'}
        </button>

        {/* Gear icon for tunable params */}
        {filterSpec && filterSpec.tunable && filterSpec.defaultParams && (
          <button
            onClick={() => setShowParams(!showParams)}
            title="Adjust indicator parameters"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 28,
              height: 28,
              borderRadius: 6,
              border: `1px solid ${showParams ? colors.accent : colors.border}`,
              backgroundColor: showParams ? 'rgba(16,185,129,0.1)' : 'transparent',
              color: showParams ? colors.accent : colors.subtle,
              cursor: 'pointer',
              flexShrink: 0,
              transition: 'all 150ms ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = colors.accent;
              e.currentTarget.style.color = colors.accent;
            }}
            onMouseLeave={(e) => {
              if (!showParams) {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.subtle;
              }
            }}
          >
            <Settings size={14} />
          </button>
        )}

        {/* Operator dropdown */}
        {filterSpec && availableOperators.length > 0 && (
          <select
            value={condition.operator}
            onChange={(e) => {
              const newOp = e.target.value;
              const isNowCrossover = newOp === 'crossed_above' || newOp === 'crossed_below';
              const wasCrossover = isCrossoverOp;
              // If switching to/from crossover, reset reference/lookback
              if (isNowCrossover && !wasCrossover) {
                onChange({
                  ...condition,
                  operator: newOp,
                  value: null,
                  referenceFilterKey: undefined,
                  lookbackDays: 5,
                  compareToIndicator: false,
                });
              } else if (!isNowCrossover && wasCrossover) {
                onChange({
                  ...condition,
                  operator: newOp,
                  value: 0,
                  referenceFilterKey: undefined,
                  lookbackDays: undefined,
                });
              } else {
                onChange({ ...condition, operator: newOp });
              }
            }}
            style={{
              ...selectStyle(colors),
              minWidth: isCrossoverOp ? 120 : 60,
              textAlign: 'center',
            }}
          >
            {availableOperators.map((op) => (
              <option key={op.value} value={op.value}>
                {op.label}
              </option>
            ))}
          </select>
        )}

        {/* Value control */}
        {filterSpec && renderValueControl()}

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Connector dropdown (not on last row) */}
        {index < total - 1 && (
          <select
            value={groupMatch}
            onChange={(e) => onGroupMatchChange(e.target.value as 'all' | 'any')}
            style={{
              ...selectStyle(colors),
              minWidth: 60,
              textAlign: 'center',
              fontWeight: 600,
              color: colors.accent,
            }}
          >
            <option value="all">AND</option>
            <option value="any">OR</option>
          </select>
        )}

        {/* Remove button */}
        <button
          onClick={onRemove}
          title="Remove filter"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 28,
            height: 28,
            borderRadius: 6,
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            color: colors.subtle,
            flexShrink: 0,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)';
            e.currentTarget.style.color = colors.danger;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
            e.currentTarget.style.color = colors.subtle;
          }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Expandable params section */}
      {filterSpec && filterSpec.tunable && filterSpec.defaultParams && showParams && (
        <div
          style={{
            display: 'flex',
            gap: 8,
            padding: '8px 12px 4px 12px',
            flexWrap: 'wrap',
          }}
        >
          {Object.entries(filterSpec.defaultParams).map(([paramKey, paramValue]) => {
            const currentVal = condition.params?.[paramKey] ?? paramValue;
            return (
              <div key={paramKey} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <label
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: colors.muted,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  {PARAM_LABELS[paramKey] || paramKey}:
                </label>
                <input
                  type="number"
                  value={currentVal}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10);
                    onChange({
                      ...condition,
                      params: { ...(condition.params || {}), [paramKey]: isNaN(val) ? paramValue : val },
                    });
                  }}
                  style={{
                    width: 60,
                    padding: '4px 6px',
                    borderRadius: 4,
                    border: `1px solid ${colors.border}`,
                    backgroundColor: colors.inputBg,
                    color: colors.text,
                    fontSize: 12,
                    outline: 'none',
                  }}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* Expandable params section for reference indicator */}
      {(isIndicatorMode || isCrossoverOp) && refFilterSpec && refFilterSpec.tunable && refFilterSpec.defaultParams && showRefParams && (
        <div
          style={{
            display: 'flex',
            gap: 8,
            padding: '4px 12px 8px 12px',
            flexWrap: 'wrap',
          }}
        >
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: colors.accent,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              alignSelf: 'center',
            }}
          >
            {getDynamicLabel(refFilterSpec, condition.referenceParams)}:
          </span>
          {Object.entries(refFilterSpec.defaultParams).map(([paramKey, paramValue]) => {
            const currentVal = condition.referenceParams?.[paramKey] ?? paramValue;
            return (
              <div key={paramKey} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <label
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: colors.muted,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  {PARAM_LABELS[paramKey] || paramKey}:
                </label>
                <input
                  type="number"
                  value={currentVal}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10);
                    onChange({
                      ...condition,
                      referenceParams: { ...(condition.referenceParams || {}), [paramKey]: isNaN(val) ? paramValue : val },
                    });
                  }}
                  style={{
                    width: 60,
                    padding: '4px 6px',
                    borderRadius: 4,
                    border: `1px solid ${colors.border}`,
                    backgroundColor: colors.inputBg,
                    color: colors.text,
                    fontSize: 12,
                    outline: 'none',
                  }}
                />
              </div>
            );
          })}
        </div>
      )}

      <FilterPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        onSelect={handleFilterSelect}
      />
    </>
  );
}

// ── Shared style helpers ─────────────────────────────────

function selectStyle(colors: Record<string, string>): React.CSSProperties {
  return {
    padding: '6px 8px',
    borderRadius: 6,
    border: `1px solid ${colors.border}`,
    backgroundColor: colors.inputBg,
    color: colors.text,
    fontSize: 13,
    outline: 'none',
    cursor: 'pointer',
  };
}

function inputStyle(colors: Record<string, string>): React.CSSProperties {
  return {
    padding: '6px 8px',
    borderRadius: 6,
    border: `1px solid ${colors.border}`,
    backgroundColor: colors.inputBg,
    color: colors.text,
    fontSize: 13,
    outline: 'none',
  };
}
