"""Contract tests for strict task parsing and cross-field validation."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from reproagent_lite.models import ModelValidationError, TaskSpec


class ModelTests(unittest.TestCase):
    """Exercise accepted task documents and fail-closed schema behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parents[1]
        cls.task_path = project_root / "examples" / "linear-regression" / "task.json"
        cls.payload = json.loads(cls.task_path.read_text(encoding="utf-8"))

    def test_example_round_trips(self) -> None:
        task = TaskSpec.from_dict(self.payload)
        self.assertEqual(TaskSpec.from_dict(task.to_dict()), task)
        self.assertIsNone(task.paper.pdf_path)

    def test_unknown_fields_are_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["unexpected"] = True
        with self.assertRaisesRegex(ModelValidationError, "unknown field"):
            TaskSpec.from_dict(payload)

    def test_overflowing_numeric_task_fields_are_validation_errors(self) -> None:
        paths = (
            ("claim", "reported_value"),
            ("claim", "acceptance", "tolerance"),
            ("execution", "cpu_limit"),
            ("paper", "evidence", 0, "confidence"),
        )
        for path in paths:
            for sign in (1, -1):
                with self.subTest(path=path, sign=sign):
                    payload = json.loads(json.dumps(self.payload))
                    target = payload
                    for component in path[:-1]:
                        target = target[component]
                    target[path[-1]] = sign * 10**400
                    with self.assertRaisesRegex(ModelValidationError, "must be finite"):
                        TaskSpec.from_json(json.dumps(payload))

    def test_seed_requirement_must_be_achievable(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["claim"]["acceptance"]["min_successful_seeds"] = 4
        with self.assertRaisesRegex(ModelValidationError, "cannot exceed"):
            TaskSpec.from_dict(payload)

    def test_integer_digit_limit_is_a_task_validation_error(self) -> None:
        previous_limit = sys.get_int_max_str_digits()
        self.addCleanup(sys.set_int_max_str_digits, previous_limit)
        sys.set_int_max_str_digits(640)
        for sign in ("", "-"):
            with self.subTest(sign=sign):
                text = '{"value":' + sign + "9" * 641 + "}"
                with self.assertRaisesRegex(ModelValidationError, "invalid JSON number"):
                    TaskSpec.from_json(text)

    def test_json_errors_keep_specific_diagnostics(self) -> None:
        cases = (
            ('{"x":1,"x":2}', "duplicate JSON field 'x'"),
            ('{"x":NaN}', "non-standard JSON number 'NaN'"),
            ('{"x":}', "invalid JSON at line 1, column 6"),
        )
        for text, message in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ModelValidationError, message):
                    TaskSpec.from_json(text)


if __name__ == "__main__":
    unittest.main()
