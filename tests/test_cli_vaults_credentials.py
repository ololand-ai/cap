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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "cred_1", "display_name": "mcp",
                                                    "created_at": "2026-06-23"})
    creds = MagicMock(spec=["list", "create", "retrieve", "update", "delete",
                            "archive", "mcp_oauth_validate"])
    creds.list.return_value = [obj]
    creds.retrieve.return_value = obj
    creds.create.return_value = obj
    creds.mcp_oauth_validate.return_value = obj
    vaults = types.SimpleNamespace(credentials=creds)
    return types.SimpleNamespace(beta=types.SimpleNamespace(vaults=vaults)), creds


def test_list_passes_parent_positional(monkeypatch):
    fake, creds = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "vaults", "credentials", "list", "vault_1"])
    assert result.exit_code == 0, result.output
    creds.list.assert_called_once_with("vault_1")


def test_get_passes_own_id_positional_parent_keyword(monkeypatch):
    fake, creds = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "vaults", "credentials", "get", "cred_1", "--vault", "vault_1"])
    assert result.exit_code == 0, result.output
    creds.retrieve.assert_called_once_with("cred_1", vault_id="vault_1")  # own id pos, parent kw


def test_create_merges_json_into_kwargs(monkeypatch):
    fake, creds = _fake()
    _patch_client(monkeypatch, fake)
    body = '{"display_name": "mcp", "auth": {"type": "oauth"}}'
    result = runner.invoke(
        app, ["--json", "vaults", "credentials", "create", "vault_1", "--data", body])
    assert result.exit_code == 0, result.output
    args, kwargs = creds.create.call_args
    assert args == ("vault_1",) and kwargs["display_name"] == "mcp"
    assert kwargs["auth"] == {"type": "oauth"}


def test_validate_dispatches_to_mcp_oauth_validate(monkeypatch):
    fake, creds = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "vaults", "credentials", "validate", "cred_1", "--vault", "vault_1"])
    assert result.exit_code == 0, result.output
    creds.mcp_oauth_validate.assert_called_once_with("cred_1", vault_id="vault_1")


def test_delete_without_yes_blocks_and_never_builds_client(monkeypatch):
    fake, creds = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["vaults", "credentials", "delete", "cred_1", "--vault", "vault_1"])
    assert result.exit_code == 4
    creds.delete.assert_not_called()


def test_delete_with_yes_calls_sdk(monkeypatch):
    fake, creds = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--yes", "vaults", "credentials", "delete", "cred_1", "--vault", "vault_1"])
    assert result.exit_code == 0, result.output
    creds.delete.assert_called_once_with("cred_1", vault_id="vault_1")
