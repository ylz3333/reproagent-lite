"""Contract tests for strict task parsing and cross-field validation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from reproagent_lite.models import AcceptanceSpec, ModelValidationError, TaskSpec


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

    def test_relative_tolerance_does_not_accept_overflowed_difference(self) -> None:
        for expected in (1.2e308, -1.2e308):
            for mode in ("relative", "both"):
                for relative, accepted in ((1.5, False), (2.0, True), (2.5, True)):
                    with self.subTest(expected=expected, mode=mode, relative=relative):
                        rule = AcceptanceSpec(
                            expected=expected, mode=mode,
                            tolerance=relative if mode == "relative" else 0.0,
                            relative_tolerance=relative if mode == "both" else None,
                        )
                        self.assertEqual(rule.check(-expected), accepted)

    def test_unknown_fields_are_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["unexpected"] = True
        with self.assertRaisesRegex(ModelValidationError, "unknown field"):
            TaskSpec.from_dict(payload)

    def test_seed_requirement_must_be_achievable(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["claim"]["acceptance"]["min_successful_seeds"] = 4
        with self.assertRaisesRegex(ModelValidationError, "cannot exceed"):
            TaskSpec.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
