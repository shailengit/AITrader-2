import { useState, useEffect, useRef } from "react";
import { request } from "@/lib/api";

export interface ScanParams {
  model: "xgboost" | "lstm";
  threshold: number;
  minConviction: number;
  maxResults: number;
  asOfDate: string;  // YYYY-MM-DD, empty string = today
}

interface RetrainProgress {
  running: boolean;
  progress_pct: number;
  current_ticker: string;
  current_action: string;
  tickers_completed: number;
  tickers_total: number;
  elapsed_seconds: number;
  estimated_remaining_seconds: number;
  model: string;
  stale?: boolean;
}

interface ControlPanelProps {
  onScan: (params: ScanParams) => void;
  loading: boolean;
  /** Optional initial values to pre-fill the form (from URL params). */
  initialValues?: Partial<ScanParams>;
}

export default function ControlPanel({ onScan, loading, initialValues }: ControlPanelProps) {
  const [model, setModel] = useState<"xgboost" | "lstm">("xgboost");
  const [threshold, setThreshold] = useState(2.0);
  const [minConviction, setMinConviction] = useState(0.6);
  const [maxResults, setMaxResults] = useState(50);
  const [asOfDate, setAsOfDate] = useState("");
  const [retraining, setRetraining] = useState(false);
  const [retrainMsg, setRetrainMsg] = useState<string | null>(null);
  const [retrainProgress, setRetrainProgress] = useState<RetrainProgress | null>(null);
  const retrainMsgTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Apply initial values from URL params on mount
  useEffect(() => {
    if (!initialValues) return;
    if (initialValues.model) setModel(initialValues.model);
    if (initialValues.minConviction != null) setMinConviction(initialValues.minConviction);
    if (initialValues.maxResults != null) setMaxResults(initialValues.maxResults);
    if (initialValues.asOfDate != null) setAsOfDate(initialValues.asOfDate);
    if (initialValues.threshold != null) setThreshold(initialValues.threshold);
    // Only run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll retrain progress while retraining
  useEffect(() => {
    if (!retraining) return;
    const interval = setInterval(async () => {
      try {
        const data = await request<RetrainProgress>("/markov/retrain-status");
        setRetrainProgress(data);
        if (!data.running) {
          clearInterval(interval);
          setRetraining(false);
          setRetrainMsg("Retraining complete!");
          // Clear completion message after 5s
          if (retrainMsgTimer.current) clearTimeout(retrainMsgTimer.current);
          retrainMsgTimer.current = setTimeout(() => setRetrainMsg(null), 5000);
        } else if (data.stale) {
          clearInterval(interval);
          setRetraining(false);
          setRetrainMsg("Retrain process stopped responding. Please try again.");
        }
      } catch {
        // ignore polling errors
      }
    }, 2000);
    return () => {
      clearInterval(interval);
    };
  }, [retraining]);

  // Format elapsed time
  const formatTime = (seconds: number): string => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  };

  const handleRetrain = async (retrainModel: "xgboost" | "lstm") => {
    setRetraining(true);
    setRetrainMsg(null);
    setRetrainProgress(null);
    try {
      await request("/markov/retrain", {
        method: "POST",
        body: {
          model: retrainModel,
          threshold: threshold / 100,
          max_tickers: maxResults,
        },
      });
      setRetrainMsg(`${retrainModel === "xgboost" ? "XGBoost" : "LSTM"} retraining started in background.`);
    } catch (e) {
      setRetraining(false);
      setRetrainMsg(e instanceof Error ? e.message : "Retrain failed");
    }
  };

  return (
    <div style={{ maxWidth: 480, padding: "24px" }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 24 }}>
        Scan Controls
      </h2>

      {/* Model Toggle */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 8 }}>
          Model
        </label>
        <div style={{ display: "flex", gap: 12 }}>
          <button
            onClick={() => setModel("xgboost")}
            style={{
              padding: "8px 20px",
              borderRadius: 8,
              border: `2px solid ${model === "xgboost" ? "#10B981" : "#d2d2d7"}`,
              background: model === "xgboost" ? "rgba(16, 185, 129, 0.1)" : "transparent",
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            XGBoost (Fast)
          </button>
          <button
            onClick={() => setModel("lstm")}
            style={{
              padding: "8px 20px",
              borderRadius: 8,
              border: `2px solid ${model === "lstm" ? "#10B981" : "#d2d2d7"}`,
              background: model === "lstm" ? "rgba(16, 185, 129, 0.1)" : "transparent",
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            LSTM (Deep)
          </button>
        </div>
      </div>

      {/* Threshold Slider */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 8 }}>
          BUY/SELL Threshold: {threshold.toFixed(1)}%
        </label>
        <input
          type="range"
          min={0.5}
          max={5.0}
          step={0.5}
          value={threshold}
          onChange={(e) => setThreshold(parseFloat(e.target.value))}
          style={{ width: "100%" }}
        />
        <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>
          Affects LSTM (trained on-the-fly). For XGBoost, use Retrain to apply a new threshold.
        </div>
      </div>

      {/* Min Conviction Slider */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 8 }}>
          Min Conviction: {minConviction.toFixed(2)}
        </label>
        <input
          type="range"
          min={0.3}
          max={0.95}
          step={0.05}
          value={minConviction}
          onChange={(e) => setMinConviction(parseFloat(e.target.value))}
          style={{ width: "100%" }}
        />
        <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>
          Minimum confidence for a BUY signal. Also used by the Actionable filter.
        </div>
      </div>

      {/* Max Results */}
      <div style={{ marginBottom: 24 }}>
        <label style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 8 }}>
          Max Tickers to Scan
        </label>
        <input
          type="number"
          value={maxResults}
          onChange={(e) => setMaxResults(parseInt(e.target.value) || 50)}
          min={5}
          max={500}
          style={{
            padding: "8px 12px",
            borderRadius: 8,
            border: "1px solid #d2d2d7",
            width: 100,
          }}
        />
        <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>
          Number of tickers to scan (5–500). Results are capped at this value.
        </div>
      </div>

      {/* As of Date */}
      <div style={{ marginBottom: 24 }}>
        <label style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 8 }}>
          As of Date
        </label>
        <input
          type="date"
          value={asOfDate}
          max={new Date().toISOString().split("T")[0]}
          onChange={(e) => setAsOfDate(e.target.value)}
          style={{
            padding: "8px 12px",
            borderRadius: 8,
            border: "1px solid #d2d2d7",
            width: 180,
          }}
        />
        <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>
          Scan as of this date (leave empty for today). Affects regime model, features, and labels.
        </div>
      </div>

      {/* Retrain Models */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 8 }}>
          Retrain Models
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => handleRetrain("xgboost")}
            disabled={retraining || loading}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: "1px solid #F59E0B",
              background: retraining || loading ? "rgba(156,163,175,0.2)" : "rgba(245,158,11,0.1)",
              cursor: retraining || loading ? "not-allowed" : "pointer",
              fontSize: 13,
              color: "inherit",
            }}
            title="Retrain all XGBoost models with current threshold"
          >
            {retraining ? "Retraining..." : "Retrain XGBoost"}
          </button>
          <button
            onClick={() => handleRetrain("lstm")}
            disabled={retraining || loading}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: "1px solid #8B5CF6",
              background: retraining || loading ? "rgba(156,163,175,0.2)" : "rgba(139,92,246,0.1)",
              cursor: retraining || loading ? "not-allowed" : "pointer",
              fontSize: 13,
              color: "inherit",
            }}
            title="Retrain all LSTM models with current threshold"
          >
            {retraining ? "Retraining..." : "Retrain LSTM"}
          </button>
        </div>
        {retrainMsg && !retrainProgress?.running && (
          <div style={{ fontSize: 11, marginTop: 6, color: retrainMsg.includes("failed") ? "#EF4444" : "#10B981" }}>
            {retrainMsg}
          </div>
        )}

        {/* Retrain progress bar */}
        {retrainProgress?.running && (
          <div style={{
            marginTop: 12,
            padding: "14px 16px",
            borderRadius: 10,
            background: "rgba(255,255,255,0.03)",
            border: "1px solid rgba(255,255,255,0.1)",
          }}>
            {/* Status header */}
            <div style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  backgroundColor: "#10B981",
                  animation: "pulse-dot 1.2s ease-in-out infinite",
                }} />
                <span style={{ fontWeight: 600, fontSize: 13 }}>
                  {retrainProgress.current_action || "Retraining..."}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.7)" }}>
                {formatTime(retrainProgress.elapsed_seconds)} elapsed
                {retrainProgress.estimated_remaining_seconds > 0 && (
                  <> · ~{formatTime(retrainProgress.estimated_remaining_seconds)} remaining</>
                )}
              </div>
            </div>

            {/* Progress bar */}
            <div style={{
              width: "100%",
              height: 6,
              borderRadius: 3,
              background: "rgba(255,255,255,0.1)",
              overflow: "hidden",
              marginBottom: 6,
            }}>
              <div style={{
                width: `${Math.max(retrainProgress.progress_pct, 2)}%`,
                height: "100%",
                borderRadius: 3,
                background: "linear-gradient(90deg, #10B981, #34D399, #10B981)",
                backgroundSize: "200% 100%",
                animation: "shimmer 1.5s ease-in-out infinite",
                transition: "width 0.5s ease",
              }} />
            </div>

            {/* Ticker count */}
            <div style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 12,
              color: "rgba(255,255,255,0.6)",
            }}>
              <span>
                {retrainProgress.current_ticker ? (
                  <>Processing <strong style={{ color: "#10B981" }}>{retrainProgress.current_ticker}</strong> ({retrainProgress.tickers_completed}/{retrainProgress.tickers_total})</>
                ) : (
                  <>{retrainProgress.tickers_completed}/{retrainProgress.tickers_total} tickers</>
                )}
              </span>
              <span>{retrainProgress.progress_pct.toFixed(0)}%</span>
            </div>
          </div>
        )}
      </div>

      {/* Scan Button */}
      <button
        onClick={() => onScan({ model, threshold: threshold / 100, minConviction, maxResults, asOfDate })}
        disabled={loading}
        style={{
          padding: "12px 32px",
          borderRadius: 8,
          border: "none",
          background: loading ? "#9CA3AF" : "#10B981",
          color: "white",
          fontWeight: 600,
          cursor: loading ? "not-allowed" : "pointer",
          fontSize: 16,
        }}
      >
        {loading ? "Scanning..." : "Run Scan"}
      </button>
    </div>
  );
}