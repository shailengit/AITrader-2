# Web Terminal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed the full Claude Code CLI experience inside the TradeCraft webapp via a browser-based terminal.

**Architecture:** A FastAPI WebSocket endpoint spawns a Claude Code process inside a pseudo-terminal (PTY). The frontend uses xterm.js to render the terminal and pipes keystrokes/output through the WebSocket. The user gets 100% of Claude Code's capabilities (bash, file ops, git, skills, MCP servers) without leaving the browser.

**Tech Stack:** Python (ptyprocess), FastAPI (WebSocket), React (xterm.js + xterm-addon-fit), lucide-react (Terminal icon)

## Global Constraints

- Backend runs from `backend/` directory with venv Python
- Frontend uses React + TypeScript + Tailwind + shadcn/ui
- All new files follow existing codebase patterns (see `backend/app/routers/` and `frontend/src/pages/`)
- PTY process runs as the same user (no sandboxing — this is a personal dev tool)
- Claude Code must be installed at `~/.local/bin/claude` (the native install)
- `ptyprocess>=0.7.0` is already available in the system Python

---

### Task 1: Backend — Terminal Session Manager

**Files:**
- Create: `backend/app/services/terminal_manager.py`

**Interfaces:**
- Produces: `TerminalSession` class, `TerminalManager` singleton

- [ ] **Step 1: Create `terminal_manager.py`**

```python
"""PTY-based terminal session manager for the web terminal.

Spawns a Claude Code process inside a pseudo-terminal and manages
its lifecycle. One session per WebSocket connection.
"""

import os
import logging
import time
import ptyprocess
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


class TerminalSession:
    """A single Claude Code process running inside a PTY."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.process: Optional[ptyprocess.PtyProcess] = None
        self.last_activity = time.time()
        self.created_at = time.time()

    def start(self):
        """Spawn Claude Code inside a pseudo-terminal."""
        try:
            self.process = ptyprocess.PtyProcess.spawn(
                ["claude"],
                cwd=PROJECT_ROOT,
            )
            logger.info("Terminal session %s started (PID %d)", self.session_id, self.process.pid)
        except FileNotFoundError:
            raise RuntimeError(
                "Claude Code not found. Install with: "
                "npm install -g @anthropic-ai/claude-code"
            )

    def write(self, data: str) -> None:
        """Write data to the PTY's stdin."""
        if self.process and self.is_alive():
            self.process.write(data)
            self.last_activity = time.time()

    def read(self) -> bytes:
        """Read from the PTY's stdout (non-blocking). Returns empty bytes if nothing available."""
        if not self.process or not self.is_alive():
            return b""
        try:
            self.last_activity = time.time()
            return self.process.read(4096)
        except Exception:
            return b""

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY terminal dimensions."""
        if self.process and self.is_alive():
            try:
                self.process.setwinsize(rows, cols)
            except Exception:
                pass

    def kill(self) -> None:
        """Terminate the Claude Code process."""
        if self.process:
            try:
                self.process.close()
            except Exception:
                try:
                    self.process.terminate(force=True)
                except Exception:
                    pass
            self.process = None
            logger.info("Terminal session %s killed", self.session_id)

    def is_alive(self) -> bool:
        """Check if the Claude Code process is still running."""
        if self.process is None:
            return False
        try:
            return self.process.isalive()
        except Exception:
            return False

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity


class TerminalManager:
    """Manages all active terminal sessions."""

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}

    def create_session(self, session_id: str) -> TerminalSession:
        """Create a new terminal session. Destroys existing one with same ID if any."""
        self.destroy_session(session_id)
        session = TerminalSession(session_id)
        session.start()
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        return self._sessions.get(session_id)

    def destroy_session(self, session_id: str) -> None:
        """Kill and remove a session."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.kill()

    def cleanup_idle(self, timeout: int = 1800) -> int:
        """Kill sessions idle for more than `timeout` seconds. Returns count killed."""
        now = time.time()
        killed = 0
        for sid, session in list(self._sessions.items()):
            if now - session.last_activity > timeout:
                logger.info("Cleaning up idle session %s", sid)
                session.kill()
                del self._sessions[sid]
                killed += 1
        return killed


# Module-level singleton
manager = TerminalManager()
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && ./venv/bin/python -c "from app.services.terminal_manager import manager; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/terminal_manager.py
git commit -m "feat(terminal): add PTY-based terminal session manager"
```

---

### Task 2: Backend — WebSocket Router

**Files:**
- Create: `backend/app/routers/terminal.py`

**Interfaces:**
- Consumes: `TerminalManager` from `app.services.terminal_manager`
- Produces: WebSocket endpoint at `/api/terminal/ws`, health endpoint at `/api/terminal/health`

- [ ] **Step 1: Create `terminal.py` router**

```python
"""WebSocket terminal router — streams Claude Code CLI to the browser."""

import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.terminal_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/terminal/ws")
async def terminal_ws(websocket: WebSocket, session: str = ""):
    """WebSocket endpoint that wraps a Claude Code PTY session.

    Each connection gets its own Claude Code process. The session
    parameter allows reconnection to an existing session within the
    idle timeout window.
    """
    await websocket.accept()

    if not session:
        await websocket.send_json({"type": "error", "message": "session parameter required"})
        await websocket.close()
        return

    # Get or create session
    term_session = manager.get_session(session)
    if term_session is None:
        try:
            term_session = manager.create_session(session)
        except RuntimeError as e:
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
            return

    logger.info("WebSocket connected: session=%s", session)

    async def read_pty():
        """Background task: poll PTY stdout and send to WebSocket."""
        while True:
            try:
                data = term_session.read()
                if data:
                    await websocket.send_bytes(data)
                elif not term_session.is_alive():
                    await websocket.send_json({
                        "type": "exit",
                        "code": term_session.process.exitstatus if term_session.process else -1,
                    })
                    break
                else:
                    import asyncio
                    await asyncio.sleep(0.05)
            except Exception:
                break

    import asyncio
    read_task = asyncio.create_task(read_pty())

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if message["type"] == "websocket.receive":
                raw = message.get("text") or message.get("bytes")
                if raw is None:
                    continue

                # Handle JSON control messages
                if isinstance(raw, str) and raw.startswith("{"):
                    try:
                        control = json.loads(raw)
                        if control.get("type") == "resize":
                            term_session.resize(control["cols"], control["rows"])
                            continue
                    except json.JSONDecodeError:
                        pass

                # Forward keystrokes to the PTY
                if isinstance(raw, str):
                    term_session.write(raw)
                elif isinstance(raw, bytes):
                    term_session.write(raw.decode("utf-8", errors="replace"))

    except WebSocketDisconnect:
        pass
    finally:
        read_task.cancel()
        manager.destroy_session(session)
        logger.info("WebSocket disconnected: session=%s", session)


@router.get("/terminal/health")
async def terminal_health():
    """Check if Claude Code is available."""
    import subprocess
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"available": True, "version": result.stdout.strip()}
        return {"available": False, "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"available": False, "error": "Claude Code not found. Install with: npm install -g @anthropic-ai/claude-code"}
    except Exception as e:
        return {"available": False, "error": str(e)}
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && ./venv/bin/python -c "from app.routers.terminal import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/terminal.py
git commit -m "feat(terminal): add WebSocket and health endpoints"
```

---

### Task 3: Backend — Register Router + Requirements

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add import in `main.py`**

Edit `backend/app/main.py` line 99:
```python
from app.routers import sectors, screener, quantgen, health, earnings, markov, coach, strategy_lab, strategy_agent, terminal
```

- [ ] **Step 2: Add `include_router` line after line 110**

```python
app.include_router(terminal.router, prefix="/api", tags=["Terminal"])
```

- [ ] **Step 3: Add `ptyprocess` to `requirements.txt`**

Append to `backend/requirements.txt`:
```
ptyprocess>=0.7.0
```

- [ ] **Step 4: Verify registration**

Run: `cd backend && ./venv/bin/python -c "from app.main import app; routes = [r.path for r in app.routes]; print('terminal/ws' in str(routes))"`
Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/requirements.txt
git commit -m "feat(terminal): register terminal router and add ptyprocess dependency"
```

---

### Task 4: Frontend — Install xterm.js Dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install xterm.js packages**

```bash
cd frontend && npm install xterm xterm-addon-fit
```

- [ ] **Step 2: Verify installation**

Check that `frontend/node_modules/xterm` and `frontend/node_modules/xterm-addon-fit` exist.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(terminal): add xterm.js and xterm-addon-fit dependencies"
```

---

### Task 5: Frontend — Terminal React Component

**Files:**
- Create: `frontend/src/components/terminal/Terminal.tsx`

**Interfaces:**
- Consumes: WebSocket URL from environment/config
- Produces: `<TerminalComponent sessionId={id} onDisconnected={fn} />` React component

- [ ] **Step 1: Create the Terminal component**

```tsx
import { useEffect, useRef, useCallback } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

interface TerminalComponentProps {
  sessionId: string;
  onDisconnected?: (exitCode?: number) => void;
}

const WS_BASE = (() => {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/terminal/ws`;
})();

export function TerminalComponent({ sessionId, onDisconnected }: TerminalComponentProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(() => {
    if (!containerRef.current) return;

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

    // Fit terminal to container after a short delay (needs layout to settle)
    setTimeout(() => fitAddon.fit(), 50);

    termRef.current = term;

    // Connect WebSocket
    const ws = new WebSocket(`${WS_BASE}?session=${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      term.focus();
      // Send initial terminal size
      const dims = fitAddon.proposeDimensions();
      if (dims) {
        ws.send(JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows }));
      }
    };

    ws.onmessage = (event) => {
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
      onDisconnected?.(event.code);
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

    // Forward resize events
    const observer = new ResizeObserver(() => {
      fitAddon.fit();
      const dims = fitAddon.proposeDimensions();
      if (dims && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows }));
      }
    });
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    // Cleanup on unmount
    return () => {
      observer.disconnect();
      ws.close();
      term.dispose();
    };
  }, [sessionId, onDisconnected]);

  useEffect(() => {
    const cleanup = connect();
    return () => cleanup?.();
  }, [connect]);

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
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to the new Terminal component

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/terminal/Terminal.tsx
git commit -m "feat(terminal): add xterm.js React component with WebSocket integration"
```

---

### Task 6: Frontend — Terminal Page

**Files:**
- Create: `frontend/src/pages/Terminal.tsx`

- [ ] **Step 1: Create the Terminal page**

```tsx
import { useState, useCallback } from "react";
import { TerminalComponent } from "../components/terminal/Terminal";
import { useTheme } from "../context/ThemeContext";

export default function TerminalPage() {
  const { isDarkMode } = useTheme();
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [status, setStatus] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const [exitCode, setExitCode] = useState<number | undefined>();

  const handleNewSession = useCallback(() => {
    setSessionId(crypto.randomUUID());
    setStatus("connecting");
    setExitCode(undefined);
  }, []);

  const handleDisconnected = useCallback((code?: number) => {
    setStatus("disconnected");
    setExitCode(code);
  }, []);

  const colors = {
    bg: isDarkMode ? "#050505" : "#f5f5f7",
    surface: isDarkMode ? "#0a0a0a" : "#ffffff",
    text: isDarkMode ? "#ffffff" : "#1d1d1f",
    muted: isDarkMode ? "rgba(255,255,255,0.55)" : "#6e6e73",
    border: isDarkMode ? "rgba(255,255,255,0.08)" : "#d2d2d7",
  };

  const statusColor =
    status === "connected" ? "#10B981"
    : status === "connecting" ? "#F59E0B"
    : "#EF4444";

  const statusLabel =
    status === "connected" ? "Connected"
    : status === "connecting" ? "Connecting..."
    : "Disconnected";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        backgroundColor: colors.bg,
        color: colors.text,
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
          flexShrink: 0,
          height: 48,
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

        <button
          onClick={handleNewSession}
          style={{
            padding: "6px 14px",
            borderRadius: 6,
            border: `1px solid ${colors.border}`,
            backgroundColor: "transparent",
            color: colors.text,
            fontSize: 13,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          New Session
        </button>
      </div>

      {/* Terminal area */}
      <div style={{ flex: 1, padding: 8, overflow: "hidden" }}>
        {status === "disconnected" ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              gap: 12,
              color: colors.muted,
            }}
          >
            <span style={{ fontSize: 16 }}>
              Session ended{exitCode != null ? ` (exit code ${exitCode})` : ""}
            </span>
            <button
              onClick={handleNewSession}
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
        ) : (
          <TerminalComponent
            sessionId={sessionId}
            onDisconnected={handleDisconnected}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to the new Terminal page

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Terminal.tsx
git commit -m "feat(terminal): add full-page terminal view with toolbar and session management"
```

---

### Task 7: Frontend — Add Route and Landing Card

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Landing.tsx`

- [ ] **Step 1: Add route in `App.tsx`**

Add import at the top:
```tsx
import TerminalPage from './pages/Terminal'
```

Add route inside the `<Route element={<Layout />}>` block (before the closing `</Route>`):
```tsx
<Route path="terminal" element={
  <ErrorBoundary>
    <TerminalPage />
  </ErrorBoundary>
} />
```

- [ ] **Step 2: Add card in `Landing.tsx`**

Add `Terminal` to the lucide-react import:
```tsx
import { ..., Terminal } from 'lucide-react'
```

Add a new entry in the `tools` array (after the strategy-lab entry):
```tsx
{
  id: 'terminal',
  title: 'AI Terminal',
  description: 'Full Claude Code CLI in your browser. Read, write, run code, git, and more.',
  icon: Terminal,
  accent: '#10B981',
  link: '/terminal',
  stat: 'Claude Code',
  detail: 'Direct project access with all tools and skills',
},
```

- [ ] **Step 3: Verify TypeScript compilation**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/Landing.tsx
git commit -m "feat(terminal): add /terminal route and landing page card"
```

---

### Task 8: Integration Test

- [ ] **Step 1: Start the backend**

```bash
cd backend && ./venv/bin/python -m app.main &
sleep 3
```

- [ ] **Step 2: Test health endpoint**

```bash
curl -s http://localhost:8000/api/terminal/health | python3 -m json.tool
```
Expected: `{"available": true, "version": "2.1.220"}`

- [ ] **Step 3: Test WebSocket with a quick command**

```bash
python3 -c "
import asyncio, websockets, json
async def test():
    session = 'test-' + __import__('uuid').uuid4().hex[:8]
    async with websockets.connect(f'ws://localhost:8000/api/terminal/ws?session={session}') as ws:
        # Wait a moment for Claude to start
        await asyncio.sleep(2)
        # Send 'echo hello' command
        ws.send('echo hello\\n')
        await asyncio.sleep(3)
        # Read any output
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                print('Received:', msg[:200] if isinstance(msg, str) else msg.hex()[:200])
        except asyncio.TimeoutError:
            pass
        print('Test complete')
asyncio.run(test())
"
```
Expected: Output from Claude Code CLI (may include the echo response)

- [ ] **Step 4: Kill the backend**

```bash
kill %1 2>/dev/null; wait 2>/dev/null
```
