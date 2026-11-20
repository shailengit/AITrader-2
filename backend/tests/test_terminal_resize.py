"""Terminal PTY <-> client size synchronisation.

The PTY is created at 24x80 and only changes when the client asks. When it does
not match what xterm renders, interactive programs wrap for the wrong width and
overwrite themselves at the right edge — the reported bug. These tests pin the
three parts of the contract: the client's initial size is honoured at spawn, a
resize frame reaches the PTY in (rows, cols) order, and a malformed frame is
ignored rather than tearing the WebSocket down.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.routers.terminal import classify_inbound  # noqa: E402
from app.services import terminal_manager as tm  # noqa: E402


class FakeProc:
    """Stand-in for ptyprocess.PtyProcess."""

    def __init__(self, alive=True):
        self.fd = -1  # os.set_blocking(-1) raises OSError, which _spawn ignores
        self.pid = 4242
        self.winsize_calls = []
        self._alive = alive
        self.written = []

    def isalive(self):
        return self._alive

    def setwinsize(self, rows, cols):
        self.winsize_calls.append((rows, cols))

    def read(self, _n):
        return b""

    def write(self, data):
        self.written.append(data)

    def close(self, force=False):
        self._alive = False

    def terminate(self, force=False):
        self._alive = False


@pytest.fixture
def spawn_recorder(monkeypatch):
    """Capture the kwargs the session passes to ptyprocess."""
    recorded = {}

    def fake_spawn(argv, cwd=None, env=None, dimensions=None, **kwargs):
        recorded["argv"] = argv
        recorded["cwd"] = cwd
        recorded["env"] = env
        recorded["dimensions"] = dimensions
        return FakeProc()

    monkeypatch.setattr(tm.ptyprocess.PtyProcess, "spawn", staticmethod(fake_spawn))
    return recorded


# --------------------------------------------------------------------- frames

class TestClassifyInbound:
    """Three outcomes: apply a resize, drop an unusable control frame, or forward
    the bytes to the shell as input."""

    def test_accepts_a_resize_frame(self):
        assert classify_inbound('{"type":"resize","cols":120,"rows":40}') == ("resize", (120, 40))

    def test_keystrokes_and_text_are_input(self):
        assert classify_inbound("ls -la\r") == ("input", None)
        assert classify_inbound("") == ("input", None)
        assert classify_inbound(b'{"type":"resize","cols":120,"rows":40}') == ("input", None)
        # A paste that happens to start with "{" must still reach the shell.
        assert classify_inbound('{"weird": 1}') == ("input", None)
        assert classify_inbound('not json at all') == ("input", None)

    def test_unusable_resize_frames_are_dropped_not_typed(self):
        # KeyError here used to escape the read loop and kill the session; typing
        # the frame at the prompt would be just as wrong.
        for raw in [
            '{"type":"resize"}',
            '{"type":"resize","cols":120}',
            '{"type":"resize","cols":null,"rows":null}',
            '{"type":"resize","cols":"wide","rows":40}',
            '{"type":"resize","cols":true,"rows":true}',
            '{"type":"resize","cols":1e999,"rows":1e999}',  # parses to inf
        ]:
            assert classify_inbound(raw) == ("ignore", None), raw

    def test_other_json_objects_are_still_input(self):
        assert classify_inbound('{"type":"input","data":"x"}') == ("input", None)
        assert classify_inbound("[1,2,3]") == ("input", None)
        assert classify_inbound("null") == ("input", None)

    def test_truncated_json_is_input(self):
        assert classify_inbound('{"type":"resize",') == ("input", None)


# ---------------------------------------------------------------------- spawn

def test_initial_size_comes_from_the_client(spawn_recorder):
    """The client's dimensions must reach the spawn call, not ptyprocess' 24x80."""
    session = tm.TerminalSession("sess-initial", cols=132, rows=43)
    assert session.wait_ready(timeout=5)
    # ptyprocess takes dimensions as (rows, cols).
    assert spawn_recorder["dimensions"] == (43, 132)
    assert (session.cols, session.rows) == (132, 43)


def test_spawn_uses_xterm_256color(spawn_recorder):
    session = tm.TerminalSession("sess-term")
    assert session.wait_ready(timeout=5)
    env = spawn_recorder["env"]
    assert env is not None, "spawn must pass an explicit env, or TERM is whatever launchd had"
    assert env["TERM"] == "xterm-256color"


def test_spawn_falls_back_to_a_usable_default(spawn_recorder):
    session = tm.TerminalSession("sess-default", cols=None, rows=None)
    assert session.wait_ready(timeout=5)
    assert spawn_recorder["dimensions"] == (24, 80)


def test_nonsense_dimensions_do_not_reach_the_pty(spawn_recorder):
    session = tm.TerminalSession("sess-bad", cols=0, rows=0)
    assert session.wait_ready(timeout=5)
    assert spawn_recorder["dimensions"] == (24, 80)
    assert (session.cols, session.rows) == (80, 24)


def test_manager_creation_passes_dimensions_through(spawn_recorder):
    manager = tm.TerminalManager()
    session = manager.create_session("sess-manager", cols=100, rows=30)
    assert session.wait_ready(timeout=5)
    assert spawn_recorder["dimensions"] == (30, 100)


# --------------------------------------------------------------------- resize

class TestResize:
    def _session(self, spawn_recorder):
        session = tm.TerminalSession("sess-resize")
        assert session.wait_ready(timeout=5)
        return session

    def test_resize_calls_setwinsize_rows_then_cols(self, spawn_recorder):
        session = self._session(spawn_recorder)
        proc = FakeProc()
        session.process = proc
        session.resize(120, 40)
        assert proc.winsize_calls == [(40, 120)]
        assert (session.cols, session.rows) == (120, 40)

    def test_repeated_same_size_is_a_no_op(self, spawn_recorder):
        session = self._session(spawn_recorder)
        proc = FakeProc()
        session.process = proc
        session.resize(120, 40)
        session.resize(120, 40)
        # One SIGWINCH, not two: a repeat would make the TUI redraw for nothing.
        assert proc.winsize_calls == [(40, 120)]

    def test_non_numeric_sizes_are_ignored(self, spawn_recorder):
        session = self._session(spawn_recorder)
        proc = FakeProc()
        session.process = proc
        for cols, rows in [
            (None, None),
            ("x", 40),
            (float("nan"), 40),
            (float("inf"), 40),  # JSON 1e999 parses to inf; int(inf) raises OverflowError
            (True, True),
        ]:
            session.resize(cols, rows)
        assert proc.winsize_calls == []
        assert (session.cols, session.rows) == (80, 24)

    def test_a_narrow_panel_is_clamped_not_ignored(self, spawn_recorder):
        # A really narrow panel must still be reported: if the PTY kept a stale,
        # wider size the wrapping bug would come straight back.
        session = self._session(spawn_recorder)
        proc = FakeProc()
        session.process = proc
        session.resize(5, 3)
        assert proc.winsize_calls == [(tm.MIN_ROWS, tm.MIN_COLS)]
        assert (session.cols, session.rows) == (tm.MIN_COLS, tm.MIN_ROWS)

    def test_huge_sizes_are_capped(self, spawn_recorder):
        session = self._session(spawn_recorder)
        proc = FakeProc()
        session.process = proc
        session.resize(100000, 100000)
        assert proc.winsize_calls == [(tm.MAX_ROWS, tm.MAX_COLS)]

    def test_dead_session_is_a_no_op(self, spawn_recorder):
        session = self._session(spawn_recorder)
        proc = FakeProc(alive=False)
        session.process = proc
        session.resize(120, 40)
        assert proc.winsize_calls == []


class TestClampSize:
    def test_usable_size_passes_through(self):
        assert tm.clamp_size(120, 40) == (120, 40)

    def test_defaults_for_unusable_size(self):
        assert tm.clamp_size(0, 0) == (tm.DEFAULT_COLS, tm.DEFAULT_ROWS)
        assert tm.clamp_size(None, None) == (tm.DEFAULT_COLS, tm.DEFAULT_ROWS)
        assert tm.clamp_size("nope", 40) == (tm.DEFAULT_COLS, tm.DEFAULT_ROWS)
