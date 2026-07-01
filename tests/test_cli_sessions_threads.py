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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "thread_1", "created_at": "2026-06-23"})
    threads = MagicMock(spec=["list", "retrieve", "archive"])
    threads.list.return_value = [obj]
    threads.archive.return_value = obj
    sessions = types.SimpleNamespace(threads=threads)
    return types.SimpleNamespace(beta=types.SimpleNamespace(sessions=sessions)), threads


def test_list_parent_positional(monkeypatch):
    fake, threads = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "sessions", "threads", "list", "session_1"])
    assert result.exit_code == 0, result.output
    threads.list.assert_called_once_with("session_1")


def test_archive_gated_then_calls_sdk(monkeypatch):
    fake, threads = _fake()
    _patch_client(monkeypatch, fake)
    blocked = runner.invoke(
        app, ["sessions", "threads", "archive", "thread_1", "--session", "session_1"])
    assert blocked.exit_code == 4
    threads.archive.assert_not_called()
    ok = runner.invoke(
        app, ["--yes", "sessions", "threads", "archive", "thread_1", "--session", "session_1"])
    assert ok.exit_code == 0, ok.output
    threads.archive.assert_called_once_with("thread_1", session_id="session_1")
