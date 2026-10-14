"""End-to-end workflow tests for evidence creation and Git provenance checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from reproagent_lite.workflow import ReproductionWorkflow


class WorkflowTests(unittest.TestCase):
    """Exercise orchestration across preparation, execution, and reporting."""

    def test_bundled_demo_runs_end_to_end_locally(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        task_path = project_root / "examples" / "linear-regression" / "task.json"
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory) / "run"
            workflow = ReproductionWorkflow(task_path, run_directory)
            result, attempts = workflow.run(backend="local", allow_unsafe_local=True)

            self.assertEqual(result.status, "PASS")
            self.assertEqual(len(attempts), 3)
            self.assertTrue(all(attempt.status == "SUCCEEDED" for attempt in attempts))
            verdict = json.loads(
                (run_directory / "verdict.json").read_text(encoding="utf-8")
            )
            self.assertFalse(verdict["independent_isolation"])
            self.assertTrue(
                all(not Path(path).is_absolute() for path in verdict["evidence_hashes"])
            )
            self.assertIn(
                "trusted local demo",
                (run_directory / "report.md").read_text(encoding="utf-8"),
            )

    def test_overflowing_metric_does_not_abort_remaining_seeds_or_reporting(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        task = json.loads(
            (project_root / "examples" / "linear-regression" / "task.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            # This trusted fixture exercises the real subprocess and artifact pipeline.
            (source / "experiment.py").write_text(
                "import json, os\n"
                "from pathlib import Path\n"
                "seed = int(os.environ['REPRO_SEED'])\n"
                f"value = 10**400 if seed == 7 else {task['claim']['reported_value']!r}\n"
                "(Path(os.environ['REPRO_OUTPUT_DIR']) / 'metrics.json').write_text(\n"
                "    json.dumps({'rmse': value}), encoding='utf-8')\n",
                encoding="utf-8",
            )
            task["source"]["directory"] = "source"
            task_path = root / "task.json"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            run_directory = root / "run"
            result, attempts = ReproductionWorkflow(task_path, run_directory).run(
                backend="local", allow_unsafe_local=True
            )

            self.assertEqual([attempt.seed for attempt in attempts], [7, 19, 42])
            self.assertEqual(
                [attempt.status for attempt in attempts], ["FAILED", "SUCCEEDED", "SUCCEEDED"]
            )
            self.assertIsNone(attempts[0].observed_value)
            self.assertIn("must be finite", attempts[0].error)
            self.assertEqual(result.status, "INCONCLUSIVE")
            self.assertEqual(result.successful_seeds, 2)
            self.assertEqual(len(json.loads((run_directory / "attempts.json").read_text())), 3)
            verdict = json.loads((run_directory / "verdict.json").read_text())
            self.assertEqual(verdict["status"], "INCONCLUSIVE")
            self.assertIn("attempts/seed-7/metrics.json", verdict["evidence_hashes"])
            self.assertIn(
                "INCONCLUSIVE", (run_directory / "report.md").read_text(encoding="utf-8")
            )
            self.assertEqual(
                json.loads((run_directory / "state.json").read_text())["state"], "REPORTED"
            )

    @unittest.skipUnless(shutil.which("git"), "Git is required for provenance test")
    def test_prepare_verifies_registered_git_checkout(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        example_task = json.loads(
            (
                project_root / "examples" / "linear-regression" / "task.json"
            ).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "experiment.py").write_text("print('fixture')\n", encoding="utf-8")

            def git(*arguments: str) -> str:
                completed = subprocess.run(
                    [str(shutil.which("git")), "-C", str(source), *arguments],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                    shell=False,
                )
                return completed.stdout.strip()

            git("init")
            git("config", "user.name", "ReproAgent Test")
            git("config", "user.email", "reproagent@example.invalid")
            git("remote", "add", "origin", "https://example.invalid/repository.git")
            git("add", "experiment.py")
            git("commit", "-m", "fixture")
            commit = git("rev-parse", "HEAD")

            example_task["paper"]["repository_url"] = (
                "https://example.invalid/repository.git"
            )
            example_task["paper"]["commit_sha"] = commit
            example_task["source"]["directory"] = "source"
            task_path = root / "task.json"
            task_path.write_text(json.dumps(example_task), encoding="utf-8")

            workflow = ReproductionWorkflow(task_path, root / "run")
            workflow.prepare(backend="docker")
            manifest = json.loads(
                (root / "run" / "source_manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["repository_verified"])
            self.assertEqual(manifest["repository_head"], commit)


if __name__ == "__main__":
    unittest.main()
