"""Contract tests for strict task parsing and cross-field validation."""

from __future__ import annotations

import json
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

    def test_seed_requirement_must_be_achievable(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["claim"]["acceptance"]["min_successful_seeds"] = 4
        with self.assertRaisesRegex(ModelValidationError, "cannot exceed"):
            TaskSpec.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
