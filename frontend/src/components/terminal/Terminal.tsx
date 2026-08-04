import { useEffect, useRef } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

interface TerminalComponentProps {
  sessionId: string;
  onReady?: () => void;
  onDisconnected?: (exitCode?: number) => void;
}

const WS_BASE = (() => {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/terminal/ws`;
})();

// Maximum number of automatic reconnects before we give up and surface
// the disconnected state to the user. StrictMode double-mount counts as
// one reconnect, so this needs to be high enough to absorb that plus a
// few transient network blips.
const MAX_AUTO_RECONNECTS = 8;
const RECONNECT_BASE_DELAY_MS = 250;
const RECONNECT_MAX_DELAY_MS = 4000;

export function TerminalComponent({ sessionId, onReady, onDisconnected }: TerminalComponentProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const onReadyRef = useRef(onReady);
  const onDisconnectedRef = useRef(onDisconnected);

  // Reconnect bookkeeping (refs so the auto-reconnect logic doesn't
  // trigger React re-renders and re-create the terminal).
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionallyClosedRef = useRef(false);

  // Keep callback refs in sync without triggering re-renders
  onReadyRef.current = onReady;
  onDisconnectedRef.current = onDisconnected;

  useEffect(() => {
    if (!containerRef.current) return;
    intentionallyClosedRef.current = false;

    // Create xterm.js terminal
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
    term.open(containerRef.current);

    // Fit terminal to container after layout settles
    const fitTerminal = () => fitAddon.fit();
    setTimeout(fitTerminal, 50);

    termRef.current = term;

    const openSocket = () => {
      const ws = new WebSocket(`${WS_BASE}?session=${sessionId}`);
      wsRef.current = ws;

      ws.onopen = () => {
        // Successful connection — reset backoff.
        reconnectAttemptsRef.current = 0;
        term.focus();
        const dims = fitAddon.proposeDimensions();
        if (dims) {
          ws.send(JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows }));
        }
      };

      ws.onmessage = (event) => {
        // Handle JSON control messages from the backend
        if (typeof event.data === "string" && event.data.startsWith("{")) {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === "ready") {
              onReadyRef.current?.();
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
            // Not JSON, treat as regular terminal output
          }
        }

        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then((buf) => {
            const decoder = new TextDecoder("utf-8");
            term.write(decoder.decode(buf));
          });
        } else {
          term.write(event.data);
        }
      };

      ws.onclose = (event) => {
        // If we closed intentionally (sessionId change, unmount),
        // do NOT surface the close to the parent — the component is
        // being torn down and calling onDisconnected would cause the
        // new component (on re-mount) to show "Session ended" due to
        // the async onclose firing after the new mount.
        if (intentionallyClosedRef.current) {
          return;
        }
        if (event.code === 1000 || event.code === 1001) {
          // Normal closure — don't reconnect.
          onDisconnectedRef.current?.(event.code);
          return;
        }
        if (reconnectAttemptsRef.current < MAX_AUTO_RECONNECTS) {
          const attempt = reconnectAttemptsRef.current++;
          const delay = Math.min(
            RECONNECT_BASE_DELAY_MS * 2 ** attempt,
            RECONNECT_MAX_DELAY_MS,
          );
          term.write(
            `\r\n\x1b[33mConnection lost — reconnecting in ${Math.round(delay / 100) / 10}s…\x1b[0m\r\n`,
          );
          reconnectTimerRef.current = setTimeout(() => {
            if (!intentionallyClosedRef.current) openSocket();
          }, delay);
          return;
        }
        // Out of retries — give up.
        onDisconnectedRef.current?.(event.code);
      };

      ws.onerror = () => {
        // onclose will fire after this
      };

      // Forward keystrokes to WebSocket
      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data);
        }
      });

      // (Resize observer attached once, outside openSocket, so it isn't
      // duplicated across reconnects.)
    };

    // Forward resize events (attached once)
    const observer = new ResizeObserver(() => {
      fitAddon.fit();
      const dims = fitAddon.proposeDimensions();
      if (dims && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows }),
        );
      }
    });
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    openSocket();

    // Cleanup on unmount or sessionId change
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
  }, [sessionId]); // Only reconnect when sessionId changes

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "100%",
        overflow: "hidden",
        borderRadius: 8,
      }}
    />
  );
}
