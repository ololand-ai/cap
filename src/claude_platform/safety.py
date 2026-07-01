from __future__ import annotations

DESTRUCTIVE = frozenset({"delete", "archive"})


class SafetyAbort(Exception):
    """Raised when a destructive verb is attempted without --yes."""


def check(verb: str, target: str, yes: bool, *, destructive: bool = False) -> None:
    if (destructive or verb in DESTRUCTIVE) and not yes:
        raise SafetyAbort(
            f"Refusing to {verb} '{target}' without --yes. "
            f"Re-run with --yes to confirm."
        )
