"""Scientific-verdict tests for metric parsing, aggregation, and tolerance."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reproagent_lite.models import TaskSpec
from reproagent_lite.verifier import MetricReadError, read_metric, verify


class VerifierTests(unittest.TestCase):
    """Cover PASS, FAIL, INCONCLUSIVE, and malformed metric artifacts."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.task = TaskSpec.from_json_file(
            root / "examples" / "linear-regression" / "task.json"
        )

    def test_matching_multi_seed_values_pass(self) -> None:
        result = verify(
            self.task,
            [0.5120403941125949, 0.524385417908034, 0.4806082435786309],
        )
        self.assertEqual(result.status, "PASS")

    def test_out_of_tolerance_values_fail(self) -> None:
        result = verify(self.task, [1.0, 1.0, 1.0])
        self.assertEqual(result.status, "FAIL")

    def test_missing_seeds_are_inconclusive(self) -> None:
        result = verify(self.task, [self.task.expected_value])
        self.assertEqual(result.status, "INCONCLUSIVE")

    def test_metric_rejects_duplicate_json_keys(self) -> None:
        payloads = (
            '{"rmse": 9.0, "rmse": 0.5}',
            '{"test": {"rmse": 9.0, "rmse": 0.5}}',
            '{"test": {"rmse": 9.0}, "test": {"rmse": 0.5}}',
        )
        with tempfile.TemporaryDirectory() as directory:
            metric_path = Path(directory) / "metrics.json"
            for payload in payloads:
                with self.subTest(payload=payload):
                    metric_path.write_text(payload, encoding="utf-8")
                    key = "test.rmse" if '"test"' in payload else "rmse"
                    with self.assertRaisesRegex(MetricReadError, "duplicate JSON field"):
                        read_metric(metric_path, key)

    def test_metric_allows_same_key_in_separate_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metric_path = Path(directory) / "metrics.json"
            metric_path.write_text(
                '{"train": {"rmse": 0.1}, "test": {"rmse": 0.5}}', encoding="utf-8"
            )
            self.assertEqual(read_metric(metric_path, "train.rmse"), 0.1)
            self.assertEqual(read_metric(metric_path, "test.rmse"), 0.5)

    def test_metric_key_supports_nested_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metric_path = Path(directory) / "metrics.json"
            metric_path.write_text(json.dumps({"test": {"rmse": 0.5}}), encoding="utf-8")
            self.assertEqual(read_metric(metric_path, "test.rmse"), 0.5)
            with self.assertRaises(MetricReadError):
                read_metric(metric_path, "missing")


if __name__ == "__main__":
    unittest.main()
