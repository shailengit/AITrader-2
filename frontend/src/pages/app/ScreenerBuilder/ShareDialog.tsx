import { useState } from 'react';
import { X, Copy, Check, Code } from 'lucide-react';
import { encodeShareUrl, type ShareData } from '../../../lib/shareCodec';

interface ShareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  screenData: ShareData;
}

export default function ShareDialog({ open, onOpenChange, screenData }: ShareDialogProps) {
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

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

  const shareUrl = (() => {
    try {
      const base = window.location.origin + window.location.pathname;
      const encoded = encodeShareUrl(screenData);
      if (!encoded) return '';
      return `${base}?s=${encoded}`;
    } catch {
      return '';
    }
  })();

  const jsonData = (() => {
    try {
      return JSON.stringify(screenData, null, 2);
    } catch {
      return '';
    }
  })();

  const handleCopyUrl = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2000);
    } catch {
      // Fallback
      const el = document.createElement('textarea');
      el.value = shareUrl;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2000);
    }
  };

  const handleCopyJson = async () => {
    if (!jsonData) return;
    try {
      await navigator.clipboard.writeText(jsonData);
      setCopiedJson(true);
      setTimeout(() => setCopiedJson(false), 2000);
    } catch {
      setCopiedJson(true);
      setTimeout(() => setCopiedJson(false), 2000);
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
          width: 480,
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
            Share Screen
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

        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Share URL */}
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
              Share URL
            </label>
            <div
              style={{
                display: 'flex',
                gap: 8,
              }}
            >
              <input
                type="text"
                value={shareUrl}
                readOnly
                style={{
                  flex: 1,
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: `1px solid ${colors.border}`,
                  backgroundColor: colors.inputBg,
                  color: colors.text,
                  fontSize: 13,
                  fontFamily: 'monospace',
                  outline: 'none',
                }}
              />
              <button
                onClick={handleCopyUrl}
                title="Copy URL"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: 'none',
                  backgroundColor: copiedUrl ? colors.accent : colors.inputBg,
                  color: copiedUrl ? 'var(--accent-ink)' : colors.text,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  transition: 'all 150ms ease',
                }}
              >
                {copiedUrl ? <Check size={16} /> : <Copy size={16} />}
                {copiedUrl ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <span style={{ fontSize: 11, color: colors.subtle, marginTop: 4, display: 'block' }}>
              Anyone with this link can load your screener configuration.
            </span>
          </div>

          {/* Copy as JSON */}
          <div>
            <button
              onClick={handleCopyJson}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '8px 14px',
                borderRadius: 8,
                border: `1px solid ${colors.border}`,
                backgroundColor: 'transparent',
                color: colors.muted,
                fontSize: 13,
                fontWeight: 500,
                cursor: 'pointer',
                transition: 'all 150ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.accent;
                e.currentTarget.style.color = colors.accent;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.muted;
              }}
            >
              {copiedJson ? <Check size={15} /> : <Code size={15} />}
              {copiedJson ? 'Copied!' : 'Copy as JSON'}
            </button>
          </div>

          {/* Summary */}
          <div
            style={{
              padding: 12,
              borderRadius: 8,
              backgroundColor: colors.inputBg,
              border: `1px solid ${colors.border}`,
            }}
          >
            <span style={{ fontSize: 12, color: colors.muted, display: 'block', marginBottom: 4 }}>
              Screen summary
            </span>
            <span style={{ fontSize: 13, color: colors.text, lineHeight: 1.5, display: 'block' }}>
              {screenData.filters.conditions.length} condition
              {screenData.filters.conditions.length !== 1 ? 's' : ''}
              {screenData.filters.match === 'all' ? ' (match all)' : ' (match any)'}
              {screenData.sort?.by && ` · Sort by ${screenData.sort?.by}`}
              {screenData.maxResults && ` · Max ${screenData.maxResults}`}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
