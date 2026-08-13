export type RangeMode = '1y' | '2y' | '3y' | '5y' | 'max' | 'custom';

interface DateRangeBarProps {
  mode: RangeMode;
  customStart: string;
  customEnd: string;
  onChange: (mode: RangeMode, custom?: { start?: string; end?: string }) => void;
  colors: Record<string, string>;
}

const PILLS: Array<{ key: RangeMode; label: string }> = [
  { key: '1y', label: '1Y' },
  { key: '2y', label: '2Y' },
  { key: '3y', label: '3Y' },
  { key: '5y', label: '5Y' },
  { key: 'max', label: 'Max' },
  { key: 'custom', label: 'Custom' },
];

/**
 * Pill-button bar for the chart's date range. Selecting "Custom" reveals
 * two date inputs below the pills; the parent owns the values.
 */
export default function DateRangeBar({ mode, customStart, customEnd, onChange, colors }: DateRangeBarProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: colors.muted,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          marginRight: 4,
        }}
      >
        Range
      </span>
      {PILLS.map((p) => {
        const active = p.key === mode;
        return (
          <button
            key={p.key}
            onClick={() => onChange(p.key, { start: customStart, end: customEnd })}
            style={{
              padding: '6px 14px',
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              border: `1px solid ${active ? colors.accent : colors.border}`,
              backgroundColor: active ? 'var(--accent-glow)' : 'transparent',
              color: active ? colors.accent : colors.muted,
              cursor: 'pointer',
            }}
          >
            {p.label}
          </button>
        );
      })}
      {mode === 'custom' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 8 }}>
          <input
            type="date"
            value={customStart}
            max={customEnd || undefined}
            onChange={(e) => onChange('custom', { start: e.target.value, end: customEnd })}
            style={{
              padding: '5px 8px',
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.surface,
              color: colors.text,
              fontSize: 12,
              outline: 'none',
            }}
          />
          <span style={{ color: colors.muted, fontSize: 12 }}>→</span>
          <input
            type="date"
            value={customEnd}
            min={customStart || undefined}
            onChange={(e) => onChange('custom', { start: customStart, end: e.target.value })}
            style={{
              padding: '5px 8px',
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.surface,
              color: colors.text,
              fontSize: 12,
              outline: 'none',
            }}
          />
        </div>
      )}
    </div>
  );
}
