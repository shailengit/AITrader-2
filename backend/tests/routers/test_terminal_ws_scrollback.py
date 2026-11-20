"""Integration tests for scrollback replay in the terminal WebSocket handler.

We drive `terminal_ws` directly with a FakeWebSocket rather than going
through TestClient (which doesn't support WebSockets). This lets us
verify the message order: {ready} -> scrollback bytes -> live stream.
"""

import asyncio
import json

import pytest

from app.services import terminal_manager
from app.services.terminal_manager import TerminalManager


class FakeWebSocket:
    """Minimal WebSocket stand-in for driving terminal_ws in tests."""

    def __init__(self, query_params=None):
        self.sent_text = []
        self.sent_bytes = []
        self.disconnected = False
        # The handler reads the client's initial geometry from here, as it does on a
        # real Starlette WebSocket.
        self.query_params = query_params or {}

    async def accept(self):
        pass

    async def send_json(self, payload):
        self.sent_text.append(payload)

    async def send_bytes(self, payload):
        self.sent_bytes.append(payload)

    async def close(self, code=None):
        self.disconnected = True

    async def receive(self):
        # Return a disconnect immediately so the handler's
        # `while True: await websocket.receive()` loop exits promptly.
        if self.disconnected:
            raise RuntimeError("WS already disconnected")
        self.disconnected = True
        return {"type": "websocket.disconnect"}


@pytest.fixture(autouse=True)
def _accept_ws_handshake(monkeypatch):
    """These tests drive terminal_ws directly and are about message order, not the
    handshake (covered in the auth tests). Without this the fake socket presents no
    token and the handler closes the connection before replaying anything."""
    monkeypatch.setattr("app.routers.terminal.require_ws_token", lambda _token: True)


def _install_loop_stubs(monkeypatch):
    """Patch asyncio primitives the router needs so the test doesn't need a real loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # No-op reader writer so on_pty_readable can be registered; we never fire it.
    loop.add_reader = lambda *_a, **_kw: None
    loop.remove_reader = lambda *_a, **_kw: None
    return loop


def _patch_fake_pty(monkeypatch):
    """Replace ptyprocess.PtyProcess.spawn with a fake that won't try to start a process."""
    class FakePty:
        @staticmethod
        def spawn(argv, cwd=None, env=None, dimensions=None, **kwargs):
            # Mirror ptyprocess' real signature: TerminalSession also passes the
            # client's geometry and an explicit TERM env.
            class P:
                fd = 7
                pid = 1234

                def isalive(self):
                    return True

                def read(self, n):
                    return b""

                def write(self, data):
                    pass

                def setwinsize(self, rows, cols):
                    pass

            return P()

    monkeypatch.setattr(terminal_manager.ptyprocess.PtyProcess, "spawn", FakePty.spawn)
    monkeypatch.setattr(terminal_manager.os, "set_blocking", lambda *_a, **_kw: None)


def test_ws_replays_scrollback_after_ready_on_initial_spawn(monkeypatch):
    """First-time connect (no existing session): {info}, {ready}, then scrollback bytes."""
    _patch_fake_pty(monkeypatch)
    loop = _install_loop_stubs(monkeypatch)

    try:
        mgr = TerminalManager()
        # Fresh manager: get_session returns None, so the initial-spawn
        # branch fires. create_session creates a real TerminalSession,
        # but we override its append_scrollback to inject our seed data
        # once construction is complete.
        from app.services.terminal_manager import TerminalSession as RealTS
        original_init = RealTS.__init__

        def init_with_seed(self, session_id, resume=False, cols=None, rows=None, **kwargs):
            original_init(self, session_id, resume=resume, cols=cols, rows=rows)
            self.append_scrollback(b"PRE-HISTORY\n")

        monkeypatch.setattr(RealTS, "__init__", init_with_seed)

        monkeypatch.setattr("app.routers.terminal.manager", mgr)

        from app.routers.terminal import terminal_ws

        ws = FakeWebSocket()

        async def drive():
            await terminal_ws(ws, session="replay-A")

        loop.run_until_complete(drive())

        json_msgs = [m for m in ws.sent_text]
        info_msgs = [m for m in json_msgs if m.get("type") == "info"]
        assert len(info_msgs) >= 1, json_msgs
        ready_msgs = [m for m in json_msgs if m.get("type") == "ready"]
        assert len(ready_msgs) == 1, json_msgs
        assert ready_msgs[0].get("reconnected") is None, ready_msgs
        assert any(b"PRE-HISTORY" in chunk for chunk in ws.sent_bytes), ws.sent_bytes
    finally:
        loop.close()


def test_ws_replays_scrollback_on_reconnect_to_live_session(monkeypatch):
    """Reconnect path: cancel pending destroy, send {ready, reconnected}, then scrollback."""
    _patch_fake_pty(monkeypatch)
    loop = _install_loop_stubs(monkeypatch)

    try:
        mgr = TerminalManager()
        sess = mgr.create_session("replay-B")
        sess.ready_event.wait(timeout=2)
        sess.append_scrollback(b"OLD\n")
        # Keep the session alive.
        monkeypatch.setattr(sess.__class__, "is_alive", lambda self: True)

        monkeypatch.setattr("app.routers.terminal.manager", mgr)

        from app.routers.terminal import terminal_ws

        ws = FakeWebSocket()

        async def drive():
            await terminal_ws(ws, session="replay-B")

        loop.run_until_complete(drive())

        json_msgs = [m for m in ws.sent_text]
        ready_msgs = [m for m in json_msgs if m.get("type") == "ready"]
        assert len(ready_msgs) == 1, json_msgs
        assert ready_msgs[0].get("reconnected") is True, ready_msgs
        assert len(ws.sent_bytes) == 1
        assert b"OLD" in ws.sent_bytes[0]
    finally:
        loop.close()


def test_respawn_passes_resume_true(monkeypatch):
    """Reconnect-to-dead-session path calls create_session(..., resume=True)
    so the Claude child respawns with --resume <sessionId>."""
    _patch_fake_pty(monkeypatch)
    loop = _install_loop_stubs(monkeypatch)

    captured_kwargs = {}

    original_create = TerminalManager.create_session

    def spying_create(self, session_id, *, resume=False):
        captured_kwargs["session_id"] = session_id
        captured_kwargs["resume"] = resume
        return original_create(self, session_id, resume=resume)

    try:
        mgr = TerminalManager()
        # Pre-populate so the reconnect branch enters.
        pre_existing = mgr.create_session("replay-C")
        pre_existing.ready_event.wait(timeout=2)
        # Mark the pre-existing session as dead so the respawn branch fires.
        monkeypatch.setattr(pre_existing.__class__, "is_alive", lambda self: False)

        monkeypatch.setattr(TerminalManager, "create_session", spying_create)
        monkeypatch.setattr("app.routers.terminal.manager", mgr)

        from app.routers.terminal import terminal_ws

        ws = FakeWebSocket()

        async def drive():
            await terminal_ws(ws, session="replay-C")

        loop.run_until_complete(drive())

        # Either the respawn or the create_session call captured True.
        assert captured_kwargs.get("resume") is True, captured_kwargs
    finally:
        loop.close()