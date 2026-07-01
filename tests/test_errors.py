import httpx

from claude_platform.errors import format_error
from claude_platform.config import ConfigError
from claude_platform.safety import SafetyAbort

def test_config_error_code_3():
    msg, code = format_error(ConfigError("No config at X"))
    assert code == 3 and "No config" in msg

def test_safety_abort_code_4():
    msg, code = format_error(SafetyAbort("Refusing to delete"))
    assert code == 4 and "Refusing" in msg

def test_anthropic_error_code_5():
    class AnthropicError(Exception):
        pass
    msg, code = format_error(AnthropicError("401 invalid"))
    assert code == 5 and "401" in msg

def test_unknown_error_code_1():
    msg, code = format_error(ValueError("boom"))
    assert code == 1 and "boom" in msg


def test_real_sdk_errors_map_to_code_5():
    # The exact failure modes the spec names (401/403/missing creds/400) all
    # subclass anthropic.AnthropicError but their leaf names contain neither
    # "Anthropic" nor "APIError" — they must still map to exit 5, not 1.
    import anthropic

    request = httpx.Request("POST", "https://example.invalid")

    def _resp(status):
        return httpx.Response(status, request=request)

    cases = [
        anthropic.AuthenticationError("401", response=_resp(401), body=None),
        anthropic.PermissionDeniedError("403", response=_resp(403), body=None),
        anthropic.BadRequestError("400", response=_resp(400), body=None),
        anthropic.APIConnectionError(message="creds unreachable", request=request),
    ]
    for exc in cases:
        msg, code = format_error(exc)
        assert code == 5, f"{type(exc).__name__} should map to exit 5, got {code}"
        assert "API error" in msg
