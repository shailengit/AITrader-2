"""WebSocket terminal router — streams a shell session to the browser."""

import asyncio
import json
import logging
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from app.dependencies import require_api_auth, require_ws_token
from app.services.terminal_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


def classify_inbound(raw) -> Tuple[str, Optional[Tuple[int, int]]]:
    """Classify one inbound WebSocket message.

    Returns one of:

    * ``("resize", (cols, rows))`` — apply this geometry to the PTY;
    * ``("ignore", None)`` — a control frame we cannot use; drop it;
    * ``("input", None)`` — not a control frame; forward it to the PTY.

    This runs for every message in the read loop and must never raise: an exception
    there is caught neither by the ``WebSocketDisconnect`` handler nor by anything
    else, so it tears the terminal down mid-session. (It used to index
    ``control["cols"]`` directly, so a resize frame without dimensions raised
    KeyError and killed the session.)

    A frame that announces itself as a control frame is never forwarded as input.
    A resize frame missing its dimensions must not end up typed at the user's
    prompt as the literal text ``{"type":"resize"}``.
    """
    if not isinstance(raw, str) or not raw.startswith("{"):
        return "input", None
    try:
        control = json.loads(raw)
    except ValueError:
        # Not JSON after all — the user is typing or pasting text starting with "{".
        return "input", None
    if not isinstance(control, dict) or control.get("type") != "resize":
        return "input", None

    def _int(value):
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            # OverflowError: JSON allows 1e999, which parses to inf.
            return None

    cols, rows = _int(control.get("cols")), _int(control.get("rows"))
    if cols is None or rows is None:
        return "ignore", None
    return "resize", (cols, rows)


def _query_size(websocket: WebSocket) -> Optional[Tuple[int, int]]:
    """``(cols, rows)`` from the connect URL, or None when absent/unusable.

    The client sends its real terminal size here so the PTY can be spawned at the
    right dimensions instead of the 24x80 default.
    """
    cols = websocket.query_params.get("cols")
    rows = websocket.query_params.get("rows")
    if cols is None or rows is None:
        return None
    try:
        return int(cols), int(rows)
    except (TypeError, ValueError, OverflowError):
        return None


@router.websocket("/terminal/ws")
async def terminal_ws(websocket: WebSocket, session: str = ""):
    """WebSocket endpoint that wraps a shell PTY session.

    Each connection gets its own zsh process. The session
    parameter allows reconnection to an existing session within the
    idle timeout window.

    PTY I/O is wired to asyncio via ``loop.add_reader()`` so the
    master fd wakes the event loop when data is available, instead of
    blocking the loop in a synchronous ``read()`` syscall.
    """
    await websocket.accept()

    # Require a valid API token on the WebSocket handshake (query param).
    token = websocket.query_params.get("token", "")
    try:
        require_ws_token(token)
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": "Unauthorized: invalid or missing API token"})
        await websocket.close(code=4401)
        return

    if not session:
        await websocket.send_json({"type": "error", "message": "session parameter required"})
        await websocket.close()
        return

    async def send_scrollback() -> None:
        """Replay the full scrollback buffer to the client so xterm rebuilds
        its visible history. Sends raw bytes (may include ANSI escapes)
        which the frontend writes to xterm verbatim."""
        scrollback, _ = term_session.get_scrollback()
        if scrollback:
            await websocket.send_bytes(scrollback)

    # Get or create session (spawns Claude Code in a background thread)
    initial_size = _query_size(websocket)

    term_session = manager.get_session(session)
    if term_session is None:
        await websocket.send_json({"type": "info", "message": "Starting shell session..."})
        term_session = manager.create_session(
            session,
            cols=initial_size[0] if initial_size else None,
            rows=initial_size[1] if initial_size else None,
        )

        # Wait for the process to start (up to 30s)
        started = term_session.wait_ready(timeout=30.0)
        if not started:
            await websocket.send_json({"type": "error", "message": "Timed out waiting for shell to start"})
            await websocket.close()
            manager.destroy_session(session)
            return

        if term_session.error:
            await websocket.send_json({"type": "error", "message": term_session.error})
            await websocket.close()
            manager.destroy_session(session)
            return

        await websocket.send_json({"type": "ready"})
        await send_scrollback()
    else:
        # Reconnecting to an existing session — cancel any pending
        # destroy (StrictMode double-mount / transient blip) and tell
        # the client we're already attached.
        manager.cancel_pending_destroy(session)
        if term_session.is_alive():
            await websocket.send_json({
                "type": "ready",
                "reconnected": True,
            })
            await send_scrollback()
        else:
            # Session exists but its Claude child has died (e.g. user
            # exited Claude). Recreate with the same ID and ask Claude
            # to resume its prior conversation from its own session store.
            await websocket.send_json({
                "type": "info",
                "message": "Previous session ended. Starting new shell session...",
            })
            term_session = manager.create_session(session, resume=True)
            started = term_session.wait_ready(timeout=30.0)
            if not started or term_session.error:
                msg = term_session.error or "Timed out waiting for Claude Code to start"
                await websocket.send_json({"type": "error", "message": msg})
                await websocket.close()
                manager.destroy_session(session)
                return
            await websocket.send_json({"type": "ready"})
            await send_scrollback()

    # A reclaimed session still has the geometry its previous client left behind;
    # make it match this client before the shell draws anything.
    if initial_size is not None:
        term_session.resize(initial_size[0], initial_size[1])

    logger.info(
        "WebSocket connected: session=%s size=%s",
        session, initial_size or "unset",
    )

    loop = asyncio.get_running_loop()
    reader_attached = False
    exit_sent = False

    def on_pty_readable() -> None:
        """Called by the event loop when the PTY master fd has data.

        Runs on the event loop thread, so it's safe to call
        ``websocket.send_*`` here. Uses non-blocking read so it
        returns immediately if there's only a partial chunk.
        """
        nonlocal exit_sent
        try:
            data = term_session.read_nonblocking()
        except Exception as e:
            logger.warning("PTY read error: %s", e)
            return
        if data:
            # Record before forwarding so a (re)connecting client can
            # replay this byte from the scrollback buffer.
            term_session.append_scrollback(data)
            # Schedule send on the loop to avoid awaiting inside the
            # synchronous reader callback.
            asyncio.ensure_future(_safe_send_bytes(data), loop=loop)
            return
        # No data: either still warming up, or EOF (process died).
        if not term_session.is_alive() and not exit_sent:
            exit_sent = True
            asyncio.ensure_future(_safe_send_exit(), loop=loop)

    async def _safe_send_bytes(data: bytes) -> None:
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    async def _safe_send_exit() -> None:
        try:
            await websocket.send_json({"type": "exit", "code": -1})
        except Exception:
            pass

    try:
        try:
            fd = term_session.fileno()
        except OSError as e:
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
            manager.destroy_session(session)
            return

        loop.add_reader(fd, on_pty_readable)
        reader_attached = True

        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if message["type"] == "websocket.receive":
                raw = message.get("text") or message.get("bytes")
                if raw is None:
                    continue

                # Control frames are handled here and never reach the shell.
                kind, size = classify_inbound(raw)
                if kind == "resize" and size is not None:
                    term_session.resize(size[0], size[1])
                    continue
                if kind == "ignore":
                    continue

                # Forward keystrokes to the PTY
                if isinstance(raw, str):
                    term_session.write(raw)
                elif isinstance(raw, bytes):
                    term_session.write(raw.decode("utf-8", errors="replace"))

    except WebSocketDisconnect:
        pass
    finally:
        if reader_attached:
            try:
                loop.remove_reader(fd)
            except (OSError, ValueError, Exception):
                pass
        # Don't call destroy_session here — it would schedule a kill
        # timer that fires even if a new WebSocket has already reclaimed
        # the session (e.g. after page navigation). Let cleanup_idle
        # handle stale sessions instead.
        manager.cancel_pending_destroy(session)
        logger.info("WebSocket disconnected: session=%s", session)


@router.get("/terminal/health", dependencies=[Depends(require_api_auth)])
async def terminal_health():
    """Check if zsh is available."""
    import subprocess
    import shutil
    zsh_path = shutil.which("zsh")
    if zsh_path:
        return {"available": True, "path": zsh_path}
    return {"available": False, "error": "zsh not found in PATH"}
