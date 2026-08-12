import { useState } from 'react';
import { request } from '@/lib/api';

interface Props {
  source: 'sectors' | 'screener' | 'markov';
  ticker?: string;
  sector?: string;
  regime?: string;
  conviction?: number;
  sourceMeta: Record<string, any>;
}

export function SaveHypothesisPopover({ source, ticker, sector, regime, conviction, sourceMeta }: Props) {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState('');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await request('/hypotheses', {
        method: 'POST',
        body: {
          source, ticker, sector, regime, conviction,
          why: why || `Saved from ${source}`,
          source_meta: sourceMeta,
        },
      });
      setOpen(false);
      setWhy('');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div onClick={(e) => e.stopPropagation()} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Save as hypothesis"
        style={{
          width: 24, height: 24, borderRadius: 6, border: '1px solid rgba(255,255,255,.15)',
          background: 'rgba(255,255,255,.04)', color: 'inherit', cursor: 'pointer', fontSize: 14,
        }}
      >+</button>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 6, zIndex: 50,
          background: '#11151c', border: '1px solid rgba(255,255,255,.12)', borderRadius: 10,
          padding: 12, minWidth: 240,
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Save as hypothesis</div>
          <textarea
            value={why}
            onChange={e => setWhy(e.target.value)}
            placeholder="Why is this interesting?"
            rows={3}
            style={{
              width: '100%', padding: 6, fontSize: 13,
              background: 'rgba(255,255,255,.04)', color: 'inherit',
              border: '1px solid rgba(255,255,255,.1)', borderRadius: 6, resize: 'vertical',
            }}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
            <button onClick={() => setOpen(false)} style={{ padding: '4px 10px', fontSize: 12, background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer' }}>Cancel</button>
            <button onClick={save} disabled={saving} style={{
              padding: '4px 12px', fontSize: 12, borderRadius: 4,
              background: '#10B981', color: '#050505', border: 'none', fontWeight: 600, cursor: 'pointer',
            }}>{saving ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
      )}
    </div>
  );
}
