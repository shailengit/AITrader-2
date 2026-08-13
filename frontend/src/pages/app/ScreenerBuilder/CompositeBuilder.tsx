import { useState } from 'react';
import { X, Plus, FunctionSquare } from 'lucide-react';
import { FILTER_CATALOG, getFilterByKey } from '../../../data/filterCatalog';
import { useComposites, type CompositeOperation } from '../../../hooks/useComposites';

interface CompositeBuilderProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCompositeCreated?: () => void;
}

const OPERATIONS: { value: CompositeOperation; label: string; symbol: string }[] = [
  { value: 'add', label: 'Add', symbol: '+' },
  { value: 'subtract', label: 'Subtract', symbol: '−' },
  { value: 'multiply', label: 'Multiply', symbol: '×' },
  { value: 'divide', label: 'Divide', symbol: '÷' },
  { value: 'ratio_pct', label: 'Ratio %', symbol: '%' },
];

export default function CompositeBuilder({
  open,
  onOpenChange,
  onCompositeCreated,
}: CompositeBuilderProps) {
  const { saveComposite } = useComposites();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [leftIndicator, setLeftIndicator] = useState('');
  const [rightIndicator, setRightIndicator] = useState('');
  const [operation, setOperation] = useState<CompositeOperation>('divide');
  const [error, setError] = useState<string | null>(null);

  const colors = {
    bg: 'var(--surface-overlay)',
    overlay: 'rgba(0,0,0,0.5)',
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    subtle: 'var(--subtle)',
    border: 'var(--border)',
    surface: 'var(--surface)',
    inputBg: 'var(--canvas)',
    accent: 'var(--accent)',
    danger: 'var(--bad)',
  };

  if (!open) return null;

  const numberFilters = FILTER_CATALOG.filter((f) => f.type === 'number');

  const leftSpec = getFilterByKey(leftIndicator);
  const rightSpec = getFilterByKey(rightIndicator);

  const handleSave = () => {
    setError(null);

    if (!name.trim()) {
      setError('Please enter a name for your composite.');
      return;
    }
    if (!leftIndicator) {
      setError('Please select a left indicator.');
      return;
    }
    if (!rightIndicator) {
      setError('Please select a right indicator.');
      return;
    }
    if (leftIndicator === rightIndicator) {
      setError('Left and right indicators must be different.');
      return;
    }

    saveComposite({
      name: name.trim(),
      description: description.trim() || undefined,
      leftIndicator,
      rightIndicator,
      operation,
    });

    // Reset form
    setName('');
    setDescription('');
    setLeftIndicator('');
    setRightIndicator('');
    setOperation('divide');
    onCompositeCreated?.();
    onOpenChange(false);
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
          width: 520,
          backgroundColor: colors.bg,
          borderRadius: 16,
          border: `1px solid ${colors.border}`,
          boxShadow: '0 25px 50px rgba(0,0,0,0.3)',
          padding: 24,
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 20,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <FunctionSquare size={20} color={colors.accent} />
            <span style={{ fontSize: 17, fontWeight: 600, color: colors.text }}>
              Create Composite
            </span>
          </div>
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

        <p style={{ fontSize: 13, color: colors.muted, margin: '0 0 20px', lineHeight: 1.5 }}>
          Combine two indicators with a math operation to create a new composite metric.
          It will appear in the filter catalog under "Custom Composites".
        </p>

        {/* Name */}
        <div style={{ marginBottom: 16 }}>
          <label
            style={{
              display: 'block',
              fontSize: 11,
              fontWeight: 600,
              color: colors.muted,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: 4,
            }}
          >
            Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., SMARatio, Volume x Price"
            style={{
              width: '100%',
              padding: '8px 10px',
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.inputBg,
              color: colors.text,
              fontSize: 14,
              outline: 'none',
            }}
          />
        </div>

        {/* Description */}
        <div style={{ marginBottom: 16 }}>
          <label
            style={{
              display: 'block',
              fontSize: 11,
              fontWeight: 600,
              color: colors.muted,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: 4,
            }}
          >
            Description (optional)
          </label>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What does this composite measure?"
            style={{
              width: '100%',
              padding: '8px 10px',
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.inputBg,
              color: colors.text,
              fontSize: 14,
              outline: 'none',
            }}
          />
        </div>

        {/* Formula builder */}
        <div
          style={{
            padding: 16,
            borderRadius: 10,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.surface,
            marginBottom: 16,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: colors.muted,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: 12,
            }}
          >
            Formula
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* Left indicator */}
            <select
              value={leftIndicator}
              onChange={(e) => setLeftIndicator(e.target.value)}
              style={{
                flex: 1,
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 13,
                outline: 'none',
              }}
            >
              <option value="">Select indicator...</option>
              {numberFilters.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>

            {/* Operation */}
            <select
              value={operation}
              onChange={(e) => setOperation(e.target.value as CompositeOperation)}
              style={{
                width: 80,
                padding: '8px 6px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 13,
                fontWeight: 600,
                textAlign: 'center',
                outline: 'none',
              }}
            >
              {OPERATIONS.map((op) => (
                <option key={op.value} value={op.value}>
                  {op.symbol}
                </option>
              ))}
            </select>

            {/* Right indicator */}
            <select
              value={rightIndicator}
              onChange={(e) => setRightIndicator(e.target.value)}
              style={{
                flex: 1,
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${colors.border}`,
                backgroundColor: colors.inputBg,
                color: colors.text,
                fontSize: 13,
                outline: 'none',
              }}
            >
              <option value="">Select indicator...</option>
              {numberFilters.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>

          {/* Preview */}
          {leftSpec && rightSpec && (
            <div
              style={{
                marginTop: 12,
                padding: '8px 12px',
                borderRadius: 6,
                backgroundColor: 'var(--accent-glow)',
                color: colors.accent,
                fontSize: 13,
                fontWeight: 600,
                textAlign: 'center',
              }}
            >
              {leftSpec.label}{' '}
              {OPERATIONS.find((o) => o.value === operation)?.symbol}{' '}
              {rightSpec.label}
              {operation === 'ratio_pct' ? ' × 100' : ''}
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div
            style={{
              padding: '8px 12px',
              borderRadius: 6,
              backgroundColor: 'var(--danger-hover)',
              color: colors.danger,
              fontSize: 13,
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button
            onClick={() => onOpenChange(false)}
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              border: `1px solid ${colors.border}`,
              backgroundColor: 'transparent',
              color: colors.muted,
              fontSize: 13,
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 16px',
              borderRadius: 8,
              border: 'none',
              backgroundColor: colors.accent,
              color: 'var(--accent-ink)',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <Plus size={15} />
            Create Composite
          </button>
        </div>
      </div>
    </div>
  );
}
