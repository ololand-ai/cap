import json
import types
from unittest.mock import MagicMock
from typer.testing import CliRunner
import claude_platform.cli as climod
from claude_platform.cli import app

runner = CliRunner()

def _patch_client(monkeypatch, fake_client):
    # Bypass config + AWS: feed a canned client into the CLI.
    monkeypatch.setattr(climod, "load_settings", lambda profile=None: types.SimpleNamespace(
        workspace_id="wrkspc_x", region="us-east-1", profile="aws"))
    monkeypatch.setattr(climod, "build_client", lambda settings: fake_client)

def _fake_client_with_agents():
    agent = types.SimpleNamespace(model_dump=lambda: {"id": "agent_1", "name": "career-copilot",
                                                      "created_at": "2026-06-19"})
    agents = MagicMock()
    agents.list.return_value = [agent]
    agents.archive = MagicMock()
    beta = types.SimpleNamespace(agents=agents)
    return types.SimpleNamespace(beta=beta)

def test_agents_list_json(monkeypatch):
    fake = _fake_client_with_agents()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "agents", "list"])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"id": "agent_1", "name": "career-copilot",
                                          "created_at": "2026-06-19"}]
    fake.beta.agents.list.assert_called_once()

def test_auto_json_when_not_a_tty(monkeypatch):
    # CliRunner captures stdout (not a TTY), so output must be JSON even
    # without an explicit --json flag.
    fake = _fake_client_with_agents()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["agents", "list"])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"id": "agent_1", "name": "career-copilot",
                                          "created_at": "2026-06-19"}]

def test_agents_archive_without_yes_blocks(monkeypatch):
    fake = _fake_client_with_agents()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["agents", "archive", "agent_1"])
    assert result.exit_code == 4
    fake.beta.agents.archive.assert_not_called()

def test_agents_archive_with_yes_calls_sdk(monkeypatch):
    fake = _fake_client_with_agents()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--yes", "agents", "archive", "agent_1"])
    assert result.exit_code == 0
    fake.beta.agents.archive.assert_called_once_with("agent_1")


def test_agents_get_dispatches_to_sdk_retrieve(monkeypatch):
    # The SDK exposes `retrieve`, not `get`. The CLI `get` subcommand must call
    # `retrieve` — and must NOT touch a (nonexistent) `get` attribute.
    agent = types.SimpleNamespace(model_dump=lambda: {"id": "agent_1",
                                                      "name": "career-copilot",
                                                      "created_at": "2026-06-19"})
    agents = MagicMock(spec=["retrieve"])  # spec => `.get` raises AttributeError
    agents.retrieve.return_value = agent
    fake = types.SimpleNamespace(beta=types.SimpleNamespace(agents=agents))
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "agents", "get", "agent_1"])
    assert result.exit_code == 0, result.output
    fake.beta.agents.retrieve.assert_called_once_with("agent_1")
    assert json.loads(result.output)["id"] == "agent_1"


def test_files_get_dispatches_to_retrieve_metadata(monkeypatch):
    # files has no `retrieve`; the CLI `get` verb maps to `retrieve_metadata`
    # via the resource's method_overrides.
    meta = types.SimpleNamespace(model_dump=lambda: {"id": "file_1", "created_at": "2026"})
    files = MagicMock(spec=["retrieve_metadata"])  # spec => `.retrieve`/`.get` raise
    files.retrieve_metadata.return_value = meta
    fake = types.SimpleNamespace(beta=types.SimpleNamespace(files=files))
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "files", "get", "file_1"])
    assert result.exit_code == 0, result.output
    files.retrieve_metadata.assert_called_once_with("file_1")
    assert json.loads(result.output)["id"] == "file_1"


def test_json_error_path_emits_json_object(monkeypatch):
    # Under --json (and the auto-JSON non-TTY case), failures must be a JSON
    # error object on stderr, not plain text, so automated callers can parse it.
    agents = MagicMock(spec=["retrieve"])
    agents.retrieve.side_effect = ValueError("boom")
    fake = types.SimpleNamespace(beta=types.SimpleNamespace(agents=agents))
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "agents", "get", "agent_1"])
    assert result.exit_code == 1
    err = json.loads(result.stderr)
    assert err == {"error": "boom", "exit_code": 1}
