import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import Editor from "@monaco-editor/react";
import {
  Play,
  Save,
  Terminal,
  Activity,
  Trash2,
  Microscope,
  FilePlus,
  ChevronDown,
  ChevronRight,
  Sparkles,
  AlertCircle,
  Lightbulb,
  FileCode,
  Box,
} from "lucide-react";
import { OptimizationConfig } from "@/components/quantgen";
import { IndicatorBrowser } from '@/components/quantgen/IndicatorBrowser';
import { TerminalRedirectBanner } from '../../components/shared/TerminalRedirectBanner';
import { SectorRegime, fetchRegimes, summarizeRegimes } from "../../lib/regime";
import { quantgen } from "@/lib/api";

import { useTheme } from "../../context/ThemeContext";

interface ParamRange {
  name: string;
  start: number;
  stop: number;
  step: number;
  sourceValue?: number; // The code value that last generated this range
}

interface WFOConfig {
  type: "rolling" | "expanding";
  windows: number;
  ratio: number;
  splitMethod: "ratio" | "fixed";
  train_days: number;
  test_days: number;
  start_date: string;
  end_date: string;
}

interface OptimizationConfigData {
  mode: "simple" | "wfo" | "true_wfo";
  metric: "total_return" | "sharpe" | "sortino" | "max_dd";
  wfo: WFOConfig;
}

function roundToDecimals(value: number, decimals: number): number {
  const factor = Math.pow(10, decimals);
  return Math.round(value * factor) / factor;
}

function computeAutoRange(
  value: number,
  isInteger: boolean
): { start: number; stop: number; step: number } {
  if (isInteger) {
    const start = Math.max(1, Math.round(value * 0.5));
    const stop = Math.max(1, Math.round(value * 1.5));
    const step = Math.max(1, Math.round(value * 0.1));
    return { start, stop, step };
  }
  const start = Math.max(0.1, roundToDecimals(value * 0.5, 2));
  const stop = Math.max(0.1, roundToDecimals(value * 1.5, 2));
  const step = Math.max(0.1, roundToDecimals(value * 0.1, 2));
  return { start, stop, step };
}

const makeDefaultOptConfig = (exportedStart?: string | null): OptimizationConfigData => ({
  mode: "true_wfo",
  metric: "total_return",
  wfo: {
    type: "rolling",
    windows: 10,
    ratio: 0.7,
    splitMethod: "ratio",
    train_days: 252,
    test_days: 63,
    start_date: exportedStart || "2023-01-01",
    end_date: "2024-01-01",
  },
});

export default function Builder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const loadSlug = searchParams.get('load');
  const fromScreenerTickers = searchParams.get("tickers");
  const fromScreenerDate = searchParams.get("from_date");
  const importedTickers = fromScreenerTickers
    ? fromScreenerTickers.split(',').map(t => t.trim()).filter(Boolean)
    : [];
  const [showAllTickers, setShowAllTickers] = useState(false);
  const tickerCount = importedTickers.length;
  const shouldCollapse = tickerCount > 8;
  const [strategyPrompt, setStrategyPrompt] = useState("");
  const [tickers, setTickers] = useState(() => importedTickers[0] || "AAPL");
  const [code, setCode] = useState("");
  const [output, setOutput] = useState("");
  const [currentFilename, setCurrentFilename] = useState<string | null>(null);
  const isFirstLoad = useRef(true);
  const editorRef = useRef<any>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [strategies, setStrategies] = useState<string[]>([]);
  const [runMode, setRunMode] = useState<"backtest" | "optimize">("backtest");
  const [optConfig, setOptConfig] =
    useState<OptimizationConfigData>(() => makeDefaultOptConfig(fromScreenerDate));
  const [optParams, setOptParams] = useState<ParamRange[]>([]);
  const [_strategyMetadata, setStrategyMetadata] = useState<any>(null);
  const [isLoadingStrategy, setIsLoadingStrategy] = useState(false);
  const [isIndicatorBrowserOpen, setIsIndicatorBrowserOpen] = useState(false);
  const [showSaveDropdown, setShowSaveDropdown] = useState(false);
  const [errorToast, setErrorToast] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    message: string;
    onConfirm: () => void;
  } | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  // Regime chart overlay toggle. The Builder itself renders no chart (the
  // strategy chart lives on /quantgen/dashboard), so when enabled this
  // surfaces the current aggregate market regime as a green/red badge in
  // the Builder. `regimeBands` is the SectorRegime[] payload that the
  // chart's `regimeBands` prop expects, so it can also be handed to a
  // chart consumer that opts into the overlay.
  const [showRegimeOverlay, setShowRegimeOverlay] = useState(false);
  const [regimes, setRegimes] = useState<SectorRegime[]>([]);

  // Fetch sector regimes once on mount so the toggle has data to reflect.
  useEffect(() => {
    fetchRegimes()
      .then(setRegimes)
      .catch(() => setRegimes([]));
  }, []);

  const regimeSummary = showRegimeOverlay
    ? summarizeRegimes(regimes)
    : { overall: 'UNKNOWN' as const, vol: 'LOW' as const };
  const regimeColor =
    regimeSummary.overall === 'BULL'
      ? 'var(--good)'
      : regimeSummary.overall === 'BEAR'
        ? 'var(--bad)'
        : 'var(--subtle)';

  // Structured error state for rich error cards
  const [structuredError, setStructuredError] = useState<{
    type: string;
    category: string;
    message: string;
    line?: number;
    line_content?: string;
    traceback?: string;
    stdout?: string;
    suggestion?: string;
    related_lesson?: string;
    fix_attempts?: number;
  } | null>(null);

  /** Replace ticker = '...' in strategy code with selected ticker */
  const replaceTickerInCode = useCallback((codeStr: string, newTicker: string): string => {
    return codeStr.replace(
      /^(\s*)ticker\s*=\s*['"][^'"]*['"]/m,
      `$1ticker = '${newTicker}'`
    );
  }, []);

  /** Replace start/end dates in strategy code with selected dates */
  const replaceDatesInCode = useCallback((codeStr: string, newStart: string, newEnd: string): string => {
    let updated = codeStr;
    // Replace start = 'YYYY-MM-DD' or start = "YYYY-MM-DD"
    updated = updated.replace(
      /^(\s*)start\s*=\s*['"]\d{4}-\d{2}-\d{2}['"]/m,
      `$1start = '${newStart}'`
    );
    // Replace end = 'YYYY-MM-DD' or end = "YYYY-MM-DD"
    updated = updated.replace(
      /^(\s*)end\s*=\s*['"]\d{4}-\d{2}-\d{2}['"]/m,
      `$1end = '${newEnd}'`
    );
    return updated;
  }, []);

  const handleInsertSnippet = useCallback((snippet: string) => {
    const editor = editorRef.current;
    if (editor) {
      const position = editor.getPosition();
      editor.executeEdits('indicator-browser', [
        {
          range: {
            startLineNumber: position.lineNumber,
            startColumn: position.column,
            endLineNumber: position.lineNumber,
            endColumn: position.column,
          },
          text: snippet + '\n',
        },
      ]);
      editor.focus();
    } else {
      // Fallback: append to code
      setCode(prev => prev + '\n' + snippet + '\n');
    }
  }, []);

  /** Render a rich error card with type badge, line info, suggestion, collapsible traceback */
  const ErrorCard = ({ error }: { error: NonNullable<typeof structuredError> }) => {
    const [showTraceback, setShowTraceback] = useState(false);
    const [showStdout, setShowStdout] = useState(false);

    const isSyntax = error.category === "syntax";
    const isValidation = error.category === "validation";
    const isSecurity = error.category === "security";

    let badgeColor = "#EF4444"; // red - execution
    let badgeBg = "rgba(239,68,68,0.08)";
    let borderColor = "rgba(239,68,68,0.15)";
    if (isSyntax) {
      badgeColor = "#F59E0B"; // amber
      badgeBg = "rgba(245,158,11,0.08)";
      borderColor = "rgba(245,158,11,0.15)";
    } else if (isValidation) {
      badgeColor = "#8B5CF6"; // purple
      badgeBg = "rgba(139,92,246,0.08)";
      borderColor = "rgba(139,92,246,0.15)";
    } else if (isSecurity) {
      badgeColor = "#DC2626"; // dark red
      badgeBg = "rgba(220,38,38,0.08)";
      borderColor = "rgba(220,38,38,0.15)";
    }

    return (
      <div
        style={{
          padding: "16px",
          borderRadius: "12px",
          backgroundColor: badgeBg,
          border: `1px solid ${borderColor}`,
          marginBottom: "12px",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            marginBottom: "10px",
          }}
        >
          <AlertCircle size={18} color={badgeColor} />
          <span
            style={{
              fontSize: "12px",
              fontWeight: 700,
              color: badgeColor,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            {error.type}
            {error.line ? ` (Line ${error.line})` : ""}
          </span>
          {error.fix_attempts != null && error.fix_attempts > 0 && (
            <span
              style={{
                fontSize: "11px",
                fontWeight: 600,
                color: "var(--muted)",
                marginLeft: "auto",
              }}
            >
              {error.fix_attempts} fix attempt(s)
            </span>
          )}
        </div>

        {/* Message */}
        <p
          style={{
            fontSize: "13px",
            color: "var(--foreground)",
            marginBottom: "10px",
            lineHeight: 1.5,
          }}
        >
          {error.message}
        </p>

        {/* Line content */}
        {error.line_content && (
          <div
            style={{
              marginBottom: "10px",
              padding: "10px 12px",
              borderRadius: "8px",
              backgroundColor: "var(--canvas)",
              border: `1px solid ${borderColor}`,
            }}
          >
            <div
              style={{
                fontSize: "11px",
                color: "var(--subtle)",
                marginBottom: "4px",
                display: "flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              <FileCode size={11} />
              Line {error.line}
            </div>
            <pre
              style={{
                margin: 0,
                fontSize: "12px",
                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                color: "var(--foreground)",
                overflowX: "auto",
              }}
            >
              {error.line_content}
            </pre>
          </div>
        )}

        {/* Suggestion */}
        {error.suggestion && (
          <div
            style={{
              marginTop: "8px",
              padding: "10px 12px",
              borderRadius: "8px",
              backgroundColor: "var(--accent-glow)",
              border: "1px solid var(--border-hover)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                marginBottom: "4px",
              }}
            >
              <Lightbulb size={13} style={{ color: "var(--accent)" }} />
              <span
                style={{
                  fontSize: "12px",
                  fontWeight: 700,
                  color: "var(--accent)",
                }}
              >
                Suggestion
              </span>
            </div>
            <span
              style={{
                fontSize: "12px",
                color: "var(--foreground)",
                lineHeight: 1.5,
              }}
            >
              {error.suggestion}
            </span>
          </div>
        )}

        {/* Collapsible Traceback */}
        {error.traceback && (
          <div style={{ marginTop: "10px" }}>
            <button
              onClick={() => setShowTraceback(!showTraceback)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "12px",
                fontWeight: 600,
                color: "var(--subtle)",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "4px 0",
              }}
            >
              {showTraceback ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
              Traceback
            </button>
            {showTraceback && (
              <pre
                style={{
                  margin: "6px 0 0",
                  padding: "10px 12px",
                  borderRadius: "8px",
                  backgroundColor: "var(--canvas)",
                  fontSize: "11px",
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                  color: "var(--muted)",
                  overflowX: "auto",
                  maxHeight: "200px",
                  overflowY: "auto",
                  lineHeight: 1.5,
                }}
              >
                {error.traceback}
              </pre>
            )}
          </div>
        )}

        {/* Collapsible Stdout */}
        {error.stdout && (
          <div style={{ marginTop: "8px" }}>
            <button
              onClick={() => setShowStdout(!showStdout)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "12px",
                fontWeight: 600,
                color: "var(--subtle)",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "4px 0",
              }}
            >
              {showStdout ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
              Stdout
            </button>
            {showStdout && (
              <pre
                style={{
                  margin: "6px 0 0",
                  padding: "10px 12px",
                  borderRadius: "8px",
                  backgroundColor: "var(--canvas)",
                  fontSize: "11px",
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                  color: "var(--muted)",
                  overflowX: "auto",
                  maxHeight: "200px",
                  overflowY: "auto",
                  lineHeight: 1.5,
                }}
              >
                {error.stdout}
              </pre>
            )}
          </div>
        )}
      </div>
    );
  };

  const { isDarkMode } = useTheme();

  // Responsive breakpoint
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  // Auto-dismiss error toast
  useEffect(() => {
    if (!errorToast) return;
    const t = setTimeout(() => setErrorToast(null), 4000);
    return () => clearTimeout(t);
  }, [errorToast]);

  // Close dropdown on click outside
  const saveDropdownRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!showSaveDropdown) return;
    const handleClick = (e: MouseEvent) => {
      if (saveDropdownRef.current && !saveDropdownRef.current.contains(e.target as Node)) {
        setShowSaveDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showSaveDropdown]);

  // Load saved state
  useEffect(() => {
    if (!isFirstLoad.current) return;
    isFirstLoad.current = false;

    const saved = localStorage.getItem("builderState");
    if (saved) {
      try {
        const state = JSON.parse(saved);
        if (state.code) setCode(replaceDatesInCode(state.code, optConfig.wfo.start_date, optConfig.wfo.end_date));
        if (state.strategyPrompt) setStrategyPrompt(state.strategyPrompt);
        if (state.currentFilename) setCurrentFilename(state.currentFilename);
        if (state.runMode) setRunMode(state.runMode);
        if (state.optConfig) {
          const base = makeDefaultOptConfig();
          setOptConfig({
            ...base,
            ...state.optConfig,
            wfo: { ...base.wfo, ...(state.optConfig.wfo || {}) },
          });
        }
        if (state.optParams) setOptParams(state.optParams);
        if (state.tickers) setTickers(state.tickers);
      } catch (e) {
        console.error("Failed to restore state:", e);
      }
    }
    loadStrategies();
  }, []);

  // Fetch latest DB date and apply exported dates from Sector Rotation
  useEffect(() => {
    const applyExportedDates = async () => {
      try {
        const data = await quantgen.latestDate();
        const latest = data.data?.latest_date || "2024-01-01";

        setOptConfig((prev) => ({
          ...prev,
          wfo: {
            ...prev.wfo,
            start_date: fromScreenerDate || prev.wfo.start_date,
            end_date: latest,
          },
        }));
      } catch (e) {
        console.error("Failed to fetch latest date:", e);
      }
    };
    applyExportedDates();
  }, []);

  // Sync code dates with optConfig dates whenever they change
  useEffect(() => {
    if (code && optConfig.wfo.start_date && optConfig.wfo.end_date) {
      const updated = replaceDatesInCode(
        code,
        optConfig.wfo.start_date,
        optConfig.wfo.end_date,
      );
      if (updated !== code) {
        setCode(updated);
      }
    }
  }, [optConfig.wfo.start_date, optConfig.wfo.end_date]);

  const saveState = useCallback(() => {
    localStorage.setItem(
      "builderState",
      JSON.stringify({
        code,
        strategyPrompt,
        currentFilename,
        runMode,
        optConfig,
        optParams,
        tickers,
      }),
    );
  }, [
    code,
    strategyPrompt,
    currentFilename,
    runMode,
    optConfig,
    optParams,
    tickers,
  ]);

  useEffect(() => {
    if (!isFirstLoad.current) saveState();
  }, [saveState]);

  // Extract parameters from code and auto-compute ranges
  useEffect(() => {
    if (!code) return;
    const lines = code.split("\n");
    let inParamsSection = false;
    const foundParams: { name: string; value: number; isInteger: boolean }[] = [];

    for (const line of lines) {
      const trimmed = line.trim();
      if (
        trimmed.toLowerCase().startsWith("# parameters") ||
        trimmed.toLowerCase().startsWith("#parameters")
      ) {
        inParamsSection = true;
        continue;
      }
      if (inParamsSection) {
        if (!trimmed) continue;
        if (trimmed.startsWith("#")) continue;
        const match = trimmed.match(
          /^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([0-9.]+)(\s*#.*)?$/,
        );
        if (match) {
          const rawValue = match[2];
          const val = parseFloat(rawValue);
          const isInteger = !rawValue.includes(".");
          foundParams.push({
            name: match[1],
            value: isNaN(val) ? 10 : val,
            isInteger,
          });
        } else break;
      }
    }

    setOptParams((prev) => {
      const existingMap = new Map(prev.map((p) => [p.name, p]));
      const newParams = foundParams.map((p) => {
        const existing = existingMap.get(p.name);
        if (existing && existing.sourceValue === p.value) {
          return existing;
        }
        const { start, stop, step } = computeAutoRange(p.value, p.isInteger);
        return { name: p.name, start, stop, step, sourceValue: p.value };
      });
      return JSON.stringify(newParams) === JSON.stringify(prev)
        ? prev
        : newParams;
    });
  }, [code]);

  // Auto-load strategy from ?load=<slug>
  useEffect(() => {
    if (!loadSlug) return;
    setIsLoadingStrategy(true);
    quantgen.strategyBySlug(loadSlug)
      .then(data => {
        if (data.success && data.data) {
          setCode(data.data.code);
          setStrategyMetadata(data.data.metadata);
          // Pre-fill optimization params from metadata
          if (data.data.metadata?.parameters) {
            const params = data.data.metadata.parameters;
            const ranges: ParamRange[] = Object.entries(params).map(([name, conf]: [string, any]) => ({
              name,
              start: conf.min ?? Math.max(1, Math.round(Number(conf.default) * 0.5)),
              stop: conf.max ?? Math.max(2, Math.round(Number(conf.default) * 1.5)),
              step: conf.step ?? (conf.type === 'int' ? 1 : 0.5),
              sourceValue: Number(conf.default),
            }));
            setOptParams(ranges);
          }
        }
      })
      .catch(() => {})
      .finally(() => setIsLoadingStrategy(false));
  }, [loadSlug]);

  const loadStrategies = async () => {
    try {
      const data = await quantgen.listStrategies();
      const list = data.data?.strategies || data.strategies || [];
      setStrategies(Array.isArray(list) ? list : []);
    } catch (e) {
      console.error("Failed to load strategies:", e);
    }
  };

  const handleGenerate = async () => {
    if (!strategyPrompt.trim()) return;
    setIsGenerating(true);
    setStructuredError(null);
    try {
      const data = await quantgen.generate({
        prompt: strategyPrompt,
        tickers: tickers.split(",").map((t) => t.trim()),
        start_date: optConfig.wfo.start_date,
        end_date: optConfig.wfo.end_date,
      });
      if (data.success && data.data?.code) {
        let generatedCode = replaceDatesInCode(data.data.code, optConfig.wfo.start_date, optConfig.wfo.end_date);
        generatedCode = replaceTickerInCode(generatedCode, tickers.split(",")[0].trim());
        setCode(generatedCode);
        const attempts = data.data?.fix_attempts || 0;
        const lessons = data.data?.lessons_applied || [];
        let msg = data.data.output || "Strategy generated successfully!";
        if (attempts > 0) {
          msg = `✅ Strategy generated and auto-fixed after ${attempts} attempt(s).`;
          if (lessons.length > 0) {
            msg += `\nApplied lesson: ${lessons.join(", ")}`;
          }
          msg += `\n\n${data.data.output || ""}`;
        }
        setOutput(msg);
      } else {
        // Parse structured error details if available
        const details = data.error?.details;
        if (details && typeof details === "object") {
          setStructuredError({
            type: details.type || "UNKNOWN",
            category: details.category || "execution",
            message: details.message || data.error?.message || "Unknown error",
            line: details.line,
            line_content: details.line_content,
            traceback: details.traceback,
            stdout: details.stdout,
            suggestion: details.suggestion,
            related_lesson: details.related_lesson,
            fix_attempts: data.data?.fix_attempts,
          });
        }
        setOutput(
          `GENERATION FAILED\n\nError: ${data.error?.message || data.error || "Unknown error"}\n\nPartial Output:\n${data.data?.output || ""}`,
        );
      }
    } catch (e: any) {
      setOutput(`API Error: ${e.message}`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleRun = async () => {
    if (!code) return;
    setIsRunning(true);
    setStructuredError(null);
    try {
      const tickerList = tickers.split(",").map((t) => t.trim()).filter(Boolean);
      let body: any = { code, tickers: tickerList };
      if (runMode === "optimize") {
        const strategy_params: Record<
          string,
          { start: number; stop: number; step: number }
        > = {};
        optParams.forEach((p) => {
          if (p.name)
            strategy_params[p.name] = {
              start: p.start,
              stop: p.stop,
              step: p.step,
            };
        });
        body = { code, strategy_params, config: optConfig, tickers: tickerList };
      }
      const data =
        runMode === "optimize"
          ? await quantgen.optimize(body as import("@/lib/api").OptimizePayload)
          : await quantgen.run(body as import("@/lib/api").RunPayload);
      if (data.output) setOutput(data.output);
      if (data.data?.output) setOutput(data.data.output);
      const err = data.error;
      if (err) {
        // Parse structured error details if available
        const details = err.details;
        if (details && typeof details === "object") {
          setStructuredError({
            type: details.type || "UNKNOWN",
            category: details.category || "execution",
            message: details.message || err.message || "Unknown error",
            line: details.line,
            line_content: details.line_content,
            traceback: details.traceback,
            stdout: details.stdout,
            suggestion: details.suggestion,
            related_lesson: details.related_lesson,
          });
        }
        setOutput((prev) => prev + `\n\nERROR:\n${err.message || err}`);
      }
      if (
        data.data?.stats ||
        data.data?.best_equity ||
        data.data?.equity ||
        data.data?.windows
      ) {
        const maxEquityPoints = 1000;
        const maxTrades = 500;
        const equity = (data.data.equity || []).slice(0, maxEquityPoints);
        const bestEquity = (data.data.best_equity || []).slice(
          0,
          maxEquityPoints,
        );
        const trades = (data.data.trades || []).slice(0, maxTrades);
        const runData = {
          stats: data.data.stats,
          equity,
          ohlcv: data.data.ohlcv,
          drawdown: data.data.drawdown,
          benchmark_drawdown: data.data.benchmark_drawdown,
          trades,
          indicators: data.data.indicators || [],
          tickers: tickerList,
          optimization:
            runMode === "optimize"
              ? {
                  mode: data.data.mode,
                  heatmap: data.data.heatmap?.slice(0, 50),
                  windows: data.data.windows,
                  best_equity: bestEquity,
                  oos_equity: data.data.oos_equity,
                  benchmark_equity: data.data.benchmark_equity,
                  stats: data.data.stats,
                  equity,
                  ohlcv: data.data.ohlcv,
                  indicators: data.data.indicators || [],
                  trades,
                }
              : null,
          output: data.data.output,
        };
        try {
          localStorage.setItem("lastRunData", JSON.stringify(runData));
        } catch {}
        navigate("/quantgen/dashboard");
      }
    } catch (e: any) {
      setOutput(`Execution Error: ${e.message}`);
    } finally {
      setIsRunning(false);
    }
  };

  const handleSave = async () => {
    if (currentFilename) await saveStrategy(currentFilename);
    else handleSaveAs();
  };

  const [savePrompt, setSavePrompt] = useState<{ open: boolean; name: string }>({ open: false, name: "" });

  const handleSaveAs = async () => {
    setSavePrompt({ open: true, name: "" });
  };

  const submitSaveAs = async () => {
    if (savePrompt.name.trim()) {
      await saveStrategy(savePrompt.name.trim());
    }
    setSavePrompt({ open: false, name: "" });
  };

  const saveStrategy = async (name: string) => {
    try {
      await quantgen.saveStrategy(name, code);
      const safeName = name.endsWith(".py") ? name : `${name}.py`;
      setCurrentFilename(safeName);
      setOutput((prev) => prev + `\nSaved to ${safeName}`);
      loadStrategies();
    } catch (e: any) {
      setErrorToast(`Failed: ${e.message}`);
    }
  };

  const handleLoad = async (name: string) => {
    try {
      const data = await quantgen.loadStrategy(name);
      if (data.data?.code) {
        let loadedCode = data.data.code;
        loadedCode = replaceDatesInCode(loadedCode, optConfig.wfo.start_date, optConfig.wfo.end_date);
        setCode(loadedCode);
        setCurrentFilename(name);
        setStrategyPrompt(`Loaded: ${name}`);
        setOutput(`Loaded ${name}`);
      }
    } catch {
      setErrorToast("Failed to load strategy");
    }
  };

  const handleDelete = (name: string) => {
    setConfirmDialog({
      open: true,
      message: `Delete ${name}?`,
      onConfirm: async () => {
        try {
          await quantgen.deleteStrategy(name);
          loadStrategies();
        } catch {
          setErrorToast("Failed to delete strategy");
        }
        setConfirmDialog(null);
      },
    });
  };

  return (
    <div
      className="h-full flex flex-col"
      style={{ backgroundColor: "var(--canvas)" }}
    >
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: "12px",
          padding: "16px 24px 24px",
          overflow: "hidden",
        }}
      >
        {/* Input Bar — compact horizontal layout */}
        <div
          style={{
            padding: "16px 20px",
            borderRadius: "14px",
            backgroundColor: "var(--surface)",
            border: "1px solid var(--border)",
            flexShrink: 0,
          }}
        >
          <label
            style={{
              display: "block",
              fontSize: "12px",
              fontWeight: 600,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "var(--subtle)",
              marginBottom: "8px",
            }}
          >
            Strategy Description
          </label>
          <textarea
            value={strategyPrompt}
            onChange={(e) => setStrategyPrompt(e.target.value)}
            placeholder="e.g. Buy when RSI < 30 and SMA crossover occurs..."
            rows={2}
            className="w-full border rounded-lg p-2.5 text-sm focus:border-emerald-500 focus:outline-none resize-none"
            style={{
              backgroundColor: "var(--canvas)",
              borderColor: "var(--border)",
              color: "var(--foreground)",
            }}
          />
        </div>

        {/* Main Workspace */}
        <div
          className="flex-1 grid"
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "7fr 6fr",
            gap: "12px",
            minHeight: 0,
            overflowY: isMobile ? "auto" : "hidden",
          }}
        >
          {/* Left: Editor + Chat */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "12px",
              minHeight: 0,
              overflow: "hidden",
            }}
          >
            {/* Tickers + Generate Bar */}
            <div
              style={{
                display: "flex",
                gap: "12px",
                alignItems: "end",
                padding: "12px 16px",
                borderRadius: "12px",
                backgroundColor: "var(--surface)",
                border: "1px solid var(--border)",
                flexShrink: 0,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <label
                  style={{
                    display: "block",
                    fontSize: "12px",
                    fontWeight: 600,
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    color: "var(--subtle)",
                    marginBottom: "8px",
                  }}
                >
                  Tickers
                </label>
                {importedTickers.length > 0 && (
                  <div style={{ marginBottom: '8px' }}>
                    {/* Summary badge when collapsed */}
                    {shouldCollapse && !showAllTickers && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                        <span
                          style={{
                            padding: '4px 10px',
                            borderRadius: '6px',
                            fontSize: '12px',
                            fontWeight: 600,
                            border: '1px solid var(--border)',
                            backgroundColor: 'var(--accent)',
                            color: 'var(--accent-ink)',
                          }}
                        >
                          {tickerCount} ticker{tickerCount !== 1 ? 's' : ''} imported
                        </span>
                        <button
                          onClick={() => setShowAllTickers(true)}
                          style={{
                            padding: '4px 10px',
                            borderRadius: '6px',
                            fontSize: '12px',
                            fontWeight: 600,
                            border: '1px solid var(--border)',
                            cursor: 'pointer',
                            backgroundColor: 'var(--canvas)',
                            color: 'var(--foreground)',
                          }}
                        >
                          ▼ Show All
                        </button>
                      </div>
                    )}

                    {/* Pill list: expanded or always-visible for small counts */}
                    {(showAllTickers || !shouldCollapse) && (
                      <div style={{ marginBottom: '8px' }}>
                        <div
                          style={{
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: '6px',
                            maxHeight: shouldCollapse ? '200px' : undefined,
                            overflowY: shouldCollapse ? 'auto' : undefined,
                            paddingBottom: '4px',
                          }}
                        >
                          {importedTickers.map((t) => (
                            <button
                              key={t}
                              onClick={() => {
                                setTickers(t);
                                if (code) {
                                  let updated = replaceTickerInCode(code, t);
                                  updated = replaceDatesInCode(updated, optConfig.wfo.start_date, optConfig.wfo.end_date);
                                  setCode(updated);
                                }
                              }}
                              style={{
                                padding: '4px 10px',
                                borderRadius: '6px',
                                fontSize: '12px',
                                fontWeight: 600,
                                border: '1px solid var(--border)',
                                cursor: 'pointer',
                                backgroundColor: tickers === t ? 'var(--accent)' : 'var(--canvas)',
                                color: tickers === t ? 'var(--accent-ink)' : 'var(--foreground)',
                                transition: 'all 0.15s ease',
                                flexShrink: 0,
                              }}
                            >
                              {t}
                            </button>
                          ))}
                        </div>

                        {/* Hide button (only shown when expanded from collapsed state) */}
                        {shouldCollapse && showAllTickers && (
                          <button
                            onClick={() => setShowAllTickers(false)}
                            style={{
                              padding: '4px 10px',
                              borderRadius: '6px',
                              fontSize: '12px',
                              fontWeight: 600,
                              border: '1px solid var(--border)',
                              cursor: 'pointer',
                              backgroundColor: 'var(--canvas)',
                              color: 'var(--foreground)',
                              marginTop: '4px',
                            }}
                          >
                            ▲ Hide
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <input
                  type="text"
                  value={tickers}
                  onChange={(e) => {
                    const val = e.target.value;
                    setTickers(val);
                    if (code && !val.includes(",") && val.trim().length > 0) {
                      setCode(replaceTickerInCode(code, val.trim()));
                    }
                  }}
                  placeholder="AAPL, MSFT"
                  style={{
                    width: "100%",
                    padding: "10px 14px",
                    borderRadius: "8px",
                    fontSize: "14px",
                    border: "1px solid var(--border)",
                    backgroundColor: "var(--canvas)",
                    color: "var(--foreground)",
                    outline: "none",
                  }}
                />
              </div>

              {/* Date Range */}
              <div style={{ display: "flex", gap: "8px", minWidth: 0 }}>
                <div>
                  <label
                    style={{
                      display: "block",
                      fontSize: "12px",
                      fontWeight: 600,
                      letterSpacing: "0.15em",
                      textTransform: "uppercase",
                      color: "var(--subtle)",
                      marginBottom: "8px",
                    }}
                  >
                    Start
                  </label>
                  <input
                    type="date"
                    value={optConfig.wfo.start_date}
                    onChange={(e) => {
                      const val = e.target.value;
                      setOptConfig((prev) => ({
                        ...prev,
                        wfo: { ...prev.wfo, start_date: val },
                      }));
                      if (code) setCode(replaceDatesInCode(code, val, optConfig.wfo.end_date));
                    }}
                    style={{
                      padding: "10px 14px",
                      borderRadius: "8px",
                      fontSize: "14px",
                      border: "1px solid var(--border)",
                      backgroundColor: "var(--canvas)",
                      color: "var(--foreground)",
                      outline: "none",
                    }}
                  />
                </div>
                <div>
                  <label
                    style={{
                      display: "block",
                      fontSize: "12px",
                      fontWeight: 600,
                      letterSpacing: "0.15em",
                      textTransform: "uppercase",
                      color: "var(--subtle)",
                      marginBottom: "8px",
                    }}
                  >
                    End
                  </label>
                  <input
                    type="date"
                    value={optConfig.wfo.end_date}
                    onChange={(e) => {
                      const val = e.target.value;
                      setOptConfig((prev) => ({
                        ...prev,
                        wfo: { ...prev.wfo, end_date: val },
                      }));
                      if (code) setCode(replaceDatesInCode(code, optConfig.wfo.start_date, val));
                    }}
                    style={{
                      padding: "10px 14px",
                      borderRadius: "8px",
                      fontSize: "14px",
                      border: "1px solid var(--border)",
                      backgroundColor: "var(--canvas)",
                      color: "var(--foreground)",
                      outline: "none",
                    }}
                  />
                </div>
              </div>

              <button
                onClick={handleGenerate}
                disabled={isGenerating || !strategyPrompt.trim()}
                style={{
                  padding: "10px 20px",
                  borderRadius: "8px",
                  fontSize: "14px",
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  border: "none",
                  cursor:
                    !strategyPrompt.trim() || isGenerating
                      ? "not-allowed"
                      : "pointer",
                  backgroundColor: isGenerating
                    ? "var(--surface-overlay)"
                    : "var(--accent)",
                  color: isGenerating ? "var(--muted)" : "var(--accent-ink)",
                  opacity: !strategyPrompt.trim() ? 0.4 : 1,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
              >
                {isGenerating ? (
                  <Activity size={18} className="animate-spin" />
                ) : (
                  <Sparkles size={18} />
                )}
                Generate Strategy
              </button>
            </div>
            {/* Code Editor */}
            <div
              className="rounded-xl overflow-hidden shadow-sm flex flex-col"
              style={{
                flex: 1,
                minHeight: 0,
                backgroundColor: "var(--surface)",
                border: "1px solid var(--border)",
              }}
            >
              {/* Editor header with inline run mode toggle */}
              <div
                style={{
                  height: "40px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "0 12px",
                  backgroundColor: "var(--surface-raised)",
                  borderBottom: "1px solid var(--border)",
                  flexShrink: 0,
                }}
              >
                <div
                  style={{ display: "flex", alignItems: "center", gap: "10px" }}
                >
                  <span
                    style={{
                      fontSize: "12px",
                      fontWeight: 600,
                      letterSpacing: "0.15em",
                      textTransform: "uppercase",
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      color: "var(--subtle)",
                    }}
                  >
                    <Terminal size={14} />
                    {currentFilename ? (
                      <span style={{ color: "var(--accent)" }}>
                        {currentFilename}
                      </span>
                    ) : (
                      "Untitled"
                    )}
                  </span>
                  {/* Run mode inline toggle */}
                  <div
                    style={{
                      display: "inline-flex",
                      borderRadius: "6px",
                      padding: "2px",
                      backgroundColor: "var(--canvas)",
                      marginLeft: "8px",
                    }}
                  >
                    <button
                      onClick={() => setRunMode("backtest")}
                      style={{
                        padding: "6px 14px",
                        fontSize: "13px",
                        fontWeight: 600,
                        borderRadius: "4px",
                        border: "none",
                        cursor: "pointer",
                        backgroundColor:
                          runMode === "backtest"
                            ? "var(--accent)"
                            : "transparent",
                        color:
                          runMode === "backtest" ? "var(--accent-ink)" : "var(--muted)",
                        transition: "all 0.15s ease",
                      }}
                      aria-pressed={runMode === "backtest"}
                    >
                      Backtest
                    </button>
                    <button
                      onClick={() => setRunMode("optimize")}
                      style={{
                        padding: "6px 14px",
                        fontSize: "13px",
                        fontWeight: 600,
                        borderRadius: "4px",
                        border: "none",
                        cursor: "pointer",
                        backgroundColor:
                          runMode === "optimize"
                            ? "var(--accent)"
                            : "transparent",
                        color:
                          runMode === "optimize" ? "var(--accent-ink)" : "var(--muted)",
                        transition: "all 0.15s ease",
                      }}
                      aria-pressed={runMode === "optimize"}
                    >
                      Optimize
                    </button>
                  </div>
                </div>
                {currentFilename && (
                  <button
                    onClick={() => {
                      setCode("");
                      setCurrentFilename(null);
                      setStrategyPrompt("");
                      setOutput("");
                    }}
                    style={{
                      fontSize: "12px",
                      color: "var(--muted)",
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.color = "var(--foreground)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.color = "var(--muted)")
                    }
                  >
                    New
                  </button>
                )}
              </div>
              <div style={{ flex: 1, minHeight: 0 }}>
                {isLoadingStrategy ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--muted)', fontSize: '14px' }}>
                    Loading strategy...
                  </div>
                ) : (
                  <Editor
                    height="100%"
                    defaultLanguage="python"
                    theme={isDarkMode ? "vs-dark" : "vs"}
                    value={code}
                    onChange={(val) => setCode(val || "")}
                    onMount={(editor) => { editorRef.current = editor; }}
                    options={{
                      minimap: { enabled: false },
                      fontSize: 16,
                      scrollBeyondLastLine: false,
                    }}
                  />
                )}
              </div>
            </div>

            {/* Terminal Redirect Banner */}
            <TerminalRedirectBanner />
          </div>

          {/* Right Panel */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "12px",
              minHeight: 0,
              overflow: "hidden",
            }}
          >
            {/* Regime Overlay Toggle */}
            <div
              style={{
                flexShrink: 0,
                padding: "10px 14px",
                borderRadius: "12px",
                backgroundColor: "var(--surface)",
                border: "1px solid var(--border)",
                display: "flex",
                alignItems: "center",
                gap: "10px",
              }}
            >
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  cursor: "pointer",
                  fontSize: "13px",
                  fontWeight: 600,
                  color: "var(--foreground)",
                }}
              >
                <input
                  type="checkbox"
                  checked={showRegimeOverlay}
                  onChange={(e) => setShowRegimeOverlay(e.target.checked)}
                  style={{ width: "16px", height: "16px", cursor: "pointer", accentColor: "var(--accent)" }}
                />
                Regime Overlay
              </label>
              {showRegimeOverlay && (
                <span
                  style={{
                    marginLeft: "auto",
                    padding: "2px 8px",
                    borderRadius: "6px",
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: regimeColor,
                    border: `1px solid ${regimeColor}`,
                    backgroundColor: "rgba(0,0,0,0.4)",
                  }}
                >
                  {regimeSummary.overall}
                  {regimeSummary.vol === 'HIGH' ? ' · Vol High' : ''}
                </span>
              )}
            </div>

            {/* Run Button */}
            <button
              onClick={handleRun}
              disabled={isRunning || !code}
              style={{
                padding: "12px 20px",
                borderRadius: "10px",
                fontWeight: 600,
                fontSize: "14px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                border: "none",
                cursor: isRunning || !code ? "not-allowed" : "pointer",
                backgroundColor: isRunning
                  ? "var(--surface-overlay)"
                  : "var(--accent)",
                color: isRunning ? "var(--muted)" : "var(--accent-ink)",
                opacity: !code ? 0.4 : 1,
                flexShrink: 0,
              }}
            >
              {isRunning ? (
                <Activity size={14} className="animate-spin" />
              ) : runMode === "optimize" ? (
                <Microscope size={14} />
              ) : (
                <Play size={14} />
              )}
              {isRunning
                ? "Running..."
                : runMode === "optimize"
                  ? "Run Optimization"
                  : "Run Backtest"}
            </button>

            {/* Save with dropdown */}
            <div style={{ position: "relative", flexShrink: 0 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 36px",
                  gap: "4px",
                }}
              >
                <button
                  onClick={handleSave}
                  disabled={!code}
                  style={{
                    padding: "10px 16px",
                    borderRadius: "8px",
                    fontSize: "13px",
                    fontWeight: 600,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "6px",
                    border: "1px solid var(--border)",
                    cursor: !code ? "not-allowed" : "pointer",
                    backgroundColor: "var(--surface)",
                    color: "var(--foreground)",
                    opacity: !code ? 0.4 : 1,
                  }}
                >
                  <Save size={13} /> {currentFilename ? "Save" : "Save As"}
                </button>
                <button
                  onClick={() => setShowSaveDropdown(!showSaveDropdown)}
                  disabled={!code}
                  aria-label="Save options"
                  aria-haspopup="menu"
                  aria-expanded={showSaveDropdown}
                  style={{
                    padding: "8px",
                    borderRadius: "8px",
                    border: "1px solid var(--border)",
                    cursor: !code ? "not-allowed" : "pointer",
                    backgroundColor: "var(--surface)",
                    color: "var(--foreground)",
                    opacity: !code ? 0.4 : 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <ChevronDown size={12} />
                </button>
              </div>
              {showSaveDropdown && code && (
                <div
                  style={{
                    position: "absolute",
                    top: "100%",
                    right: 0,
                    marginTop: "4px",
                    width: "200px",
                    borderRadius: "10px",
                    backgroundColor: "var(--surface-overlay)",
                    border: "1px solid var(--border)",
                    boxShadow: "0 12px 32px rgba(0,0,0,0.4)",
                    zIndex: 20,
                    overflow: "hidden",
                  }}
                >
                  <button
                    onClick={() => {
                      handleSave();
                      setShowSaveDropdown(false);
                    }}
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      fontSize: "14px",
                      textAlign: "left",
                      background: "none",
                      border: "none",
                      color: "var(--foreground)",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.backgroundColor = "var(--surface)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.backgroundColor = "transparent")
                    }
                  >
                    <Save size={13} /> Save
                  </button>
                  <button
                    onClick={() => {
                      handleSaveAs();
                      setShowSaveDropdown(false);
                    }}
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      fontSize: "14px",
                      textAlign: "left",
                      background: "none",
                      border: "none",
                      color: "var(--foreground)",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.backgroundColor = "var(--surface)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.backgroundColor = "transparent")
                    }
                  >
                    <FilePlus size={13} /> Save As...
                  </button>
                </div>
              )}
            </div>

            {/* Optimization Config (only visible when optimize mode) */}
            {runMode === "optimize" && (
              <div
                className="rounded-xl overflow-hidden shadow-sm"
                style={{
                  flexShrink: 0,
                  backgroundColor: "var(--surface)",
                  border: "1px solid var(--border)",
                }}
              >
                <OptimizationConfig
                  config={optConfig}
                  setConfig={setOptConfig}
                  params={optParams}
                  setParams={setOptParams}
                />
              </div>
            )}

            {/* Indicator Browser */}
            <div
              className="rounded-xl overflow-hidden flex flex-col"
              style={{
                flexShrink: 0,
                backgroundColor: "var(--surface)",
                border: "1px solid var(--border)",
              }}
            >
              <button
                onClick={() => setIsIndicatorBrowserOpen(!isIndicatorBrowserOpen)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  width: "100%",
                  padding: "10px 14px",
                  border: "none",
                  backgroundColor: "var(--surface-raised)",
                  color: "var(--foreground)",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: "pointer",
                  textAlign: "left",
                  letterSpacing: "0.15em",
                  textTransform: "uppercase",
                }}
              >
                <Box size={14} />
                Indicator Browser
                <span style={{ marginLeft: "auto" }}>
                  {isIndicatorBrowserOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </span>
              </button>
              {isIndicatorBrowserOpen && (
                <div style={{
                  padding: "12px",
                  maxHeight: "320px",
                  overflowY: "auto",
                }}>
                  <IndicatorBrowser onInsertSnippet={handleInsertSnippet} />
                </div>
              )}
            </div>

            {/* Strategy Library */}
            <div
              className="rounded-xl overflow-hidden flex flex-col"
              style={{
                flex: "1 1 0",
                minHeight: 0,
                backgroundColor: "var(--surface)",
                border: "1px solid var(--border)",
              }}
            >
              <div
                style={{
                  padding: "10px 14px",
                  fontSize: "12px",
                  fontWeight: 600,
                  letterSpacing: "0.15em",
                  textTransform: "uppercase",
                  color: "var(--subtle)",
                  backgroundColor: "var(--surface-raised)",
                  borderBottom: "1px solid var(--border)",
                  flexShrink: 0,
                }}
              >
                Library ({strategies.length})
              </div>
              <div style={{ flex: 1, overflowY: "auto", padding: "6px" }}>
                {strategies.length === 0 ? (
                  <div
                    style={{
                      padding: "16px 12px",
                      textAlign: "center",
                      fontSize: "14px",
                      color: "var(--muted)",
                    }}
                  >
                    No saved strategies. Generate a strategy above, then save it
                    here.
                  </div>
                ) : (
                  strategies.map((s) => (
                    <div
                      key={s}
                      role="button"
                      tabIndex={0}
                      onClick={() => handleLoad(s)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          handleLoad(s);
                        }
                      }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "9px 12px",
                        borderRadius: "8px",
                        cursor: "pointer",
                        color: "var(--foreground)",
                        fontSize: "14px",
                        marginBottom: "2px",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.backgroundColor =
                          "var(--surface-overlay)")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.backgroundColor = "transparent")
                      }
                    >
                      <span
                        style={{
                          flex: 1,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {s}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(s);
                        }}
                        aria-label={`Delete strategy ${s}`}
                        style={{
                          padding: "6px",
                          borderRadius: "6px",
                          background: "none",
                          border: "none",
                          color: "var(--danger)",
                          cursor: "pointer",
                          opacity: 0.35,
                          minWidth: "32px",
                          minHeight: "32px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.opacity = "1";
                          e.currentTarget.style.backgroundColor =
                            "var(--danger-hover)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.opacity = "0.35";
                          e.currentTarget.style.backgroundColor = "transparent";
                        }}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Console Output */}
            <div
              className="rounded-xl overflow-hidden flex flex-col font-mono text-xs"
              style={{
                flex: "1 1 0",
                minHeight: 0,
                backgroundColor: "var(--canvas)",
                border: "1px solid var(--border)",
              }}
            >
              <div
                style={{
                  padding: "8px 12px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  backgroundColor: "var(--surface-raised)",
                  borderBottom: "1px solid var(--border)",
                  flexShrink: 0,
                }}
              >
                <span
                  style={{
                    fontSize: "12px",
                    fontWeight: 600,
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    color: "var(--subtle)",
                  }}
                >
                  Console
                </span>
                <div
                  style={{ display: "flex", alignItems: "center", gap: "8px" }}
                >
                  {isRunning && (
                    <span
                      style={{ color: "var(--accent)", fontSize: "12px" }}
                      className="animate-pulse"
                    >
                      Running...
                    </span>
                  )}
                  {output && (
                    <button
                      onClick={() => {
                        setOutput("");
                        setStructuredError(null);
                      }}
                      aria-label="Clear console output"
                      style={{
                        fontSize: "12px",
                        color: "var(--muted)",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.color = "var(--foreground)")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.color = "var(--muted)")
                      }
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
              <div
                style={{
                  flex: 1,
                  overflow: "auto",
                  padding: "10px 12px",
                  color: "var(--muted)",
                  whiteSpace: "pre-wrap",
                  fontSize: "14px",
                  lineHeight: 1.5,
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                }}
              >
                {structuredError && <ErrorCard error={structuredError} />}
                {output || (
                  <span style={{ opacity: 0.5, color: "var(--muted)" }}>
                    Waiting for execution...
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Error Toast */}
      {errorToast && (
        <div
          style={{
            position: "fixed",
            bottom: "24px",
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 50,
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "12px 20px",
            borderRadius: "14px",
            backgroundColor: "rgba(239,68,68,0.1)",
            border: "1px solid rgba(239,68,68,0.2)",
          }}
        >
          <AlertCircle style={{ width: "18px", height: "18px", color: "#EF4444" }} />
          <span style={{ fontSize: "15px", fontWeight: 600, color: "#EF4444" }}>{errorToast}</span>
        </div>
      )}

      {/* Confirm Dialog */}
      {confirmDialog?.open && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 60,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(0,0,0,0.6)",
            backdropFilter: "blur(4px)",
          }}
          onClick={() => setConfirmDialog(null)}
        >
          <div
            style={{
              padding: "24px",
              borderRadius: "20px",
              backgroundColor: "var(--surface)",
              border: "1px solid var(--border)",
              maxWidth: "400px",
              width: "90%",
              boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <p
              style={{
                fontSize: "17px",
                fontWeight: 600,
                color: "var(--foreground)",
                marginBottom: "24px",
              }}
            >
              {confirmDialog.message}
            </p>
            <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setConfirmDialog(null)}
                style={{
                  padding: "10px 20px",
                  borderRadius: "10px",
                  fontSize: "14px",
                  fontWeight: 600,
                  border: "1px solid var(--border)",
                  backgroundColor: "transparent",
                  color: "var(--foreground)",
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDialog.onConfirm}
                style={{
                  padding: "10px 20px",
                  borderRadius: "10px",
                  fontSize: "14px",
                  fontWeight: 600,
                  border: "none",
                  backgroundColor: "var(--danger)",
                  color: "#ffffff",
                  cursor: "pointer",
                }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Inline Save Prompt */}
      {savePrompt.open && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 60,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(0,0,0,0.6)",
            backdropFilter: "blur(4px)",
          }}
          onClick={() => setSavePrompt({ open: false, name: "" })}
        >
          <div
            style={{
              padding: "24px",
              borderRadius: "20px",
              backgroundColor: "var(--surface)",
              border: "1px solid var(--border)",
              maxWidth: "400px",
              width: "90%",
              boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <label
              style={{
                display: "block",
                fontSize: "12px",
                fontWeight: 600,
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                color: "var(--subtle)",
                marginBottom: "8px",
              }}
            >
              Strategy Name
            </label>
            <input
              type="text"
              value={savePrompt.name}
              onChange={(e) => setSavePrompt({ ...savePrompt, name: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitSaveAs();
                if (e.key === "Escape") setSavePrompt({ open: false, name: "" });
              }}
              autoFocus
              placeholder="e.g. sma_crossover"
              style={{
                width: "100%",
                padding: "12px 14px",
                borderRadius: "10px",
                fontSize: "14px",
                border: "1px solid var(--border)",
                backgroundColor: "var(--canvas)",
                color: "var(--foreground)",
                outline: "none",
                marginBottom: "20px",
              }}
            />
            <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setSavePrompt({ open: false, name: "" })}
                style={{
                  padding: "10px 20px",
                  borderRadius: "10px",
                  fontSize: "14px",
                  fontWeight: 600,
                  border: "1px solid var(--border)",
                  backgroundColor: "transparent",
                  color: "var(--foreground)",
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={submitSaveAs}
                disabled={!savePrompt.name.trim()}
                style={{
                  padding: "10px 20px",
                  borderRadius: "10px",
                  fontSize: "14px",
                  fontWeight: 600,
                  border: "none",
                  backgroundColor: "var(--accent)",
                  color: "var(--accent-ink)",
                  cursor: !savePrompt.name.trim() ? "not-allowed" : "pointer",
                  opacity: !savePrompt.name.trim() ? 0.4 : 1,
                }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
