import json
import types
from unittest.mock import MagicMock

from typer.testing import CliRunner
import claude_platform.cli as climod
from claude_platform.cli import app

runner = CliRunner()


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(climod, "load_settings", lambda profile=None: types.SimpleNamespace(
        workspace_id="wrkspc_x", region="us-east-1", profile="aws"))
    monkeypatch.setattr(climod, "build_client", lambda settings: fake)


def _fake():
    ev = types.SimpleNamespace(model_dump=lambda: {"id": "ev_1", "type": "user.message",
                                                   "created_at": "2026-06-23"})
    thread_events = MagicMock(spec=["list"])
    thread_events.list.return_value = [ev]
    threads = types.SimpleNamespace(events=thread_events)
    session_events = MagicMock(spec=["list"])
    session_events.list.return_value = [ev]
    sessions = types.SimpleNamespace(threads=threads, events=session_events)
    return (types.SimpleNamespace(beta=types.SimpleNamespace(sessions=sessions)),
            thread_events, session_events)


def test_two_deep_events_list_threads_immediate_positional_grandparent_keyword(monkeypatch):
    fake, thread_events, _ = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "sessions", "threads", "events", "list", "thread_1",
              "--session", "session_1"])
    assert result.exit_code == 0, result.output
    # immediate parent (thread) positional; grandparent (session) keyword-only.
    thread_events.list.assert_called_once_with("thread_1", session_id="session_1")
    assert json.loads(result.output)[0]["id"] == "ev_1"


def test_session_level_events_list_parent_positional(monkeypatch):
    fake, _, session_events = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "sessions", "events", "list", "session_1"])
    assert result.exit_code == 0, result.output
    session_events.list.assert_called_once_with("session_1")


def test_threads_subtyper_lists_events(monkeypatch):
    result = runner.invoke(app, ["sessions", "threads", "--help"])
    assert result.exit_code == 0
    assert "events" in result.output
