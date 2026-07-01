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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "run_1", "status": "succeeded",
                                                    "created_at": "2026-06-23"})
    runs = MagicMock(spec=["list", "retrieve"])
    runs.list.return_value = [obj]
    runs.retrieve.return_value = obj
    return types.SimpleNamespace(beta=types.SimpleNamespace(deployment_runs=runs)), runs


def test_list_passes_only_data_filters_no_positional(monkeypatch):
    fake, runs = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "deployment-runs", "list", "--data",
              '{"deployment_id": "dep_1", "has_error": true}'])
    assert result.exit_code == 0, result.output
    args, kwargs = runs.list.call_args
    assert args == () and kwargs == {"deployment_id": "dep_1", "has_error": True}


def test_get_run(monkeypatch):
    fake, runs = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "deployment-runs", "get", "run_1"])
    assert result.exit_code == 0, result.output
    runs.retrieve.assert_called_once_with("run_1")
