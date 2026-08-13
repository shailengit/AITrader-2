import { useState } from 'react';
import { ChevronDown, ChevronRight, RotateCcw } from 'lucide-react';
import { Slider, Toggle } from '../../../components/ui';

export interface SubWeights {
  trend: number;
  momentum: number;
  volatility: number;
  volume: number;
}

export const DEFAULT_BASE_WEIGHT = 60;
export const DEFAULT_SUB_WEIGHTS: SubWeights = { trend: 30, momentum: 25, volatility: 20, volume: 25 };
export const DEFAULT_SHOW_ALIGNMENT = false;

interface ScoringPanelProps {
  baseWeight: number;
  subWeights: SubWeights;
  showAlignment: boolean;
  angleWeight: number;
  hasCrossFilters: boolean;
  onBaseWeightChange: (v: number) => void;
  onSubWeightChange: (key: keyof SubWeights, v: number) => void;
  onShowAlignmentChange: (v: boolean) => void;
  onAngleWeightChange: (v: number) => void;
  onReset: () => void;
}

/**
 * Collapsible card with 5 sliders (base_weight + 4 sub-weights), 1 toggle
 * (alignment diagnostic), and a reset link. Inline-styled to match the rest
 * of the ScreenerBuilder (see CLAUDE.md "Tailwind Spacing" lesson).
 */
export default function ScoringPanel({
  baseWeight, subWeights, showAlignment,
  angleWeight, hasCrossFilters,
  onBaseWeightChange, onSubWeightChange, onShowAlignmentChange, onAngleWeightChange, onReset,
}: ScoringPanelProps) {
  const [open, setOpen] = useState(true);
  const colors = {
    text: 'var(--foreground)',
    muted: 'var(--muted)',
    border: 'var(--border)',
    surface: 'var(--surface)',
  };

  return (
    <div
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: '12px 14px',
        marginTop: 12,
      }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          width: '100%', background: 'none', border: 'none', padding: 0,
          cursor: 'pointer', color: colors.text, fontSize: 13, fontWeight: 600,
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Scoring
        </span>
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => { e.stopPropagation(); onReset(); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onReset(); } }}
          style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: colors.muted, cursor: 'pointer' }}
        >
          <RotateCcw size={11} /> Reset
        </span>
      </button>
      {open && (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="Base setup vs filter match" hint="0 = pure filter match, 100 = pure setup">
            <Slider value={baseWeight} onChange={onBaseWeightChange} min={0} max={100} ariaLabel="Base setup vs filter match" />
          </Field>
          <Field label="Trend weight" hint="How much the trend sub-score contributes">
            <Slider value={subWeights.trend} onChange={(v) => onSubWeightChange('trend', v)} min={0} max={100} ariaLabel="Trend weight" />
          </Field>
          <Field label="Momentum weight" hint="How much the momentum sub-score contributes">
            <Slider value={subWeights.momentum} onChange={(v) => onSubWeightChange('momentum', v)} min={0} max={100} ariaLabel="Momentum weight" />
          </Field>
          <Field label="Volatility weight" hint="How much the volatility sub-score contributes">
            <Slider value={subWeights.volatility} onChange={(v) => onSubWeightChange('volatility', v)} min={0} max={100} ariaLabel="Volatility weight" />
          </Field>
          <Field label="Volume weight" hint="How much the volume sub-score contributes">
            <Slider value={subWeights.volume} onChange={(v) => onSubWeightChange('volume', v)} min={0} max={100} ariaLabel="Volume weight" />
          </Field>
          {hasCrossFilters && (
            <Field label="Crossover angle weight" hint="0 = binary pass/fail, 100 = purely angle-based scoring">
              <Slider value={angleWeight} onChange={onAngleWeightChange} min={0} max={100} ariaLabel="Crossover angle weight" />
            </Field>
          )}
          <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: 10 }}>
            <Toggle
              checked={showAlignment}
              onChange={onShowAlignmentChange}
              label="Show alignment diagnostic (Δ vs return)"
            />
            <div style={{ fontSize: 11, color: colors.muted, marginTop: 4, lineHeight: 1.4 }}>
              Adds a small column showing score − return. Use it to verify that the
              top of the table by score is also near the top by return.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--foreground)' }}>{label}</div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6, lineHeight: 1.3 }}>{hint}</div>
      {children}
    </div>
  );
}
