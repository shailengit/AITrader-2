import { Sparkles } from 'lucide-react';
import {
  SCREENER_TEMPLATES,
  type ScreenTemplate,
  type FilterGroup,
} from '../../../data/screenerTemplates';

interface TemplateChipsProps {
  onLoad: (template: ScreenTemplate) => void;
  /** Current active filter group — used to detect "selected" state. */
  activeFilters: FilterGroup;
}

export default function TemplateChips({ onLoad, activeFilters }: TemplateChipsProps) {
  const colors = {
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    accent: 'var(--accent)',
  };

  // A template is "active" if its condition count and filterKey multiset
  // match the active filters. Loose equality — a user who edited the template
  // is still "on" it.
  const activeKey = activeFilters.conditions
    .map((c) => `${c.filterKey}:${c.operator}:${JSON.stringify(c.value ?? null)}`)
    .sort()
    .join('|');
  const isActive = (tpl: ScreenTemplate): boolean => {
    const tplKey = tpl.filters.conditions
      .map((c) => `${c.filterKey}:${c.operator}:${JSON.stringify(c.value ?? null)}`)
      .sort()
      .join('|');
    return tplKey === activeKey;
  };

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8,
        marginBottom: 16,
        padding: '12px 16px',
        borderRadius: 12,
        border: `1px solid ${colors.border}`,
        backgroundColor: colors.surface,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 11,
          fontWeight: 600,
          color: colors.muted,
          letterSpacing: '0.05em',
          textTransform: 'uppercase',
          marginRight: 4,
        }}
      >
        <Sparkles size={12} />
        Quick start
      </div>
      {SCREENER_TEMPLATES.map((tpl) => {
        const active = isActive(tpl);
        return (
          <button
            key={tpl.id}
            onClick={() => onLoad(tpl)}
            title={tpl.description}
            style={{
              fontSize: 12,
              fontWeight: 600,
              padding: '6px 12px',
              borderRadius: 999,
              border: `1px solid ${active ? colors.accent : colors.border}`,
              backgroundColor: active ? 'var(--accent-glow)' : 'transparent',
              color: active ? colors.accent : colors.text,
              cursor: 'pointer',
              transition: 'all 150ms ease',
            }}
            onMouseEnter={(e) => {
              if (!active) {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
              }
            }}
            onMouseLeave={(e) => {
              if (!active) {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.text;
              }
            }}
          >
            {tpl.name}
          </button>
        );
      })}
    </div>
  );
}
