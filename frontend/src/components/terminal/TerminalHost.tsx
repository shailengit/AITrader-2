import { API_TOKEN } from "../../lib/api";
import { useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";
import { FloatingPanel, type PanelState } from "./FloatingPanel";
import { TerminalHypothesisBanner } from "../shared/TerminalHypothesisBanner";
import { useTheme } from "../../context/ThemeContext";
import {
  TrendingUp,
  Sparkles,
  Calendar,
  Code,
  Gauge,
  BookOpen,
  FlaskConical,
  LayoutDashboard,
} from "lucide-react";

const NAV_ITEMS = [
  { label: "Home", icon: LayoutDashboard, path: "/" },
  { label: "Sectors", icon: TrendingUp, path: "/sectors" },
  { label: "Screener", icon: Sparkles, path: "/screener" },
  { label: "Earnings", icon: Calendar, path: "/earnings" },
  { label: "QuantGen", icon: Code, path: "/quantgen" },
  { label: "Markov", icon: Gauge, path: "/markov" },
  { label: "Coach", icon: BookOpen, path: "/coach" },
  { label: "Strategy Lab", icon: FlaskConical, path: "/strategy-lab" },
] as const;

const WS_BASE = (() => {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/terminal/ws`;
})();

const MAX_AUTO_RECONNECTS = 8;
const RECONNECT_BASE_DELAY_MS = 250;
const RECONNECT_MAX_DELAY_MS = 4000;

const STORAGE_KEY_SESSION = "terminal_session_id";
const STORAGE_KEY_PANEL = "terminal_panel_state";

function defaultPanelState(): PanelState {
  // Start minimized (a small pill in the corner) so the terminal never
  // blocks page content on load. Click the pill to expand; the expanded
  // panel is draggable (title bar) and resizable (corner handle).
  return {
    x: Math.max(0, window.innerWidth - 240),
    y: Math.max(0, window.innerHeight - 80),
    width: 600,
    height: 400,
    minimized: true,
  };
}

function loadPanelState(): PanelState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PANEL);
    if (!raw) return defaultPanelState();
    const parsed = JSON.parse(raw) as Partial<PanelState>;
    return {
      x: Number(parsed.x) || 0,
      y: Number(parsed.y) || 0,
      width: Number(parsed.width) || 600,
      height: Number(parsed.height) || 400,
      minimized: Boolean(parsed.minimized),
    };
  } catch {
    return defaultPanelState();
  }
}

export function TerminalHost() {
  const { isDarkMode } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const mode: "fullpage" | "floating" =
    location.pathname === "/terminal" ? "fullpage" : "floating";

  // === sessionId (in sessionStorage, lazy) ===
  const [sessionId, setSessionId] = useState<string>(() => {
    const stored = sessionStorage.getItem(STORAGE_KEY_SESSION);
    if (stored) return stored;
    const fresh = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY_SESSION, fresh);
    return fresh;
  });

  // === status ===
  const [status, setStatus] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const [exitCode, setExitCode] = useState<number | undefined>();

  // === terminal dimensions ===
  const [dims, setDims] = useState<{ cols: number; rows: number }>({ cols: 80, rows: 24 });
  const [editingDims, setEditingDims] = useState(false);
  const [editCols, setEditCols] = useState("80");
  const [editRows, setEditRows] = useState("24");

  // === panel state ===
  const [panelState, setPanelState] = useState<PanelState>(() => loadPanelState());

  // === xterm + WS refs (moved from Terminal.tsx; the mode change
  // between fullpage and floating only rerenders the wrapper, never
  // touches these refs) ===
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionallyClosedRef = useRef(false);

  const handleReady = useCallback(() => setStatus("connected"), []);
  const handleDisconnected = useCallback((code?: number) => {
    setStatus("disconnected");
    setExitCode(code);
  }, []);

  // === xterm + WS lifecycle — runs ONCE per sessionId, regardless of mode ===
  useEffect(() => {
    if (!containerRef.current) return;
    intentionallyClosedRef.current = false;

    const term = new Terminal({
      cursorBlink: true,
      cursorStyle: "block",
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
      theme: {
        background: "#0a0a0a",
        foreground: "#e0e0e0",
        cursor: "#10B981",
        selectionBackground: "rgba(16, 185, 129, 0.3)",
        black: "#000000",
        red: "#ff5555",
        green: "#50fa7b",
        yellow: "#f1fa8c",
        blue: "#bd93f9",
        magenta: "#ff79c6",
        cyan: "#8be9fd",
        white: "#f8f8f2",
        brightBlack: "#6272a4",
        brightRed: "#ff6e6e",
        brightGreen: "#69ff94",
        brightYellow: "#ffffa5",
        brightBlue: "#d6acff",
        brightMagenta: "#ff92df",
        brightCyan: "#a4ffff",
        brightWhite: "#ffffff",
      },
      allowTransparency: true,
      convertEol: true,
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    termRef.current = term;

    // Only open/fit once the container actually has dimensions. Opening xterm
    // on a 0x0 container (e.g. the panel is minimized or not yet laid out)
    // leaves its renderer uninitialized and crashes on the first write with
    // "Cannot read properties of undefined (reading 'dimensions')".
    const safeFit = () => {
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (rect.width < 10 || rect.height < 10) return;
      try {
        fitAddon.fit();
      } catch {
        // container not ready — ignore
      }
    };

    let opened = false;
    const openTerminal = () => {
      if (opened) return true;
      const el = containerRef.current;
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      if (rect.width < 10 || rect.height < 10) return false; // not laid out yet
      try {
        term.open(el);
        safeFit();
        opened = true;
        openSocket();
        return true;
      } catch {
        return false;
      }
    };

    const openSocket = () => {
      const ws = new WebSocket(`${WS_BASE}?session=${sessionId}&token=${encodeURIComponent(API_TOKEN)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        term.focus();
        const proposed = fitAddon.proposeDimensions();
        if (proposed) {
          ws.send(JSON.stringify({ type: "resize", cols: proposed.cols, rows: proposed.rows }));
          setDims({ cols: proposed.cols, rows: proposed.rows });
          setEditCols(String(proposed.cols));
          setEditRows(String(proposed.rows));
        }
      };

      ws.onmessage = (event) => {
        if (typeof event.data === "string" && event.data.startsWith("{")) {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === "ready") {
              handleReady();
              return;
            }
            if (msg.type === "info") {
              term.write(`\r\n${msg.message}\r\n`);
              return;
            }
            if (msg.type === "error") {
              term.write(`\r\n\x1b[31mError: ${msg.message}\x1b[0m\r\n`);
              return;
            }
          } catch {
            // not JSON — fall through to write as bytes
          }
        }
        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then((buf) => {
            term.write(new TextDecoder("utf-8").decode(buf));
          });
        } else {
          term.write(event.data);
        }
      };

      ws.onclose = (event) => {
        if (intentionallyClosedRef.current) return;
        // NOTE: Normal closes (1000/1001) are no longer treated as
        // permanent — see Terminal.tsx for the full rationale. A normal
        // close from navigation, a backend restart, or a network blip
        // now goes through the same backoff reconnection as any other
        // drop, so the web terminal stops showing "Session ended" for
        // sessions that are actually still alive on the backend. Only an
        // exhausted retry budget surfaces the disconnected state.
        if (reconnectAttemptsRef.current < MAX_AUTO_RECONNECTS) {
          const attempt = reconnectAttemptsRef.current++;
          const delay = Math.min(
            RECONNECT_BASE_DELAY_MS * 2 ** attempt,
            RECONNECT_MAX_DELAY_MS
          );
          term.write(
            `\r\n\x1b[33mConnection lost — reconnecting in ${Math.round(delay / 100) / 10}s…\x1b[0m\r\n`
          );
          reconnectTimerRef.current = setTimeout(() => {
            if (!intentionallyClosedRef.current) openSocket();
          }, delay);
          return;
        }
        handleDisconnected(event.code);
      };

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(data);
      });
    };

    const observer = new ResizeObserver(() => {
      // Open the terminal once the container has real dimensions (e.g. the
      // panel is restored from minimized). Subsequent resizes just fit.
      if (openTerminal()) {
        safeFit();
        const dims = fitAddon.proposeDimensions();
        if (dims && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(
            JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows })
          );
        }
      }
    });
    if (containerRef.current) observer.observe(containerRef.current);

    // Try to open immediately; if the container isn't laid out yet, the
    // ResizeObserver will open it once it has dimensions.
    openTerminal();

    return () => {
      intentionallyClosedRef.current = true;
      observer.disconnect();
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      term.dispose();
    };
  }, [sessionId, handleReady, handleDisconnected]);

  // === handlers ===
  const handleNewSession = useCallback(() => {
    const fresh = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY_SESSION, fresh);
    setSessionId(fresh);
    setStatus("connecting");
    setExitCode(undefined);
  }, []);

  const handleMaximize = useCallback(() => {
    navigate("/terminal");
  }, [navigate]);

  // === status bits shared by both modes ===
  const statusLabel =
    status === "connected"
      ? "Connected"
      : status === "connecting"
      ? "Connecting…"
      : "Disconnected";
  const statusColor =
    status === "connected" ? "#10B981" : status === "connecting" ? "#F59E0B" : "#EF4444";

  // === Render the xterm mount EXACTLY ONCE at the top level of this
  // component's JSX. React mounts it once; route changes only flip the
  // chrome wrapper above it. The xterm <div> stays in the DOM with the
  // same ref across the fullpage <-> floating morph, so xterm.js keeps
  // writing to a live, attached DOM node.
  //
  // The mount is positioned via CSS to fill whichever region the chrome
  // currently claims (full viewport when mode==="fullpage", panel
  // rect when mode==="floating"). The chrome is rendered on top with
  // pointer-events:none on its background so clicks fall through to xterm.
  const xtermRegionStyle: React.CSSProperties =
    mode === "fullpage"
      ? {
          position: "fixed",
          left: 0,
          top: 92, // below toolbar (48px) + nav strip (36px) + 8px gap
          right: 0,
          bottom: 0,
          padding: 8,
          boxSizing: "border-box",
          zIndex: 498,
        }
      : {
          position: "fixed",
          left: panelState.minimized ? panelState.x : panelState.x + 10,
          top: panelState.minimized ? panelState.y : panelState.y + 36, // below title bar
          // Never let the xterm mount be 0x0 — opening xterm on a zero-size
          // container leaves its renderer uninitialized and crashes on the
          // first write ("Cannot read properties of undefined (reading
          // 'dimensions')"). Use 1px when minimized (hidden by overflow).
          width: panelState.minimized ? 1 : panelState.width - 20,
          height: panelState.minimized ? 1 : panelState.height - 50, // minus title + resize handle margin
          zIndex: 998,
        };

  // Hide the xterm mount entirely if the session ended — the chrome's
  // disconnected view will fill the space instead.
  const showXterm = status !== "disconnected";

  return (
    <>
      {/* Xterm mount — anchored, persistent. */}
      {showXterm && (
        <div
          ref={containerRef}
          key={`xterm-${sessionId}`}
          style={{
            ...xtermRegionStyle,
            overflow: "hidden",
            borderRadius: 8,
          }}
        />
      )}

      {/* Chrome on top — pointer-events:none on transparent bg, auto on
          interactive controls (buttons, etc. set pointer-events:auto
          themselves). */}
      {mode === "fullpage" ? (
        <>
          {/* Hypothesis suggestion banner — floats above the terminal in
              fullpage (/terminal) mode only. Dismissable, hidden when no
              open hypotheses. zIndex above the chrome so it stays
              clickable. */}
          <div
            style={{
              position: "fixed",
              left: 0,
              right: 0,
              top: 92, // below toolbar (48px) + nav strip (36px) + 8px gap
              zIndex: 501,
              padding: "0 16px",
              pointerEvents: "auto",
            }}
          >
            <TerminalHypothesisBanner />
          </div>
          <FullPageTerminal
          statusLabel={statusLabel}
          statusColor={statusColor}
          isDarkMode={isDarkMode}
          onNewSession={handleNewSession}
          exitCode={exitCode}
          status={status}
          dims={dims}
          editingDims={editingDims}
          editCols={editCols}
          editRows={editRows}
          onStartEdit={() => setEditingDims(true)}
          onColChange={(v) => setEditCols(v)}
          onRowChange={(v) => setEditRows(v)}
          onApply={() => {
            const cols = parseInt(editCols, 10);
            const rows = parseInt(editRows, 10);
            if (cols >= 20 && cols <= 400 && rows >= 10 && rows <= 200) {
              setDims({ cols, rows });
              setEditingDims(false);
              if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: "resize", cols, rows }));
              }
            }
          }}
          onCancel={() => {
            setEditingDims(false);
            setEditCols(String(dims.cols));
            setEditRows(String(dims.rows));
          }}
        />
        </>
      ) : (
        <FloatingPanel
          panelState={panelState}
          onPanelStateChange={setPanelState}
          onMaximize={handleMaximize}
          onNewSession={handleNewSession}
          title="AI Terminal"
          statusLabel={statusLabel}
          statusColor={statusColor}
          isDarkMode={isDarkMode}
        >
          {/* Empty — xterm is rendered above. The panel is a chrome-only
              container now; the children slot is reserved for future use. */}
          <></>
        </FloatingPanel>
      )}
    </>
  );
}

function DimensionBadge({
  dims,
  editingDims,
  editCols,
  editRows,
  onStartEdit,
  onColChange,
  onRowChange,
  onApply,
  onCancel,
  isDarkMode,
}: {
  dims: { cols: number; rows: number };
  editingDims: boolean;
  editCols: string;
  editRows: string;
  onStartEdit: () => void;
  onColChange: (v: string) => void;
  onRowChange: (v: string) => void;
  onApply: () => void;
  onCancel: () => void;
  isDarkMode: boolean;
}) {
  const [tempCols, setTempCols] = useState(editCols);
  const [tempRows, setTempRows] = useState(editRows);

  // Sync from parent when not editing
  useEffect(() => {
    if (!editingDims) {
      setTempCols(String(dims.cols));
      setTempRows(String(dims.rows));
    }
  }, [dims, editingDims]);

  const inputStyle: React.CSSProperties = {
    width: 40,
    padding: "2px 4px",
    fontSize: 12,
    textAlign: "center",
    background: isDarkMode ? "#1d1d1f" : "#fff",
    color: isDarkMode ? "#e0e0e0" : "#1d1d1f",
    border: `1px solid ${isDarkMode ? "rgba(255,255,255,0.2)" : "#d2d2d7"}`,
    borderRadius: 4,
    outline: "none",
  };

  if (editingDims) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12 }}>
        <input
          type="number"
          min={20}
          max={400}
          value={tempCols}
          onChange={(e) => setTempCols(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { onColChange(tempCols); onRowChange(tempRows); onApply(); }
            if (e.key === "Escape") { onCancel(); }
          }}
          onBlur={() => { onColChange(tempCols); onRowChange(tempRows); onApply(); }}
          style={inputStyle}
          autoFocus
        />
        <span style={{ color: isDarkMode ? "rgba(255,255,255,0.55)" : "#6e6e73" }}>×</span>
        <input
          type="number"
          min={10}
          max={200}
          value={tempRows}
          onChange={(e) => setTempRows(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { onColChange(tempCols); onRowChange(tempRows); onApply(); }
            if (e.key === "Escape") { onCancel(); }
          }}
          onBlur={() => { onColChange(tempCols); onRowChange(tempRows); onApply(); }}
          style={inputStyle}
        />
      </span>
    );
  }

  return (
    <span
      onClick={onStartEdit}
      title="Click to resize terminal"
      style={{
        fontSize: 12,
        color: isDarkMode ? "rgba(255,255,255,0.55)" : "#6e6e73",
        cursor: "pointer",
        padding: "2px 8px",
        borderRadius: 4,
        border: "1px solid transparent",
        userSelect: "none",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = isDarkMode ? "rgba(255,255,255,0.15)" : "#d2d2d7"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "transparent"; }}
    >
      {dims.cols}×{dims.rows}
    </span>
  );
}

function FullPageTerminal(props: {
  statusLabel: string;
  statusColor: string;
  isDarkMode: boolean;
  onNewSession: () => void;
  exitCode?: number;
  status: "connecting" | "connected" | "disconnected";
  dims: { cols: number; rows: number };
  editingDims: boolean;
  editCols: string;
  editRows: string;
  onStartEdit: () => void;
  onColChange: (v: string) => void;
  onRowChange: (v: string) => void;
  onApply: () => void;
  onCancel: () => void;
}) {
  const { statusLabel, statusColor, isDarkMode, onNewSession, exitCode, status,
    dims, editingDims, editCols, editRows, onStartEdit, onColChange, onRowChange, onApply, onCancel } = props;
  const navigate = useNavigate();
  const location = useLocation();
  const colors = {
    bg: isDarkMode ? "rgba(5,5,5,0.0)" : "rgba(245,245,247,0.0)", // transparent over xterm
    surface: isDarkMode ? "rgba(10,10,10,0.85)" : "rgba(255,255,255,0.85)",
    text: isDarkMode ? "#ffffff" : "#1d1d1f",
    muted: isDarkMode ? "rgba(255,255,255,0.55)" : "#6e6e73",
    border: isDarkMode ? "rgba(255,255,255,0.08)" : "#d2d2d7",
    navActiveBg: isDarkMode ? "rgba(16,185,129,0.15)" : "rgba(16,185,129,0.12)",
    navHoverBg: isDarkMode ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.05)",
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none", // let clicks fall through to xterm
        zIndex: 500,
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 16px",
          borderBottom: `1px solid ${colors.border}`,
          backgroundColor: colors.surface,
          height: 48,
          flexShrink: 0,
          pointerEvents: "auto", // toolbar itself is interactive
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontWeight: 600, fontSize: 15 }}>AI Terminal</span>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              color: colors.muted,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: statusColor,
                display: "inline-block",
              }}
            />
            {statusLabel}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <DimensionBadge
            dims={dims}
            editingDims={editingDims}
            editCols={editCols}
            editRows={editRows}
            onStartEdit={onStartEdit}
            onColChange={onColChange}
            onRowChange={onRowChange}
            onApply={onApply}
            onCancel={onCancel}
            isDarkMode={isDarkMode}
          />
          <button
            onClick={onNewSession}
            style={{
              padding: "6px 14px",
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              background: "transparent",
              color: colors.text,
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            New Session
          </button>
        </div>
      </div>

      {/* Nav strip */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          padding: "0 12px",
          height: 36,
          borderBottom: `1px solid ${colors.border}`,
          backgroundColor: colors.surface,
          overflowX: "auto",
          flexShrink: 0,
          pointerEvents: "auto",
        }}
      >
        {NAV_ITEMS.map((item) => {
          const isActive = location.pathname === item.path;
          const Icon = item.icon;
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              title={item.label}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "4px 10px",
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: isActive ? 600 : 450,
                color: isActive ? "#10B981" : colors.muted,
                backgroundColor: isActive ? colors.navActiveBg : "transparent",
                whiteSpace: "nowrap",
                flexShrink: 0,
                transition: "all 0.15s ease",
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = colors.navHoverBg;
                  e.currentTarget.style.color = colors.text;
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = "transparent";
                  e.currentTarget.style.color = colors.muted;
                }
              }}
            >
              <Icon size={13} />
              {item.label}
            </button>
          );
        })}
      </div>

      {status === "disconnected" && (
        <div
          style={{
            position: "absolute",
            inset: "84px 0 0 0", // below toolbar (48px) + nav strip (36px)
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            color: colors.muted,
            backgroundColor: colors.bg,
            pointerEvents: "auto",
          }}
        >
          <span style={{ fontSize: 16 }}>
            Session ended{exitCode != null ? ` (exit code ${exitCode})` : ""}
          </span>
          <button
            onClick={onNewSession}
            style={{
              padding: "8px 20px",
              borderRadius: 6,
              border: "none",
              backgroundColor: "#10B981",
              color: "#fff",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            New Session
          </button>
        </div>
      )}
    </div>
  );
}