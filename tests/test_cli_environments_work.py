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
    # BetaSelfHostedWork uses `state` (not status); the queue-stats model is a different shape.
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "work_1", "state": "queued",
                                                    "created_at": "2026-06-23"})
    stats_obj = types.SimpleNamespace(model_dump=lambda: {
        "type": "work_queue_stats", "depth": 3, "pending": 2,
        "workers_polling": 1, "oldest_queued_at": "2026-06-23"})
    work = MagicMock(spec=["list", "retrieve", "stats"])
    work.list.return_value = [obj]
    work.retrieve.return_value = obj
    work.stats.return_value = stats_obj
    envs = types.SimpleNamespace(work=work)
    return types.SimpleNamespace(beta=types.SimpleNamespace(environments=envs)), work


def test_list_parent_positional(monkeypatch):
    fake, work = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "environments", "work", "list", "env_1"])
    assert result.exit_code == 0, result.output
    work.list.assert_called_once_with("env_1")


def test_get_own_id_positional_parent_keyword(monkeypatch):
    fake, work = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "environments", "work", "get", "work_1", "--environment", "env_1"])
    assert result.exit_code == 0, result.output
    work.retrieve.assert_called_once_with("work_1", environment_id="env_1")


def test_stats_parent_positional(monkeypatch):
    fake, work = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "environments", "work", "stats", "env_1"])
    assert result.exit_code == 0, result.output
    work.stats.assert_called_once_with("env_1")


def test_stats_table_uses_per_verb_columns(monkeypatch):
    # Non-JSON path: the stats response model diverges from the node's columns, so the
    # `stats` verb carries its own columns — the rendered table must show the stats fields,
    # not blank id/state/created_at cells.
    fake, work = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["environments", "work", "stats", "env_1"])
    assert result.exit_code == 0, result.output
    for col in ("depth", "pending", "workers_polling"):
        assert col in result.output
    assert "3" in result.output and "2" in result.output  # depth / pending values rendered


def test_data_plane_verbs_absent(monkeypatch):
    # charter: poll/ack/heartbeat/stop/update are NOT exposed (data plane).
    result = runner.invoke(app, ["environments", "work", "--help"])
    assert result.exit_code == 0
    for excluded in ("poll", "ack", "heartbeat", "stop"):
        assert excluded not in result.output
