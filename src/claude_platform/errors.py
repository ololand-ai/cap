from __future__ import annotations

from claude_platform.config import ConfigError
from claude_platform.safety import SafetyAbort

try:  # anthropic is a hard runtime dep, but keep import failures from masking errors
    from anthropic import AnthropicError as _AnthropicError
except Exception:  # pragma: no cover - anthropic always present at runtime
    _AnthropicError = ()  # type: ignore[assignment]


def format_error(exc: Exception) -> tuple[str, int]:
    if isinstance(exc, ConfigError):
        return (str(exc), 3)
    if isinstance(exc, SafetyAbort):
        return (str(exc), 4)
    # All SDK failures (401 auth, 403 permission, missing/unreachable creds,
    # 400 bad request, ...) subclass anthropic.AnthropicError. Use isinstance
    # rather than fragile class-name substring matching (those leaf class names
    # contain neither "Anthropic" nor "APIError"). Fall back to a name check on
    # the MRO so a locally-defined `AnthropicError` still maps to exit 5.
    if _AnthropicError and isinstance(exc, _AnthropicError):
        return (f"API error: {exc}", 5)
    mro_names = {c.__name__ for c in type(exc).__mro__}
    if mro_names & {"AnthropicError", "APIError", "APIStatusError"}:
        return (f"API error: {exc}", 5)
    return (str(exc), 1)
