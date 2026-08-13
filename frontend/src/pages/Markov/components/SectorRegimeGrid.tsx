interface SectorRegime {
  etf: string;
  regime: string;
  bull_probability: number;
  vol_regime: string;
}

interface SectorRegimeGridProps {
  sectors: SectorRegime[];
}

export default function SectorRegimeGrid({ sectors }: SectorRegimeGridProps) {
  if (!sectors || sectors.length === 0) return null;

  const muted = "var(--muted)";
  const border = "var(--border)";

  return (
    <div style={{ padding: "24px" }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16, color: "var(--foreground)" }}>
        Sector Regimes
      </h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
        {sectors.map((s) => (
          <div
            key={s.etf}
            style={{
              padding: 16,
              borderRadius: 12,
              background: "var(--surface)",
              border: `1px solid ${s.regime === "BULL" ? "var(--good)" : s.regime === "BEAR" ? "var(--bad)" : border}`,
              boxShadow: s.regime === "BULL" ? "inset 0 0 0 1px var(--accent-glow)" : "none",
            }}
          >
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--foreground)" }}>{s.etf}</div>
            <div style={{ fontSize: 14, color: s.regime === "BULL" ? "var(--good)" : s.regime === "BEAR" ? "var(--bad)" : "var(--muted)", marginTop: 4, fontWeight: 600 }}>
              {s.regime}
            </div>
            <div style={{ fontSize: 12, color: muted, marginTop: 2 }}>
              Bull: {(s.bull_probability * 100).toFixed(0)}% | Vol: {s.vol_regime}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}