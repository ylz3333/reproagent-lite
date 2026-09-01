"""Deterministic SHA-256 helpers used by evidence manifests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of one file without loading it all into memory."""

    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root: str | Path) -> Iterable[Path]:
    """Yield evidence-bearing files in a stable cross-platform order.

    Git metadata and Python bytecode caches are excluded because neither is an
    experiment input.  Everything else, including untracked instrumentation,
    participates in the source-tree digest.
    """

    root_path = Path(root).resolve()
    for path in sorted(root_path.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and not {"__pycache__", ".git"}.intersection(path.parts):
            yield path


def sha256_tree(root: str | Path) -> str:
    """Hash relative paths and file bytes so directory moves do not change the digest."""

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)
    digest = hashlib.sha256()
    for path in iter_files(root_path):
        relative = path.relative_to(root_path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        file_digest = bytes.fromhex(sha256_file(path))
        digest.update(file_digest)
    return digest.hexdigest()


def evidence_hashes(
    paths: Iterable[str | Path],
    *,
    relative_to: str | Path | None = None,
) -> dict[str, str]:
    """Hash existing evidence files and optionally make their labels portable.

    Missing paths are ignored so a failed process can still produce a partial
    evidence manifest.  When ``relative_to`` is supplied, in-root paths are
    recorded relative to the run directory rather than leaking host paths.
    """

    root = Path(relative_to).resolve() if relative_to is not None else None
    hashes: dict[str, str] = {}
    for item in paths:
        path = Path(item)
        if path.is_file():
            key = str(path)
            if root is not None:
                try:
                    key = path.resolve().relative_to(root).as_posix()
                except ValueError:
                    pass
            hashes[key] = sha256_file(path)
    return hashes
