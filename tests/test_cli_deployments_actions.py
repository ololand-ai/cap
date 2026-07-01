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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "dep_1", "created_at": "2026-06-23"})
    dep = MagicMock(spec=["list", "retrieve", "create", "update", "archive",
                          "pause", "unpause", "run"])
    dep.pause.return_value = obj
    dep.unpause.return_value = obj
    dep.run.return_value = obj
    return types.SimpleNamespace(beta=types.SimpleNamespace(deployments=dep)), dep


def test_pause_unpause_not_gated(monkeypatch):
    fake, dep = _fake()
    _patch_client(monkeypatch, fake)
    p = runner.invoke(app, ["--json", "deployments", "pause", "dep_1"])
    assert p.exit_code == 0, p.output
    dep.pause.assert_called_once_with("dep_1")
    u = runner.invoke(app, ["--json", "deployments", "unpause", "dep_1"])
    assert u.exit_code == 0, u.output
    dep.unpause.assert_called_once_with("dep_1")


def test_run_is_gated_billable(monkeypatch):
    fake, dep = _fake()
    _patch_client(monkeypatch, fake)
    blocked = runner.invoke(app, ["deployments", "run", "dep_1"])
    assert blocked.exit_code == 4
    dep.run.assert_not_called()
    ok = runner.invoke(app, ["--yes", "--json", "deployments", "run", "dep_1"])
    assert ok.exit_code == 0, ok.output
    dep.run.assert_called_once_with("dep_1")
