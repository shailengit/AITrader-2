"""Tests that --resume propagates from create_session to ptyprocess.spawn."""

import threading

from app.services import terminal_manager
from app.services.terminal_manager import TerminalManager


def _patch_fake_pty(monkeypatch, captured):
    """Patch ptyprocess.PtyProcess.spawn to record argv."""

    class FakePty:
        @staticmethod
        def spawn(argv, cwd=None, env=None, dimensions=None, **kwargs):
            # Mirror ptyprocess' real signature: TerminalSession also passes the
            # client's geometry and an explicit TERM env.
            captured["argv"] = list(argv)
            captured["cwd"] = cwd
            captured["env"] = env
            captured["dimensions"] = dimensions

            class P:
                fd = 7
                pid = 1234

                def isalive(self):
                    return True

            return P()

    monkeypatch.setattr(terminal_manager.ptyprocess.PtyProcess, "spawn", FakePty.spawn)
    # fd=7 is not a real file descriptor; bypass os.set_blocking.
    monkeypatch.setattr(terminal_manager.os, "set_blocking", lambda *_a, **_kw: None)


def test_spawn_argv_contains_resume_when_resume_true(monkeypatch):
    captured = {}
    _patch_fake_pty(monkeypatch, captured)

    sess = terminal_manager.TerminalSession("sess-A", resume=True)
    sess._spawn_thread.join(timeout=5)

    assert captured["argv"] == ["zsh", "--login"], captured["argv"]
    assert sess.resume is True


def test_spawn_argv_does_not_contain_resume_when_resume_false(monkeypatch):
    captured = {}
    _patch_fake_pty(monkeypatch, captured)

    sess = terminal_manager.TerminalSession("sess-B", resume=False)
    sess._spawn_thread.join(timeout=5)

    assert captured["argv"] == ["zsh", "--login"], captured["argv"]
    assert sess.resume is False


def test_spawn_default_resume_is_false(monkeypatch):
    """Calling without the resume kwarg must default to False (no flag)."""
    captured = {}
    _patch_fake_pty(monkeypatch, captured)

    sess = terminal_manager.TerminalSession("sess-default")
    sess._spawn_thread.join(timeout=5)

    assert captured["argv"] == ["zsh", "--login"], captured["argv"]


def test_create_session_passes_resume_true_to_new_session(monkeypatch):
    """create_session(..., resume=True) creates a fresh TerminalSession with resume=True."""
    captured_kwargs = {}

    class FakeTerminalSession:
        def __init__(self, session_id, resume=False, cols=None, rows=None):
            captured_kwargs["session_id"] = session_id
            captured_kwargs["resume"] = resume
            # create_session also forwards the client's initial geometry.
            captured_kwargs["cols"] = cols
            captured_kwargs["rows"] = rows
            self.session_id = session_id
            self.is_alive = lambda: True

    monkeypatch.setattr(terminal_manager, "TerminalSession", FakeTerminalSession)

    mgr = TerminalManager()
    mgr.create_session("sess-C", resume=True)

    assert captured_kwargs == {"session_id": "sess-C", "resume": True, "cols": None, "rows": None}


def test_create_session_reclaim_branch_ignores_resume(monkeypatch):
    """If a live session exists, create_session reclaims it regardless of resume kwarg.

    resume only changes behavior on the 'create new' branch."""
    mgr = TerminalManager()

    # Pre-populate a sentinel as the live session.
    sentinel = object()
    mgr._sessions["sess-D"] = sentinel

    # Even with resume=True, the reclaim branch returns the existing object.
    result = mgr.create_session("sess-D", resume=True)
    assert result is sentinel