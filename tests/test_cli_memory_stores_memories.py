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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "mem_1", "path": "notes/a",
                                                    "created_at": "2026-06-23"})
    mems = MagicMock(spec=["list", "create", "retrieve", "update", "delete"])
    mems.list.return_value = [obj]
    mems.create.return_value = obj
    mems.retrieve.return_value = obj
    stores = types.SimpleNamespace(memories=mems)
    return types.SimpleNamespace(beta=types.SimpleNamespace(memory_stores=stores)), mems


def test_create_parent_positional_plus_json(monkeypatch):
    fake, mems = _fake()
    _patch_client(monkeypatch, fake)
    body = '{"content": "hello", "path": "notes/a"}'
    result = runner.invoke(
        app, ["--json", "memory-stores", "memories", "create", "store_1", "--data", body])
    assert result.exit_code == 0, result.output
    args, kwargs = mems.create.call_args
    assert args == ("store_1",) and kwargs == {"content": "hello", "path": "notes/a"}


def test_get_own_id_positional_parent_keyword(monkeypatch):
    fake, mems = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "memory-stores", "memories", "get", "mem_1", "--memory-store", "store_1"])
    assert result.exit_code == 0, result.output
    mems.retrieve.assert_called_once_with("mem_1", memory_store_id="store_1")
