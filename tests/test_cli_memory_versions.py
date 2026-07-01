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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "ver_1", "created_at": "2026-06-23"})
    mv = MagicMock(spec=["list", "retrieve", "redact"])
    mv.list.return_value = [obj]
    mv.redact.return_value = obj
    stores = types.SimpleNamespace(memory_versions=mv)
    return types.SimpleNamespace(beta=types.SimpleNamespace(memory_stores=stores)), mv


def test_list_parent_positional(monkeypatch):
    fake, mv = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "memory-stores", "memory-versions", "list", "store_1"])
    assert result.exit_code == 0, result.output
    mv.list.assert_called_once_with("store_1")


def test_redact_without_yes_is_gated(monkeypatch):
    fake, mv = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["memory-stores", "memory-versions", "redact", "ver_1", "--memory-store", "store_1"])
    assert result.exit_code == 4
    mv.redact.assert_not_called()


def test_redact_with_yes_calls_sdk(monkeypatch):
    fake, mv = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--yes", "memory-stores", "memory-versions", "redact", "ver_1",
              "--memory-store", "store_1"])
    assert result.exit_code == 0, result.output
    mv.redact.assert_called_once_with("ver_1", memory_store_id="store_1")
