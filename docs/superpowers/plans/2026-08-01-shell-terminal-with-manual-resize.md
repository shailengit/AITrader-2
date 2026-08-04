# Shell Terminal with Manual Resize — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the web terminal from auto-launching Claude Code to spawning a regular zsh shell, and add a clickable dimension badge in the toolbar for manual cols/rows resize.

**Architecture:** Backend change is a one-line command swap in `terminal_manager.py` plus a message string update in `terminal.py`. Frontend change adds state + inline editing UI to `TerminalHost.tsx`. The WebSocket resize protocol is already in place.

**Tech Stack:** Python (FastAPI), TypeScript (React), xterm.js

## Global Constraints

- Backend Python must use the existing `ptyprocess` library — no new dependencies
- Frontend must use shadcn/ui patterns where applicable (inline inputs, not a custom modal)
- The `resume` parameter on `create_session()` is kept for API compatibility but has no effect on shell sessions
- Manual resize is a temporary override — the ResizeObserver still fires on container changes

---

### Task 1: Backend — Spawn zsh instead of claude

**Files:**
- Modify: `backend/app/services/terminal_manager.py:64-89`
- Modify: `backend/app/routers/terminal.py:44`
- Modify: `backend/tests/services/test_terminal_manager_resume.py:39,50,62`

**Interfaces:**
- Consumes: `TerminalSession.__init__` signature unchanged
- Produces: `TerminalSession._spawn()` now runs `["zsh", "--login"]` instead of `["claude"]`

- [ ] **Step 1: Update `_spawn()` in terminal_manager.py**

Change the command from `["claude"]` to `["zsh", "--login"]` and remove the `--resume` branch:

```python
# In _spawn(), replace:
cmd = ["claude"]
if self.resume:
    cmd.extend(["--resume", self.session_id])

# With:
cmd = ["zsh", "--login"]
```

- [ ] **Step 2: Update info message in terminal.py**

```python
# In terminal.py line 44, change:
await websocket.send_json({"type": "info", "message": "Starting Claude Code session..."})

# To:
await websocket.send_json({"type": "info", "message": "Starting shell session..."})
```

- [ ] **Step 3: Update resume tests**

The resume tests assert `["claude"]` and `["claude", "--resume", "sess-A"]` in the argv. Since we now spawn `zsh --login`, update the assertions:

```python
# test_spawn_argv_contains_resume_when_resume_true (line 39):
assert captured["argv"] == ["zsh", "--login"], captured["argv"]

# test_spawn_argv_does_not_contain_resume_when_resume_false (line 50):
assert captured["argv"] == ["zsh", "--login"], captured["argv"]

# test_spawn_default_resume_is_false (line 62):
assert captured["argv"] == ["zsh", "--login"], captured["argv"]
```

- [ ] **Step 4: Run backend tests to verify**

```bash
cd backend && ./venv/bin/python -m pytest tests/services/test_terminal_manager_resume.py -v
```

Expected: All 5 tests pass (the 4 resume tests + 1 reclaim test which doesn't check argv).

- [ ] **Step 5: Run scrollback tests too**

```bash
cd backend && ./venv/bin/python -m pytest tests/services/test_terminal_session_scrollback.py -v
```

Expected: All 5 scrollback tests pass (they don't depend on the spawn command).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/terminal_manager.py backend/app/routers/terminal.py backend/tests/services/test_terminal_manager_resume.py
git commit -m "feat(terminal): spawn zsh shell instead of auto-launching Claude Code"
```

---

### Task 2: Frontend — Add dimension badge with inline editing

**Files:**
- Modify: `frontend/src/components/terminal/TerminalHost.tsx`

**Interfaces:**
- Consumes: WebSocket `resize` control message (already handled by backend)
- Produces: Dimension badge in full-page toolbar with inline editing

- [ ] **Step 1: Add dims state to TerminalHost**

Add these state variables after the existing `exitCode` state (around line 88):

```typescript
// === terminal dimensions ===
const [dims, setDims] = useState<{ cols: number; rows: number }>({ cols: 80, rows: 24 });
const [editingDims, setEditingDims] = useState(false);
const [editCols, setEditCols] = useState("80");
const [editRows, setEditRows] = useState("24");
```

- [ ] **Step 2: Initialize dims from fitAddon on connect**

In the `ws.onopen` handler (around line 153), after the existing resize send, add:

```typescript
const proposed = fitAddon.proposeDimensions();
if (proposed) {
  setDims({ cols: proposed.cols, rows: proposed.rows });
  setEditCols(String(proposed.cols));
  setEditRows(String(proposed.rows));
}
```

- [ ] **Step 3: Add resize badge component**

Add this component inside `TerminalHost.tsx` (before the return statement, or as a helper component):

```typescript
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
          style={{ width: 40, padding: "2px 4px", fontSize: 12, textAlign: "center" }}
          autoFocus
        />
        <span>×</span>
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
          style={{ width: 40, padding: "2px 4px", fontSize: 12, textAlign: "center" }}
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
        color: colors.muted,
        cursor: "pointer",
        padding: "2px 8px",
        borderRadius: 4,
        border: `1px solid transparent`,
        userSelect: "none",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = colors.border; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "transparent"; }}
    >
      {dims.cols}×{dims.rows}
    </span>
  );
}
```

- [ ] **Step 4: Wire the badge into the toolbar**

In the `FullPageTerminal` component's toolbar (around line 396-433), add the badge between the status indicator and the "New Session" button:

```typescript
{/* Before: */}
<div style={{ display: "flex", alignItems: "center", gap: 12 }}>
  <span style={{ fontWeight: 600, fontSize: 15 }}>AI Terminal</span>
  <span style={{ /* status indicator */ }}>
    <span style={{ /* dot */ }} />
    {statusLabel}
  </span>
</div>
<button onClick={onNewSession} style={/* ... */}>New Session</button>

{/* After: */}
<div style={{ display: "flex", alignItems: "center", gap: 12 }}>
  <span style={{ fontWeight: 600, fontSize: 15 }}>AI Terminal</span>
  <span style={{ /* status indicator */ }}>
    <span style={{ /* dot */ }} />
    {statusLabel}
  </span>
</div>
<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
  <DimensionBadge
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
  <button onClick={onNewSession} style={/* ... */}>New Session</button>
</div>
```

- [ ] **Step 5: Pass dims state and handlers to FullPageTerminal**

Update the `FullPageTerminal` props to include the new state and handlers:

```typescript
// Add to FullPageTerminal props:
dims: { cols: number; rows: number };
editingDims: boolean;
editCols: string;
editRows: string;
onStartEdit: () => void;
onColChange: (v: string) => void;
onRowChange: (v: string) => void;
onApply: () => void;
onCancel: () => void;
```

And pass them from the parent:

```typescript
<FullPageTerminal
  ...
  dims={dims}
  editingDims={editingDims}
  editCols={editCols}
  editRows={editRows}
  onStartEdit={() => setEditingDims(true)}
  onColChange={(v) => setEditCols(v)}
  onRowChange={(v) => setEditRows(v)}
  onApply={handleApplyDims}
  onCancel={handleCancelDims}
/>
```

- [ ] **Step 6: Verify the frontend compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: No TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/terminal/TerminalHost.tsx
git commit -m "feat(terminal): add clickable dimension badge for manual cols/rows resize"
```

---

### Task 3: Verify end-to-end

- [ ] **Step 1: Start the backend**

```bash
cd backend && ./venv/bin/python -m app.main &
sleep 3
```

- [ ] **Step 2: Start the frontend**

```bash
cd frontend && npm run dev &
sleep 5
```

- [ ] **Step 3: Open the terminal page**

Navigate to `http://localhost:5173/terminal` (or the Vite dev server port).

Verify:
- [ ] A zsh shell prompt appears (not Claude Code)
- [ ] Typing `echo hello` works and prints "hello"
- [ ] The toolbar shows a `{cols}×{rows}` badge
- [ ] Clicking the badge shows two number inputs
- [ ] Changing values and pressing Enter resizes the terminal
- [ ] Typing `claude` launches Claude Code interactively
- [ ] Typing `herdr` launches herdr (if installed)
- [ ] Typing `exit` ends the session and shows "Session ended"

- [ ] **Step 4: Kill dev servers**

```bash
kill %1 %2 2>/dev/null; true
```
