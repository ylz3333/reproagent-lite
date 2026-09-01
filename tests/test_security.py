"""Security-boundary tests for paths, commands, and process environments."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from reproagent_lite.security import (
    SecurityError,
    minimal_environment,
    resolve_inside,
    validate_command,
)


class SecurityTests(unittest.TestCase):
    """Guard against directory escape, shell ambiguity, and secret leakage."""

    def test_resolve_inside_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(SecurityError):
                resolve_inside(base, "../outside.txt")

    def test_validate_command_rejects_control_characters(self) -> None:
        with self.assertRaises(SecurityError):
            validate_command(["python", "bad\nargument"])

    def test_minimal_environment_does_not_copy_credentials(self) -> None:
        previous = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "not-a-real-secret"
        try:
            environment = minimal_environment()
            self.assertNotIn("OPENAI_API_KEY", environment)
        finally:
            if previous is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous


if __name__ == "__main__":
    unittest.main()
