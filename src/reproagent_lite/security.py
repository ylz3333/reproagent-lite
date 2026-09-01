"""Safety checks shared by local and container execution backends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


class SecurityError(ValueError):
    """Raised when an execution request violates a hard safety invariant."""


_DISALLOWED_ARGUMENT_CHARS = {"\x00", "\r", "\n"}


def resolve_inside(base: Path, candidate: str | Path) -> Path:
    """Resolve *candidate* and require it to stay inside *base*."""

    base_resolved = base.resolve()
    candidate_path = Path(candidate)
    resolved = (
        candidate_path.resolve()
        if candidate_path.is_absolute()
        else (base_resolved / candidate_path).resolve()
    )
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise SecurityError(f"Path escapes the allowed workspace: {candidate}") from exc
    return resolved


def validate_command(command: Iterable[str]) -> tuple[str, ...]:
    """Validate a list-form command suitable for ``subprocess`` with ``shell=False``."""

    normalized = tuple(str(part) for part in command)
    if not normalized:
        raise SecurityError("Experiment command must not be empty")
    if len(normalized) > 128:
        raise SecurityError("Experiment command has too many arguments")
    for part in normalized:
        if not part:
            raise SecurityError("Experiment command contains an empty argument")
        if len(part) > 4096:
            raise SecurityError("Experiment command argument is too long")
        if any(char in part for char in _DISALLOWED_ARGUMENT_CHARS):
            raise SecurityError("Experiment command contains a control character")
    return normalized


def minimal_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a deliberately small environment without inherited credentials."""

    allowed_names = (
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    )
    environment = {name: os.environ[name] for name in allowed_names if name in os.environ}
    environment["PYTHONHASHSEED"] = "0"
    if extra:
        for name, value in extra.items():
            if "KEY" in name.upper() or "TOKEN" in name.upper() or "SECRET" in name.upper():
                raise SecurityError(f"Credential-like environment variable is not allowed: {name}")
            environment[str(name)] = str(value)
    return environment

