import types
import claude_platform.cli as climod
from claude_platform.cli import shell_namespace

def test_shell_namespace_has_client(monkeypatch):
    fake_client = object()
    settings = types.SimpleNamespace(workspace_id="wrkspc_x", region="us-east-1", profile="aws")
    monkeypatch.setattr(climod, "load_settings", lambda profile=None: settings)
    monkeypatch.setattr(climod, "build_client", lambda s: fake_client)
    ns = shell_namespace()
    assert ns["client"] is fake_client and ns["settings"] is settings
