import { useState } from 'react';
import { X, BookTemplate, FolderOpen, Trash2 } from 'lucide-react';
import { SCREENER_TEMPLATES, type ScreenTemplate } from '../../../data/screenerTemplates';
import { useScreens, type ScreenPreset } from '../../../hooks/useScreens';

interface ScreenLibraryModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLoad: (preset: ScreenPreset) => void;
}

type Tab = 'templates' | 'my-screens';

export default function ScreenLibraryModal({
  open,
  onOpenChange,
  onLoad,
}: ScreenLibraryModalProps) {
  const [tab, setTab] = useState<Tab>('templates');
  const { presets, deletePreset } = useScreens();

  const colors = {
    bg: 'var(--surface-overlay)',
    overlay: 'rgba(0,0,0,0.5)',
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    subtle: 'var(--subtle)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    hoverBg: 'var(--surface-raised)',
    accent: 'var(--accent)',
    danger: 'var(--bad)',
    tabActive: 'var(--accent-glow)',
    tabInactive: 'var(--surface-raised)',
  };

  if (!open) return null;

  const handleLoadTemplate = (template: ScreenTemplate) => {
    const now = Date.now();
    const preset: ScreenPreset = {
      schemaVersion: 1,
      id: 'scr_' + Date.now().toString(36) + '_' + Math.random().toString(36).substring(2, 9),
      name: template.name,
      isTemplate: false,
      createdAt: now,
      updatedAt: now,
      filters: template.filters,
      sort: template.sort,
      maxResults: template.maxResults,
      useAi: template.useAi,
      baseWeight: template.baseWeight,
      subWeights: template.subWeights,
      showAlignment: template.showAlignment,
    };
    onLoad(preset);
    onOpenChange(false);
  };

  const handleLoadPreset = (preset: ScreenPreset) => {
    onLoad(preset);
    onOpenChange(false);
  };

  const handleDelete = (id: string) => {
    deletePreset(id);
  };

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
          width: 560,
          maxHeight: '75vh',
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
            Screen Library
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

        {/* Tabs */}
        <div
          style={{
            display: 'flex',
            gap: 4,
            padding: '12px 20px',
            borderBottom: `1px solid ${colors.border}`,
          }}
        >
          <button
            onClick={() => setTab('templates')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 16px',
              borderRadius: 8,
              border: 'none',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 600,
              backgroundColor: tab === 'templates' ? colors.tabActive : colors.tabInactive,
              color: tab === 'templates' ? colors.accent : colors.muted,
              transition: 'all 150ms ease',
            }}
          >
            <BookTemplate size={16} />
            Templates
          </button>
          <button
            onClick={() => setTab('my-screens')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 16px',
              borderRadius: 8,
              border: 'none',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 600,
              backgroundColor: tab === 'my-screens' ? colors.tabActive : colors.tabInactive,
              color: tab === 'my-screens' ? colors.accent : colors.muted,
              transition: 'all 150ms ease',
            }}
          >
            <FolderOpen size={16} />
            My Screens
            {presets.length > 0 && (
              <span
                style={{
                  fontSize: 11,
                  padding: '1px 6px',
                  borderRadius: 8,
                  backgroundColor: colors.tabActive,
                  color: colors.accent,
                }}
              >
                {presets.length}
              </span>
            )}
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
          {tab === 'templates' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {SCREENER_TEMPLATES.map((template) => (
                <TemplateCard
                  key={template.id}
                  template={template}
                  colors={colors}
                  onLoad={() => handleLoadTemplate(template)}
                />
              ))}
            </div>
          ) : (
            <>
              {presets.length === 0 ? (
                <div
                  style={{
                    textAlign: 'center',
                    padding: '48px 16px',
                    color: colors.muted,
                    fontSize: 14,
                  }}
                >
                  <FolderOpen
                    size={32}
                    style={{ margin: '0 auto 12px', display: 'block', opacity: 0.4 }}
                  />
                  No saved screens yet.
                  <br />
                  Save a screen to see it here.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {presets.map((preset) => (
                    <PresetCard
                      key={preset.id}
                      preset={preset}
                      colors={colors}
                      onLoad={() => handleLoadPreset(preset)}
                      onDelete={() => handleDelete(preset.id)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Template Card ─────────────────────────────────────────

function TemplateCard({
  template,
  colors,
  onLoad,
}: {
  template: ScreenTemplate;
  colors: Record<string, string>;
  onLoad: () => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '14px 16px',
        borderRadius: 10,
        border: `1px solid ${colors.border}`,
        backgroundColor: colors.surface,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: colors.text }}>
            {template.name}
          </span>
          <span
            style={{
              fontSize: 11,
              fontWeight: 500,
              padding: '1px 8px',
              borderRadius: 4,
              backgroundColor: 'var(--accent-glow)',
              color: colors.accent,
            }}
          >
            {template.category}
          </span>
        </div>
        <span style={{ fontSize: 12, color: colors.muted, lineHeight: 1.4, display: 'block' }}>
          {template.description}
        </span>
        <span style={{ fontSize: 11, color: colors.subtle, marginTop: 4, display: 'block' }}>
          {template.filters.conditions.length} condition
          {template.filters.conditions.length !== 1 ? 's' : ''}
        </span>
      </div>
      <button
        onClick={onLoad}
        style={{
          padding: '8px 16px',
          borderRadius: 8,
          border: 'none',
          backgroundColor: colors.accent,
          color: 'var(--accent-ink)',
          fontSize: 13,
          fontWeight: 600,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
          transition: 'opacity 150ms ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.opacity = '0.9';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.opacity = '1';
        }}
      >
        Load
      </button>
    </div>
  );
}

// ── Preset Card ──────────────────────────────────────────

function PresetCard({
  preset,
  colors,
  onLoad,
  onDelete,
}: {
  preset: ScreenPreset;
  colors: Record<string, string>;
  onLoad: () => void;
  onDelete: () => void;
}) {
  const lastUsed = new Date(preset.updatedAt).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '14px 16px',
        borderRadius: 10,
        border: `1px solid ${colors.border}`,
        backgroundColor: colors.surface,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: colors.text }}>
            {preset.name}
          </span>
          {preset.category && (
            <span
              style={{
                fontSize: 11,
                fontWeight: 500,
                padding: '1px 8px',
                borderRadius: 4,
                backgroundColor: 'var(--accent-glow)',
                color: colors.accent,
              }}
            >
              {preset.category}
            </span>
          )}
        </div>
        {preset.description && (
          <span
            style={{ fontSize: 12, color: colors.muted, lineHeight: 1.4, display: 'block' }}
          >
            {preset.description}
          </span>
        )}
        <span style={{ fontSize: 11, color: colors.subtle, marginTop: 4, display: 'block' }}>
          {preset.filters.conditions.length} condition
          {preset.filters.conditions.length !== 1 ? 's' : ''} &middot; Last used: {lastUsed}
        </span>
      </div>
      <button
        onClick={onLoad}
        style={{
          padding: '8px 16px',
          borderRadius: 8,
          border: 'none',
          backgroundColor: colors.accent,
          color: 'var(--accent-ink)',
          fontSize: 13,
          fontWeight: 600,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
          transition: 'opacity 150ms ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.opacity = '0.9';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.opacity = '1';
        }}
      >
        Load
      </button>
      <button
        onClick={onDelete}
        title="Delete"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 32,
          height: 32,
          borderRadius: 6,
          border: 'none',
          background: 'none',
          cursor: 'pointer',
          color: colors.subtle,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--danger-hover)';
          e.currentTarget.style.color = colors.danger;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = 'transparent';
          e.currentTarget.style.color = colors.subtle;
        }}
      >
        <Trash2 size={15} />
      </button>
    </div>
  );
}
