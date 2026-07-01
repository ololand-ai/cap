from __future__ import annotations

from typing import Any

from claude_platform.config import Settings


def build_client(settings: Settings) -> Any:
    """Construct the AnthropicAWS client. anthropic is imported lazily so the
    rest of the CLI (and its tests) need no AWS creds just to load."""
    import anthropic

    return anthropic.AnthropicAWS(
        workspace_id=settings.workspace_id,
        aws_region=settings.region,
    )
