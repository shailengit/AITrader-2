import { useState } from "react";
import { recordAppReferrer } from "../../../components/layout/Layout";
import { SaveHypothesisPopover } from "../../../components/shared/SaveHypothesisPopover";

interface Signal {
  ticker: string;
  sector: string;
  signal: string;
  conviction: number;
  price: number;
  regime: string;
  vol_regime: string;
  etf: string;
}

interface SignalsTableProps {
  signals: Signal[];
  totalScanned: number;
  loading: boolean;
  isDarkMode: boolean;
  minConviction?: number;  // from the scan params slider, so Actionable uses the same threshold
  asOfDate?: string;
  /** Called when the user clicks a row. */
  onTickerClick: (ticker: string) => void;
}

export default function SignalsTable({ signals, totalScanned, loading, isDarkMode, minConviction = 0.6, asOfDate, onTickerClick }: SignalsTableProps) {
  const [showAll, setShowAll] = useState(false);
  // Use the same minConviction from the scan params slider so the
  // Actionable filter matches what the user configured.
  const actionable = signals.filter((s) => s.signal === "BUY" && s.conviction >= minConviction);
  const display = showAll ? signals : actionable;

  const buyTickers = signals.filter((s) => s.signal === "BUY").map((s) => s.ticker);
  const exportUrl = buyTickers.length > 0
    ? `/quantgen/build?tickers=${encodeURIComponent(buyTickers.join(","))}&from_date=${asOfDate || new Date().toISOString().split("T")[0]}`
    : null;

  const muted = isDarkMode ? "rgba(255,255,255,0.7)" : "#6e6e73";
  const border = isDarkMode ? "rgba(255,255,255,0.12)" : "#d2d2d7";
  const rowBorder = isDarkMode ? "rgba(255,255,255,0.06)" : "#f0f0f0";
  const barBg = isDarkMode ? "rgba(255,255,255,0.15)" : "#e5e7eb";

  if (loading) {
    return <div style={{ padding: 24, textAlign: "center", color: muted }}>Loading signals...</div>;
  }

  if (signals.length === 0) {
    return <div style={{ padding: 24, textAlign: "center", color: muted }}>No signals found. Run a scan to begin.</div>;
  }

  return (
    <div style={{ padding: "24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ fontSize: 20, fontWeight: 600 }}>
          Signals ({display.length} of {signals.length})
        </h2>
        <div style={{ fontSize: 12, color: muted }}>Scanned: {totalScanned} tickers</div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button
          onClick={() => setShowAll(false)}
          style={{
            padding: "6px 16px",
            borderRadius: 6,
            border: `1px solid ${!showAll ? "#10B981" : border}`,
            background: !showAll ? "rgba(16, 185, 129, 0.1)" : "transparent",
            cursor: "pointer",
            fontSize: 13,
            color: "inherit",
          }}
          title={`Only BUY signals with conviction ≥ ${minConviction}`}
        >
          Actionable ({actionable.length})
        </button>
        <button
          onClick={() => setShowAll(true)}
          style={{
            padding: "6px 16px",
            borderRadius: 6,
            border: `1px solid ${showAll ? "#10B981" : border}`,
            background: showAll ? "rgba(16, 185, 129, 0.1)" : "transparent",
            cursor: "pointer",
            fontSize: 13,
            color: "inherit",
          }}
          title="All signals: BUY, HOLD, and SELL"
        >
          Full List ({signals.length})
        </button>
        {exportUrl && (
          <button
            onClick={() => {
              recordAppReferrer('/markov', 'Markov Chain Trader');
              window.open(exportUrl, "_blank");
            }}
            style={{
              marginLeft: "auto",
              padding: "6px 16px",
              borderRadius: 6,
              border: `1px solid #10B981`,
              background: "rgba(16, 185, 129, 0.1)",
              cursor: "pointer",
              fontSize: 13,
              color: "inherit",
            }}
            title="Open these BUY signals in QuantGen Builder for backtesting"
          >
            Export {buyTickers.length} BUY → QuantGen
          </button>
        )}
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${border}` }}>
              <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 600 }}>Rank</th>
              <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 600 }}>Ticker</th>
              <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 600 }}>Sector</th>
              <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 600 }}>Signal</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontWeight: 600 }}>Conviction</th>
              <th style={{ textAlign: "right", padding: "8px 12px", fontWeight: 600 }}>Price</th>
              <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 600 }}>ETF</th>
              <th
                style={{ textAlign: "center", padding: "8px 12px", fontWeight: 600 }}
                title="Save this signal as a hypothesis"
              >
                Save
              </th>
            </tr>
          </thead>
          <tbody>
            {display.map((s, i) => (
              <tr
                key={`${s.ticker}-${i}`}
                role="button"
                tabIndex={0}
                aria-label={`Open detail for ${s.ticker}`}
                onClick={() => onTickerClick(s.ticker)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onTickerClick(s.ticker);
                  }
                }}
                style={{
                  borderBottom: `1px solid ${rowBorder}`,
                  cursor: 'pointer',
                  transition: 'background-color 150ms ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = isDarkMode ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent';
                }}
              >
                <td style={{ padding: "8px 12px" }}>{i + 1}</td>
                <td style={{ padding: "8px 12px", fontWeight: 600 }}>{s.ticker}</td>
                <td style={{ padding: "8px 12px" }}>{s.sector}</td>
                <td style={{ padding: "8px 12px" }}>
                  <span style={{
                    color: s.signal === "BUY" ? "#10B981" : s.signal === "SELL" ? "#EF4444" : muted,
                    fontWeight: 600,
                  }}>
                    {s.signal === "BUY" ? "▲ BUY" : s.signal === "SELL" ? "▼ SELL" : "● HOLD"}
                  </span>
                </td>
                <td style={{ padding: "8px 12px", textAlign: "right" }}>
                  <div style={{
                    display: "inline-block",
                    width: 60,
                    height: 6,
                    borderRadius: 3,
                    background: barBg,
                    marginRight: 8,
                    verticalAlign: "middle",
                  }}>
                    <div style={{
                      width: `${(s.conviction * 100).toFixed(0)}%`,
                      height: "100%",
                      borderRadius: 3,
                      background: s.conviction >= 0.6 ? "#10B981" : "#F59E0B",
                    }} />
                  </div>
                  {(s.conviction * 100).toFixed(0)}%
                </td>
                <td style={{ padding: "8px 12px", textAlign: "right" }}>${s.price.toFixed(2)}</td>
                <td style={{ padding: "8px 12px" }}>{s.etf}</td>
                <td style={{ padding: "8px 12px", textAlign: "center" }}>
                  <SaveHypothesisPopover
                    source="markov"
                    ticker={s.ticker}
                    sector={s.sector}
                    regime={s.regime}
                    conviction={s.conviction}
                    sourceMeta={{ page: 'markov', signal_id: s.ticker, etf: s.etf }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}