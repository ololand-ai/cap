import sys
import types
from claude_platform.client import build_client
from claude_platform.config import Settings

def test_build_client_passes_workspace_and_region(monkeypatch):
    captured = {}

    class FakeAWS:
        def __init__(self, *, workspace_id, aws_region):
            captured["workspace_id"] = workspace_id
            captured["aws_region"] = aws_region

    fake_anthropic = types.ModuleType("anthropic")
    fake_anthropic.AnthropicAWS = FakeAWS
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    client = build_client(Settings(workspace_id="wrkspc_x", region="us-east-1", profile="aws"))
    assert isinstance(client, FakeAWS)
    assert captured == {"workspace_id": "wrkspc_x", "aws_region": "us-east-1"}
