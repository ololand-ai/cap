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
    obj = types.SimpleNamespace(model_dump=lambda: {"id": "up_1", "name": "Acme",
                                                    "relationship": "external"})
    url = types.SimpleNamespace(model_dump=lambda: {"id": "up_1", "url": "https://enroll/x"})
    up = MagicMock(spec=["list", "retrieve", "create", "update", "create_enrollment_url"])
    up.list.return_value = [obj]
    up.create.return_value = obj
    up.create_enrollment_url.return_value = url
    return types.SimpleNamespace(beta=types.SimpleNamespace(user_profiles=up)), up


def test_create_json_no_parent(monkeypatch):
    fake, up = _fake()
    _patch_client(monkeypatch, fake)
    body = '{"external_id": "u1", "relationship": "external", "name": "Acme"}'
    result = runner.invoke(app, ["--json", "user-profiles", "create", "--data", body])
    assert result.exit_code == 0, result.output
    args, kwargs = up.create.call_args
    assert args == () and kwargs["external_id"] == "u1" and kwargs["relationship"] == "external"


def test_create_enrollment_url_self_verb_renders_url(monkeypatch):
    fake, up = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "user-profiles", "create-enrollment-url", "up_1"])
    assert result.exit_code == 0, result.output
    up.create_enrollment_url.assert_called_once_with("up_1")
    assert json.loads(result.output)["url"] == "https://enroll/x"


def test_create_enrollment_url_table_output_includes_url_column(monkeypatch):
    # Non-JSON path exercises the Payload.URL column projection (the --json path bypasses
    # column logic). The url must surface as a column in the rendered table.
    fake, up = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["user-profiles", "create-enrollment-url", "up_1"])
    assert result.exit_code == 0, result.output
    assert "url" in result.output and "https://enroll/x" in result.output
