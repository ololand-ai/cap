import pytest
from claude_platform.safety import check, SafetyAbort, DESTRUCTIVE


def test_named_destructive_without_yes_aborts():
    with pytest.raises(SafetyAbort, match="--yes"):
        check("delete", "agent_1", yes=False)


def test_destructive_flag_without_yes_aborts():
    # a verb NOT in the name set, but flagged destructive (e.g. redact / run)
    with pytest.raises(SafetyAbort, match="--yes"):
        check("redact", "ver_1", yes=False, destructive=True)


def test_destructive_with_yes_passes():
    check("archive", "agent_1", yes=True)
    check("run", "dep_1", yes=True, destructive=True)


def test_nondestructive_always_passes():
    check("list", "agents", yes=False)
    check("validate", "cred_1", yes=False, destructive=False)


def test_destructive_set_unchanged():
    assert DESTRUCTIVE == frozenset({"delete", "archive"})
