"""Launch the patched upstream GCN experiment from its expected working directory."""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


def main() -> None:
    """Run the upstream training script while preserving its path assumptions."""

    repository_root = Path(__file__).resolve().parent
    training_directory = repository_root / "gcn"
    if not training_directory.is_dir():
        raise FileNotFoundError(f"Upstream GCN source is missing: {training_directory}")

    # The official loader resolves Cora files relative to the current working
    # directory, while its imports expect the repository root on sys.path.
    os.chdir(str(training_directory))
    sys.path.insert(0, str(repository_root))
    runpy.run_path(str(training_directory / "train.py"), run_name="__main__")


if __name__ == "__main__":
    main()
