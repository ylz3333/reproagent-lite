"""Backend tests for local opt-in and Docker containment construction."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reproagent_lite.runner import DockerRunner, LocalRunner, RunLimits
from reproagent_lite.security import SecurityError


class RunnerTests(unittest.TestCase):
    """Verify process evidence, resource controls, and timeout cleanup."""

    def test_local_runner_requires_explicit_opt_in(self) -> None:
        with self.assertRaises(SecurityError):
            LocalRunner()

    def test_local_runner_passes_seed_and_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            script = source / "experiment.py"
            script.write_text(
                "import json, os, pathlib\n"
                "out = pathlib.Path(os.environ['REPRO_OUTPUT_DIR'])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'metrics.json').write_text(json.dumps("
                "{'score': int(os.environ['REPRO_SEED'])}))\n",
                encoding="utf-8",
            )
            result = LocalRunner(allow_unsafe_local=True).run(
                source_directory=source,
                output_directory=output,
                command=("{python}", "experiment.py"),
                seed=7,
                limits=RunLimits(timeout_seconds=10, memory_mb=128),
            )
            self.assertTrue(result.succeeded)
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["score"], 7)

    def test_docker_runner_builds_once_and_applies_isolation_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            output_one = root / "one"
            output_two = root / "two"
            completed = subprocess.CompletedProcess([], 0, "", "")
            with (
                mock.patch("reproagent_lite.runner.shutil.which", return_value="docker"),
                mock.patch("reproagent_lite.runner.subprocess.run", return_value=completed) as run,
            ):
                runner = DockerRunner()
                runner.run(
                    source_directory=source,
                    output_directory=output_one,
                    command=("python", "experiment.py"),
                    seed=7,
                    limits=RunLimits(timeout_seconds=10, memory_mb=128),
                )
                runner.run(
                    source_directory=source,
                    output_directory=output_two,
                    command=("python", "experiment.py"),
                    seed=19,
                    limits=RunLimits(timeout_seconds=10, memory_mb=128),
                )

            self.assertEqual(run.call_count, 3)
            build_command = run.call_args_list[0].args[0]
            first_run_command = run.call_args_list[1].args[0]
            self.assertEqual(build_command[:2], ["docker", "build"])
            self.assertIn("none", build_command)
            for flag in ("--read-only", "--cap-drop", "--pids-limit", "--memory"):
                self.assertIn(flag, first_run_command)

    def test_docker_timeout_forces_container_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            build = subprocess.CompletedProcess([], 0, "", "")
            cleanup = subprocess.CompletedProcess([], 0, "", "")
            timeout = subprocess.TimeoutExpired("docker run", 1, output="partial")
            with (
                mock.patch("reproagent_lite.runner.shutil.which", return_value="docker"),
                mock.patch(
                    "reproagent_lite.runner.subprocess.run",
                    side_effect=[build, timeout, cleanup],
                ) as run,
            ):
                result = DockerRunner().run(
                    source_directory=source,
                    output_directory=root / "output",
                    command=("python", "experiment.py"),
                    seed=7,
                    limits=RunLimits(timeout_seconds=1, memory_mb=128),
                )

            self.assertTrue(result.timed_out)
            self.assertEqual(result.error_class, "TIMEOUT")
            self.assertEqual(run.call_args_list[2].args[0][1:3], ["rm", "--force"])

    def test_build_network_does_not_enable_runtime_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with (
                mock.patch("reproagent_lite.runner.shutil.which", return_value="docker"),
                mock.patch("reproagent_lite.runner.subprocess.run", return_value=completed) as run,
            ):
                DockerRunner().run(
                    source_directory=source,
                    output_directory=root / "output",
                    command=("python", "experiment.py"),
                    seed=7,
                    limits=RunLimits(
                        timeout_seconds=10,
                        memory_mb=128,
                        build_network=True,
                        network=False,
                    ),
                )

            build_command = run.call_args_list[0].args[0]
            runtime_command = run.call_args_list[1].args[0]
            self.assertNotIn("--network", build_command)
            network_index = runtime_command.index("--network")
            self.assertEqual(runtime_command[network_index + 1], "none")


if __name__ == "__main__":
    unittest.main()
