import { useState } from 'react';

export type DateRange = { start: string; end: string };

const PRESETS: { label: string; days: number | 'ytd' | 'all' }[] = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: 'YTD', days: 'ytd' },
  { label: 'All', days: 'all' },
];

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function presetRange(days: number | 'ytd' | 'all'): DateRange {
  const end = new Date();
  let start: Date;
  if (days === 'ytd') {
    start = new Date(end.getFullYear(), 0, 1);
  } else if (days === 'all') {
    start = new Date('2020-01-01');
  } else {
    start = new Date(end);
    start.setDate(start.getDate() - days);
  }
  return { start: toISODate(start), end: toISODate(end) };
}

export function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
}) {
  const [custom, setCustom] = useState(false);
  return (
    <div className="flex items-center gap-2">
      {PRESETS.map((p) => (
        <button
          key={p.label}
          onClick={() => {
            setCustom(false);
            onChange(presetRange(p.days));
          }}
          className="rounded-md border border-[color:var(--border-hover)] px-3 py-1 text-sm hover:bg-[color:var(--surface-raised)]"
        >
          {p.label}
        </button>
      ))}
      <button
        onClick={() => setCustom(true)}
        className="rounded-md border border-[color:var(--border-hover)] px-3 py-1 text-sm hover:bg-[color:var(--surface-raised)]"
      >
        Custom
      </button>
      {custom && (
        <>
          <input
            type="date"
            value={value.start}
            onChange={(e) => onChange({ ...value, start: e.target.value })}
            className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm"
          />
          <span className="text-[color:var(--subtle)]">→</span>
          <input
            type="date"
            value={value.end}
            onChange={(e) => onChange({ ...value, end: e.target.value })}
            className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm"
          />
        </>
      )}
    </div>
  );
}
