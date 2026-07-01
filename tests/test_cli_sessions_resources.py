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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "res_1", "type": "file",
                                                    "mount_path": "/in/a"})
    res = MagicMock(spec=["add", "list", "retrieve", "update", "delete"])
    res.add.return_value = obj
    res.update.return_value = obj
    sessions = types.SimpleNamespace(resources=res)
    return types.SimpleNamespace(beta=types.SimpleNamespace(sessions=sessions)), res


def test_add_parent_positional_plus_json(monkeypatch):
    fake, res = _fake()
    _patch_client(monkeypatch, fake)
    body = '{"file_id": "f_1", "type": "file", "mount_path": "/in/a"}'
    result = runner.invoke(
        app, ["--json", "sessions", "resources", "add", "session_1", "--data", body])
    assert result.exit_code == 0, result.output
    args, kwargs = res.add.call_args
    assert args == ("session_1",)
    assert kwargs == {"file_id": "f_1", "type": "file", "mount_path": "/in/a"}


def test_update_own_id_positional_parent_keyword(monkeypatch):
    fake, res = _fake()
    _patch_client(monkeypatch, fake)
    body = '{"authorization_token": "tok"}'
    result = runner.invoke(
        app, ["--json", "sessions", "resources", "update", "res_1",
              "--session", "session_1", "--data", body])
    assert result.exit_code == 0, result.output
    args, kwargs = res.update.call_args
    assert args == ("res_1",) and kwargs["session_id"] == "session_1"
    assert kwargs["authorization_token"] == "tok"
