"""Stateful, evidence-first orchestration for one reproduction task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .hashing import evidence_hashes, sha256_file, sha256_tree
from .models import AttemptRecord, TaskSpec, VerificationResult
from .report import render_markdown
from .runner import (
    DockerRunner,
    ExecutionResult,
    LocalRunner,
    RunLimits,
    write_execution_record,
)
from .security import minimal_environment, resolve_inside
from .verifier import MetricReadError, read_metric, verify


class WorkflowError(RuntimeError):
    """Raised when the reproduction workflow cannot continue safely."""


def _now() -> str:
    """Return an unambiguous UTC timestamp for state and evidence records."""

    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    """Atomically replace a JSON artifact so readers never see a partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    temporary.replace(path)


def _normalize_repository_url(value: str) -> str:
    """Normalize equivalent Git remote spellings for provenance comparison."""

    normalized = value.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def _git_output(repository: Path, *arguments: str) -> str:
    """Run one non-interactive Git query against a possibly foreign checkout.

    A temporary isolated config marks only this exact checkout as safe.  This
    avoids changing the user's global Git configuration while still allowing
    Docker-created repositories with a different owner to be audited.
    """

    git = shutil.which("git")
    if git is None:
        raise WorkflowError("Git is required to verify registered repository provenance")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        suffix=".gitconfig",
    ) as handle:
        handle.write(f"[safe]\n\tdirectory = {repository.as_posix()}\n")
        temporary_config = Path(handle.name)
    try:
        completed = subprocess.run(
            [git, "-C", str(repository), *arguments],
            env=minimal_environment(
                {
                    "GIT_CONFIG_GLOBAL": str(temporary_config),
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_TERMINAL_PROMPT": "0",
                }
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkflowError(f"Could not verify Git repository: {exc}") from exc
    finally:
        temporary_config.unlink(missing_ok=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
        raise WorkflowError(f"Could not verify Git repository: {detail}")
    return completed.stdout.strip()


class ReproductionWorkflow:
    """Execute a pre-registered task and persist every material transition."""

    def __init__(self, task_path: str | Path, run_directory: str | Path) -> None:
        """Load the task and resolve all paths before any experiment executes."""

        self.task_path = Path(task_path).resolve()
        self.task = TaskSpec.from_json_file(self.task_path)
        self.task_root = self.task_path.parent.resolve()
        self.source_directory = resolve_inside(self.task_root, self.task.source.directory)
        if not self.source_directory.is_dir():
            raise WorkflowError(f"Source directory does not exist: {self.source_directory}")
        self.run_directory = Path(run_directory).resolve()
        if (
            self.run_directory == self.source_directory
            or self.source_directory in self.run_directory.parents
        ):
            raise WorkflowError("Run directory must not be inside the source directory")

    @property
    def state_path(self) -> Path:
        """Location of the small progress snapshot consumed by UIs and users."""

        return self.run_directory / "state.json"

    def _set_state(self, state: str, **details: object) -> None:
        """Persist the latest lifecycle state using an atomic JSON write."""

        _write_json(
            self.state_path,
            {
                "task_id": self.task.task_id,
                "state": state,
                "updated_at": _now(),
                **details,
            },
        )

    def prepare(self, *, backend: str) -> dict[str, object]:
        """Freeze the normalized task, plan, sources, paper, and provenance.

        Preparation happens before seed execution so acceptance criteria cannot
        be retrofitted after observing results.
        """

        self.run_directory.mkdir(parents=True, exist_ok=True)
        self._set_state("PREPARING", backend=backend)
        _write_json(self.run_directory / "task.normalized.json", self.task.to_dict())
        _write_json(self.run_directory / "claim.json", self.task.claim.to_dict())
        plan = {
            "task_id": self.task.task_id,
            "created_at": _now(),
            "backend": backend,
            "pre_registered": True,
            "seeds": list(self.task.seeds),
            "metric": self.task.metric_name,
            "expected_value": self.task.expected_value,
            "acceptance": self.task.acceptance.to_dict(),
            "stages": [
                "validate_task",
                "hash_sources",
                "execute_each_seed",
                "read_machine_metric",
                "aggregate",
                "verify_pre_registered_tolerance",
                "render_evidence_report",
            ],
        }
        _write_json(self.run_directory / "plan.json", plan)

        repository_manifest = self._verify_repository()
        manifest: dict[str, object] = {
            "task_file": self.task_path.relative_to(self.task_root).as_posix(),
            "task_sha256": sha256_file(self.task_path),
            "source_directory": self.source_directory.relative_to(self.task_root).as_posix(),
            "source_tree_sha256": sha256_tree(self.source_directory),
            "repository_url": self.task.paper.repository_url,
            "commit_sha": self.task.paper.commit_sha,
            **repository_manifest,
        }
        if self.task.paper.pdf_path:
            paper_path = resolve_inside(self.task_root, self.task.paper.pdf_path)
            manifest["paper_pdf"] = paper_path.relative_to(self.task_root).as_posix()
            manifest["paper_sha256"] = sha256_file(paper_path)
        _write_json(self.run_directory / "source_manifest.json", manifest)
        self._set_state("PREPARED", backend=backend)
        return plan

    def _verify_repository(self) -> dict[str, object]:
        """Verify registered Git origin and commit, then record local changes."""

        repository_url = self.task.paper.repository_url
        registered_commit = self.task.paper.commit_sha
        if repository_url is None or registered_commit is None:
            return {"repository_verified": False}

        inside_worktree = _git_output(
            self.source_directory,
            "rev-parse",
            "--is-inside-work-tree",
        )
        if inside_worktree != "true":
            raise WorkflowError("Registered source directory is not a Git worktree")
        actual_commit = _git_output(self.source_directory, "rev-parse", "HEAD")
        if actual_commit.casefold() != registered_commit.casefold():
            raise WorkflowError(
                "Registered commit does not match source checkout: "
                f"expected {registered_commit}, found {actual_commit}"
            )
        actual_origin = _git_output(
            self.source_directory,
            "config",
            "--get",
            "remote.origin.url",
        )
        if _normalize_repository_url(actual_origin) != _normalize_repository_url(
            repository_url
        ):
            raise WorkflowError(
                "Registered repository URL does not match source checkout: "
                f"expected {repository_url}, found {actual_origin}"
            )
        worktree_status = _git_output(
            self.source_directory,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        changes = worktree_status.splitlines() if worktree_status else []
        return {
            "repository_verified": True,
            "repository_head": actual_commit,
            "repository_origin": actual_origin,
            "worktree_dirty": bool(changes),
            "worktree_changes": changes,
        }

    def run(
        self,
        *,
        backend: str = "docker",
        allow_unsafe_local: bool = False,
    ) -> tuple[VerificationResult, list[AttemptRecord]]:
        """Prepare, execute every seed, verify the aggregate, and report it."""

        if backend not in {"docker", "local"}:
            raise WorkflowError("backend must be 'docker' or 'local'")
        backend_label = "docker" if backend == "docker" else "unsafe-local"
        self.prepare(backend=backend_label)
        runner = (
            DockerRunner()
            if backend == "docker"
            else LocalRunner(allow_unsafe_local=allow_unsafe_local)
        )
        limits = RunLimits(
            timeout_seconds=max(1, int(self.task.execution.timeout_seconds)),
            cpu_limit=self.task.execution.cpu_limit,
            memory_mb=self.task.execution.memory_mb,
            network=self.task.execution.network,
            build_network=self.task.execution.build_network,
        )

        # Phase 1: establish the evidence ledger before running untrusted code.
        attempts: list[AttemptRecord] = []
        observed_values: list[float] = []
        all_evidence: list[Path] = [
            self.run_directory / "task.normalized.json",
            self.run_directory / "claim.json",
            self.run_directory / "plan.json",
            self.run_directory / "source_manifest.json",
        ]
        self._set_state("RUNNING", backend=backend_label, completed_seeds=0)
        # Phase 2: each seed receives a separate output directory, execution
        # record, logs, metric artifact, and evidence hashes.
        for index, seed in enumerate(self.task.seeds, start=1):
            attempt_directory = self.run_directory / "attempts" / f"seed-{seed}"
            execution = runner.run(
                source_directory=self.source_directory,
                output_directory=attempt_directory,
                command=self.task.command,
                seed=seed,
                limits=limits,
            )
            execution_path = attempt_directory / "execution.json"
            write_execution_record(
                execution,
                execution_path,
                relative_to=self.run_directory,
            )
            metric_path = resolve_inside(attempt_directory, self.task.source.result_file)
            record = self._attempt_record(execution, metric_path, execution_path)
            attempts.append(record)
            if record.observed_value is not None:
                observed_values.append(record.observed_value)
            all_evidence.extend(
                path
                for path in (
                    Path(execution.stdout_path),
                    Path(execution.stderr_path),
                    execution_path,
                    metric_path,
                )
                if path.is_file()
            )
            self._set_state(
                "RUNNING",
                backend=backend_label,
                completed_seeds=index,
                total_seeds=len(self.task.seeds),
            )

        # Phase 3: aggregate only successfully parsed metrics, then render both
        # machine-readable and human-readable views of the same verdict.
        _write_json(self.run_directory / "attempts.json", [item.to_dict() for item in attempts])
        result = verify(
            self.task,
            observed_values,
            all_evidence,
            evidence_root=self.run_directory,
        )
        verdict_payload = {
            **result.to_dict(),
            "backend": backend_label,
            "independent_isolation": backend == "docker",
            "generated_at": _now(),
        }
        _write_json(self.run_directory / "verdict.json", verdict_payload)
        report_text = render_markdown(self.task, result, attempts, backend=backend_label)
        (self.run_directory / "report.md").write_text(report_text, encoding="utf-8")
        self._set_state(
            "REPORTED",
            backend=backend_label,
            verdict=result.status,
            independent_isolation=backend == "docker",
        )
        return result, attempts

    def _attempt_record(
        self,
        execution: ExecutionResult,
        metric_path: Path,
        execution_path: Path,
    ) -> AttemptRecord:
        """Convert backend output into one normalized, evidence-linked attempt."""

        evidence = [
            Path(execution.stdout_path),
            Path(execution.stderr_path),
            execution_path,
        ]
        # Process failures are distinct from scientific FAIL verdicts: no
        # metric means this seed contributes no observation to aggregation.
        if not execution.succeeded:
            status = "TIMED_OUT" if execution.timed_out else "FAILED"
            return AttemptRecord(
                attempt_id=f"seed-{execution.seed}",
                seed=execution.seed,
                status=status,
                command=execution.command,
                exit_code=execution.exit_code,
                duration_seconds=execution.duration_seconds,
                error=execution.error_message,
                evidence_hashes=evidence_hashes(
                    (path for path in evidence if path.is_file()),
                    relative_to=self.run_directory,
                ),
            )
        try:
            observed = read_metric(metric_path, self.task.source.metric_key)
        except MetricReadError as exc:
            return AttemptRecord(
                attempt_id=f"seed-{execution.seed}",
                seed=execution.seed,
                status="FAILED",
                command=execution.command,
                exit_code=execution.exit_code,
                duration_seconds=execution.duration_seconds,
                error=str(exc),
                evidence_hashes=evidence_hashes(
                    (path for path in evidence if path.is_file()),
                    relative_to=self.run_directory,
                ),
            )
        evidence.append(metric_path)
        return AttemptRecord(
            attempt_id=f"seed-{execution.seed}",
            seed=execution.seed,
            status="SUCCEEDED",
            observed_value=observed,
            command=execution.command,
            exit_code=execution.exit_code,
            duration_seconds=execution.duration_seconds,
            evidence_hashes=evidence_hashes(
                (path for path in evidence if path.is_file()),
                relative_to=self.run_directory,
            ),
        )
