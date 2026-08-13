
interface GroupHeaderProps {
  match: 'all' | 'any';
  onMatchChange: (match: 'all' | 'any') => void;
  conditionCount: number;
}

export default function GroupHeader({ match, onMatchChange, conditionCount }: GroupHeaderProps) {
  const colors = {
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    activeBg: 'var(--accent-glow)',
    activeText: 'var(--accent)',
    inactiveBg: 'var(--surface-raised)',
    inactiveText: 'var(--disabled)',
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 16px',
        borderRadius: '12px',
        border: `1px solid ${colors.border}`,
        backgroundColor: colors.surface,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: colors.text }}>
          Filter Group
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 500,
            color: colors.muted,
            padding: '2px 8px',
            borderRadius: 6,
            border: `1px solid ${colors.border}`,
          }}
        >
          {conditionCount} {conditionCount === 1 ? 'condition' : 'conditions'}
        </span>
      </div>

      <div
        style={{
          display: 'flex',
          borderRadius: 8,
          border: `1px solid ${colors.border}`,
          overflow: 'hidden',
        }}
      >
        <button
          onClick={() => onMatchChange('all')}
          style={{
            padding: '6px 14px',
            fontSize: 13,
            fontWeight: 600,
            border: 'none',
            cursor: 'pointer',
            backgroundColor: match === 'all' ? colors.activeBg : colors.inactiveBg,
            color: match === 'all' ? colors.activeText : colors.inactiveText,
            transition: 'all 150ms ease',
          }}
        >
          Match all
        </button>
        <button
          onClick={() => onMatchChange('any')}
          style={{
            padding: '6px 14px',
            fontSize: 13,
            fontWeight: 600,
            border: 'none',
            cursor: 'pointer',
            backgroundColor: match === 'any' ? colors.activeBg : colors.inactiveBg,
            color: match === 'any' ? colors.activeText : colors.inactiveText,
            transition: 'all 150ms ease',
          }}
        >
          Match any
        </button>
      </div>
    </div>
  );
}
