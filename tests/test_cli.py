"""Protect the command-line validation contract used by automation."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from reproagent_lite.cli import main


class ValidationCLITests(unittest.TestCase):
    def test_overflow_returns_failure_and_field_error_without_success_output(self):
        example = Path(__file__).resolve().parents[1] / "examples/linear-regression/task.json"
        with tempfile.TemporaryDirectory() as directory:
            task_path = Path(directory) / "task.json"
            for value in (10**400, -(10**400)):
                with self.subTest(sign=value > 0):
                    payload = json.loads(example.read_text(encoding="utf-8"))
                    payload["claim"]["reported_value"] = value
                    task_path.write_text(json.dumps(payload), encoding="utf-8")
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = main(["validate", str(task_path)])
                    self.assertEqual(code, 1)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertEqual(stderr.getvalue(), "error: claim.reported_value must be finite\n")

    def test_valid_task_returns_success_without_error_output(self):
        example = Path(__file__).resolve().parents[1] / "examples/linear-regression/task.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["validate", str(example)])
        self.assertEqual(code, 0)
        self.assertTrue(stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
