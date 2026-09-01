"""Execution backends for trusted demos and isolated Docker reproductions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .hashing import sha256_tree
from .security import SecurityError, minimal_environment, resolve_inside, validate_command


@dataclass(frozen=True)
class RunLimits:
    """Resource and network limits applied to one experiment execution."""

    timeout_seconds: int = 300
    cpu_limit: float = 2.0
    memory_mb: int = 2048
    pids_limit: int = 256
    network: bool = False
    build_network: bool = False

    def __post_init__(self) -> None:
        """Reject unsafe or nonsensical limits before invoking a backend."""

        if not 1 <= self.timeout_seconds <= 86_400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        if not 0.1 <= self.cpu_limit <= 64:
            raise ValueError("cpu_limit must be between 0.1 and 64")
        if not 128 <= self.memory_mb <= 262_144:
            raise ValueError("memory_mb must be between 128 and 262144")
        if not 16 <= self.pids_limit <= 4096:
            raise ValueError("pids_limit must be between 16 and 4096")


@dataclass(frozen=True)
class ExecutionResult:
    """Backend-neutral process outcome plus paths to its raw evidence."""

    seed: int
    backend: str
    command: tuple[str, ...]
    exit_code: int | None
    duration_seconds: float
    timed_out: bool
    stdout_path: str
    stderr_path: str
    output_directory: str
    error_class: str | None = None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether the process completed cleanly before its deadline."""

        return self.exit_code == 0 and not self.timed_out and self.error_class is None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable execution record."""

        return asdict(self)


class ExperimentRunner(Protocol):
    """Interface shared by local and Docker execution backends."""

    def run(
        self,
        *,
        source_directory: Path,
        output_directory: Path,
        command: tuple[str, ...],
        seed: int,
        limits: RunLimits,
    ) -> ExecutionResult:
        """Execute one registered seed and return normalized process evidence."""

        ...


def _write_logs(output_directory: Path, stdout: str, stderr: str) -> tuple[Path, Path]:
    """Persist both process streams even when either stream is empty."""

    output_directory.mkdir(parents=True, exist_ok=True)
    stdout_path = output_directory / "stdout.log"
    stderr_path = output_directory / "stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return stdout_path, stderr_path


def _materialize_command(command: tuple[str, ...], *, container: bool) -> tuple[str, ...]:
    """Resolve the registered ``{python}`` placeholder for one backend."""

    python_value = "python" if container else sys.executable
    return tuple(python_value if part == "{python}" else part for part in command)


def _timeout_stream(value: str | bytes | None) -> str:
    """Normalize partial output attached to ``TimeoutExpired`` exceptions."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _container_user() -> str:
    """Use the host user on POSIX so the bind-mounted output remains writable."""

    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if callable(getuid) and callable(getgid):
        return f"{getuid()}:{getgid()}"
    return "65534:65534"


class LocalRunner:
    """Run trusted fixtures locally. This backend is intentionally opt-in."""

    name = "unsafe-local"

    def __init__(self, *, allow_unsafe_local: bool = False) -> None:
        """Require explicit acknowledgement because this backend has no sandbox."""

        if not allow_unsafe_local:
            raise SecurityError(
                "Local execution is not isolated. Pass allow_unsafe_local=True only "
                "for trusted fixtures."
            )

    def run(
        self,
        *,
        source_directory: Path,
        output_directory: Path,
        command: tuple[str, ...],
        seed: int,
        limits: RunLimits,
    ) -> ExecutionResult:
        """Run a trusted fixture as a direct child process with a minimal env."""

        source_directory = source_directory.resolve()
        if not source_directory.is_dir():
            raise FileNotFoundError(f"Source directory does not exist: {source_directory}")
        output_directory = output_directory.resolve()
        output_directory.mkdir(parents=True, exist_ok=True)
        registered_command = validate_command(command)
        resolved_command = _materialize_command(registered_command, container=False)
        # Only registered reproduction variables are added. Parent credentials
        # and proxy settings are deliberately removed by minimal_environment.
        environment = minimal_environment(
            {
                "REPRO_SEED": str(seed),
                "REPRO_OUTPUT_DIR": str(output_directory),
            }
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                resolved_command,
                cwd=source_directory,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limits.timeout_seconds,
                check=False,
                shell=False,
            )
            duration = time.monotonic() - started
            stdout_path, stderr_path = _write_logs(
                output_directory, completed.stdout, completed.stderr
            )
            error_class = None if completed.returncode == 0 else "PROCESS_EXIT"
            error_message = (
                None
                if completed.returncode == 0
                else f"Exit code {completed.returncode}"
            )
            return ExecutionResult(
                seed=seed,
                backend=self.name,
                command=registered_command,
                exit_code=completed.returncode,
                duration_seconds=duration,
                timed_out=False,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                output_directory=str(output_directory),
                error_class=error_class,
                error_message=error_message,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            stdout = _timeout_stream(exc.stdout)
            stderr = _timeout_stream(exc.stderr)
            stdout_path, stderr_path = _write_logs(output_directory, stdout, stderr)
            return ExecutionResult(
                seed=seed,
                backend=self.name,
                command=registered_command,
                exit_code=None,
                duration_seconds=duration,
                timed_out=True,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                output_directory=str(output_directory),
                error_class="TIMEOUT",
                error_message=f"Exceeded {limits.timeout_seconds} seconds",
            )


class DockerRunner:
    """Run an experiment in a locked-down, disposable Docker container."""

    name = "docker"

    def __init__(self, *, docker_executable: str = "docker") -> None:
        """Resolve Docker once and initialize the per-workflow image cache."""

        resolved = shutil.which(docker_executable)
        if resolved is None:
            raise RuntimeError("Docker is not installed or is not available on PATH")
        self.docker_executable = resolved
        self._built_images: set[str] = set()

    def run(
        self,
        *,
        source_directory: Path,
        output_directory: Path,
        command: tuple[str, ...],
        seed: int,
        limits: RunLimits,
    ) -> ExecutionResult:
        """Build the source image once, then run one locked-down seed container."""

        source_directory = source_directory.resolve()
        if not source_directory.is_dir():
            raise FileNotFoundError(f"Source directory does not exist: {source_directory}")
        output_directory = output_directory.resolve()
        output_directory.mkdir(parents=True, exist_ok=True)
        dockerfile = resolve_inside(source_directory, "Dockerfile")
        if not dockerfile.is_file():
            raise FileNotFoundError(
                f"Docker backend requires a Dockerfile in {source_directory}"
            )
        # The source-tree digest makes the image tag content-addressed. Reusing
        # it across seeds avoids rebuilding an identical legacy environment.
        build_network_args = ["--network", "none"] if not limits.build_network else []
        image_tag = f"reproagent-lite-{sha256_tree(source_directory)[:16]}"
        if image_tag not in self._built_images:
            build_started = time.monotonic()
            try:
                build = subprocess.run(
                    [
                        self.docker_executable,
                        "build",
                        "--pull=false",
                        *build_network_args,
                        "--tag",
                        image_tag,
                        str(source_directory),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=max(limits.timeout_seconds, 600),
                    check=False,
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                stdout_path, stderr_path = _write_logs(
                    output_directory,
                    _timeout_stream(exc.stdout),
                    _timeout_stream(exc.stderr),
                )
                return ExecutionResult(
                    seed=seed,
                    backend=self.name,
                    command=tuple(command),
                    exit_code=None,
                    duration_seconds=time.monotonic() - build_started,
                    timed_out=True,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    output_directory=str(output_directory),
                    error_class="IMAGE_BUILD_TIMEOUT",
                    error_message="Docker image build timed out",
                )
            if build.returncode != 0:
                stdout_path, stderr_path = _write_logs(
                    output_directory, build.stdout, build.stderr
                )
                return ExecutionResult(
                    seed=seed,
                    backend=self.name,
                    command=tuple(command),
                    exit_code=build.returncode,
                    duration_seconds=time.monotonic() - build_started,
                    timed_out=False,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    output_directory=str(output_directory),
                    error_class="IMAGE_BUILD",
                    error_message="Docker image build failed",
                )
            self._built_images.add(image_tag)

        registered_command = validate_command(command)
        resolved_command = _materialize_command(registered_command, container=True)
        container_name = f"{image_tag}-s{seed}-{uuid.uuid4().hex[:8]}"
        runtime_network_args = ["--network", "none"] if not limits.network else []
        # Defense in depth: immutable source, writable output only, no added
        # privileges/capabilities, bounded resources, and network off by default.
        run_command = [
            self.docker_executable,
            "run",
            "--rm",
            "--name",
            container_name,
            "--init",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(limits.pids_limit),
            "--memory",
            f"{limits.memory_mb}m",
            "--cpus",
            str(limits.cpu_limit),
            "--user",
            _container_user(),
            "--ipc",
            "none",
            "--ulimit",
            "nofile=1024:1024",
            "--stop-timeout",
            "1",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=512m",
            "--mount",
            f"type=bind,src={source_directory},dst=/workspace,readonly",
            "--mount",
            f"type=bind,src={output_directory},dst=/output",
            "--workdir",
            "/workspace",
            "--env",
            f"REPRO_SEED={seed}",
            "--env",
            "REPRO_OUTPUT_DIR=/output",
            *runtime_network_args,
            image_tag,
            *resolved_command,
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                run_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limits.timeout_seconds,
                check=False,
                shell=False,
            )
            duration = time.monotonic() - started
            stdout_path, stderr_path = _write_logs(
                output_directory, completed.stdout, completed.stderr
            )
            error_class = None if completed.returncode == 0 else "PROCESS_EXIT"
            return ExecutionResult(
                seed=seed,
                backend=self.name,
                command=registered_command,
                exit_code=completed.returncode,
                duration_seconds=duration,
                timed_out=False,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                output_directory=str(output_directory),
                error_class=error_class,
                error_message=(
                    None if completed.returncode == 0 else f"Exit code {completed.returncode}"
                ),
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            # A timed-out container may outlive the client process; remove it
            # explicitly so later seeds cannot inherit stale state/resources.
            cleanup = subprocess.run(
                [self.docker_executable, "rm", "--force", container_name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                shell=False,
            )
            stdout = _timeout_stream(exc.stdout)
            stderr = _timeout_stream(exc.stderr)
            if cleanup.returncode != 0 and cleanup.stderr.strip():
                stderr += f"\nContainer cleanup warning: {cleanup.stderr.strip()}\n"
            stdout_path, stderr_path = _write_logs(output_directory, stdout, stderr)
            return ExecutionResult(
                seed=seed,
                backend=self.name,
                command=registered_command,
                exit_code=None,
                duration_seconds=duration,
                timed_out=True,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                output_directory=str(output_directory),
                error_class="TIMEOUT",
                error_message=f"Exceeded {limits.timeout_seconds} seconds",
            )


def write_execution_record(
    result: ExecutionResult,
    path: Path,
    *,
    relative_to: Path | None = None,
) -> None:
    """Write a portable JSON record for a completed backend invocation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    # Prefer run-relative evidence paths so reports can move between machines.
    if relative_to is not None:
        root = relative_to.resolve()
        for key in ("stdout_path", "stderr_path", "output_directory"):
            try:
                payload[key] = Path(str(payload[key])).resolve().relative_to(root).as_posix()
            except ValueError:
                pass
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
