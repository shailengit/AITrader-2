export function DriftAlertStrip() {
  return (
    <div style={{
      padding: 16, marginBottom: 16, borderRadius: 12,
      border: '1px solid rgba(255,255,255,.08)',
      background: 'rgba(255,255,255,.02)',
      fontSize: 14, opacity: .6,
    }}>
      No drift alerts. Deploy a strategy to start tracking.
    </div>
  );
}
