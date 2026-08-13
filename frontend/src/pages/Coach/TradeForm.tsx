import { useState } from 'react';
import { coachApi } from '../../lib/coach';

export function TradeForm({ onCreated }: { onCreated: () => void }) {
  const [ticker, setTicker] = useState('');
  const [side, setSide] = useState<'long' | 'short'>('long');
  const [qty, setQty] = useState('100');
  const [entryPx, setEntryPx] = useState('');
  const [entryAt, setEntryAt] = useState(new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await coachApi.createTrade({
        ticker: ticker.trim().toUpperCase(),
        side,
        qty: parseFloat(qty),
        entry_px: parseFloat(entryPx),
        entry_at: new Date(entryAt).toISOString(),
        notes: notes || undefined,
      });
      setTicker('');
      setEntryPx('');
      setNotes('');
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-7 gap-3 items-end">
      <label className="flex flex-col text-xs text-[color:var(--subtle)]">
        Ticker
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          required
          className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm text-[color:var(--foreground)]"
        />
      </label>
      <label className="flex flex-col text-xs text-[color:var(--subtle)]">
        Side
        <select
          value={side}
          onChange={(e) => setSide(e.target.value as 'long' | 'short')}
          className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm text-[color:var(--foreground)]"
        >
          <option value="long">long</option>
          <option value="short">short</option>
        </select>
      </label>
      <label className="flex flex-col text-xs text-[color:var(--subtle)]">
        Qty
        <input
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          type="number"
          step="any"
          required
          className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm text-[color:var(--foreground)]"
        />
      </label>
      <label className="flex flex-col text-xs text-[color:var(--subtle)]">
        Entry Px
        <input
          value={entryPx}
          onChange={(e) => setEntryPx(e.target.value)}
          type="number"
          step="any"
          required
          className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm text-[color:var(--foreground)]"
        />
      </label>
      <label className="flex flex-col text-xs text-[color:var(--subtle)]">
        Entry At
        <input
          value={entryAt}
          onChange={(e) => setEntryAt(e.target.value)}
          type="date"
          required
          className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm text-[color:var(--foreground)]"
        />
      </label>
      <label className="flex flex-col text-xs text-[color:var(--subtle)] col-span-1">
        Notes
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="rounded-md border border-[color:var(--border-hover)] bg-[color:var(--surface-raised)] px-2 py-1 text-sm text-[color:var(--foreground)]"
        />
      </label>
      <button
        type="submit"
        disabled={submitting}
        className="rounded-md border border-[color:var(--accent-dark)] px-3 py-1 text-sm text-[color:var(--accent-light)] hover:bg-[color:var(--accent-glow)] disabled:opacity-50"
      >
        {submitting ? 'Adding…' : 'Add Trade'}
      </button>
      {error && <div className="col-span-7 text-sm text-[color:var(--bad)]">{error}</div>}
    </form>
  );
}
