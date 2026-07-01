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
    ver = types.SimpleNamespace(model_dump=lambda: {"id": "ver_1", "created_at": "2026-06-23"})
    versions = MagicMock(spec=["list"])           # only `list` exists -> stray .get raises
    versions.list.return_value = [ver]
    agents = types.SimpleNamespace(versions=versions)
    return types.SimpleNamespace(beta=types.SimpleNamespace(agents=agents)), versions


def test_agents_versions_list_calls_sdk_with_parent_positional(monkeypatch):
    fake, versions = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "agents", "versions", "list", "agent_1"])
    assert result.exit_code == 0, result.output
    versions.list.assert_called_once_with("agent_1")          # immediate parent positional
    assert json.loads(result.output)[0]["id"] == "ver_1"


def test_agents_versions_subtyper_present(monkeypatch):
    result = runner.invoke(app, ["agents", "--help"])
    assert result.exit_code == 0
    for tok in ("list", "get", "create", "update", "archive", "versions"):
        assert tok in result.output
