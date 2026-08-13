import { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { FILTER_CATEGORIES } from '../../../data/filterCatalog';

interface SaveScreenDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (name: string, description?: string, category?: string) => void;
  initialName?: string;
  mode: 'save' | 'save-as';
}

export default function SaveScreenDialog({
  open,
  onOpenChange,
  onSave,
  initialName,
  mode,
}: SaveScreenDialogProps) {
  const [name, setName] = useState(initialName || '');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [nameError, setNameError] = useState('');

  useEffect(() => {
    if (open) {
      setName(initialName || '');
      setDescription('');
      setCategory('');
      setNameError('');
    }
  }, [open, initialName]);

  const colors = {
    bg: 'var(--surface-overlay)',
    overlay: 'rgba(0,0,0,0.5)',
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    subtle: 'var(--subtle)',
    border: 'var(--border)',
    inputBg: 'var(--canvas)',
    accent: 'var(--accent)',
  };

  const handleSave = () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError('Name is required');
      return;
    }
    onSave(trimmed, description.trim() || undefined, category || undefined);
    onOpenChange(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSave();
    }
    if (e.key === 'Escape') {
      onOpenChange(false);
    }
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
          width: 420,
          backgroundColor: colors.bg,
          borderRadius: 16,
          border: `1px solid ${colors.border}`,
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
            {mode === 'save' ? 'Save Screen' : 'Save As'}
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

        {/* Form */}
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Name */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 6,
              }}
            >
              Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (nameError) setNameError('');
              }}
              onKeyDown={handleKeyDown}
              placeholder="My Screener"
              autoFocus
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 8,
                border: `1px solid ${nameError ? 'var(--bad)' : colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 14,
                outline: 'none',
              }}
            />
            {nameError && (
              <span style={{ fontSize: 12, color: 'var(--bad)', marginTop: 4, display: 'block' }}>
                {nameError}
              </span>
            )}
          </div>

          {/* Description */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 6,
              }}
            >
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Optional description..."
              rows={3}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 8,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 14,
                outline: 'none',
                resize: 'vertical',
                fontFamily: 'inherit',
              }}
            />
          </div>

          {/* Category */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: colors.muted,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 6,
              }}
            >
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 8,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 14,
                outline: 'none',
              }}
            >
              <option value="">No category</option>
              {FILTER_CATEGORIES.map((cat) => (
                <option key={cat.id} value={cat.label}>
                  {cat.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 8,
            padding: '12px 20px',
            borderTop: `1px solid ${colors.border}`,
          }}
        >
          <button
            onClick={() => onOpenChange(false)}
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              border: `1px solid ${colors.border}`,
              backgroundColor: 'transparent',
              color: colors.muted,
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim()}
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              border: 'none',
              backgroundColor: name.trim() ? colors.accent : colors.subtle,
              color: name.trim() ? 'var(--accent-ink)' : colors.muted,
              fontSize: 13,
              fontWeight: 600,
              cursor: name.trim() ? 'pointer' : 'not-allowed',
              transition: 'opacity 150ms ease',
            }}
            onMouseEnter={(e) => {
              if (name.trim()) e.currentTarget.style.opacity = '0.9';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = '1';
            }}
          >
            {mode === 'save' ? 'Save' : 'Save As'}
          </button>
        </div>
      </div>
    </div>
  );
}
