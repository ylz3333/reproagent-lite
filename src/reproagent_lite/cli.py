"""Translate user-facing commands into the project's application workflows.

This module deliberately stays thin: argument parsing and terminal-friendly
errors live here, while validation, execution, and verdict logic remain in
their dedicated modules.  The separation keeps CLI changes from silently
changing scientific behavior.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .llm import enrich_claim_draft
from .models import ModelValidationError, TaskSpec
from .paper import extract_pdf_pages, find_claim_candidates, write_claim_draft
from .workflow import ReproductionWorkflow, WorkflowError


def _project_root() -> Path:
    """Return the source checkout root used to locate bundled examples."""

    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    """Build the complete command tree without performing any work."""

    parser = argparse.ArgumentParser(
        prog="reproagent",
        description="Run evidence-first scientific experiment reproductions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate and normalize a task JSON file")
    validate.add_argument("task", type=Path)

    run = subparsers.add_parser("run", help="Execute, verify, and report one task")
    run.add_argument("task", type=Path)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--backend", choices=("docker", "local"), default="docker")
    run.add_argument(
        "--allow-unsafe-local",
        action="store_true",
        help="Acknowledge that local execution is only for trusted fixtures",
    )

    demo = subparsers.add_parser("demo", help="Run the bundled trusted offline fixture")
    demo.add_argument("--run-dir", type=Path, default=Path("runs/demo"))
    demo.add_argument("--backend", choices=("local", "docker"), default="local")

    extract = subparsers.add_parser("extract", help="Find claim candidates in a paper PDF")
    extract.add_argument("--pdf", type=Path, required=True)
    extract.add_argument("--target", required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--llm", action="store_true", help="Use optional OpenAI assistance")
    extract.add_argument("--model", help="OpenAI model; otherwise OPENAI_MODEL is used")

    subparsers.add_parser("doctor", help="Check local runtime capabilities")
    return parser


def _cmd_validate(task_path: Path) -> int:
    """Validate a task and print its canonical JSON representation."""

    task = TaskSpec.from_json_file(task_path)
    print(json.dumps(task.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Execute a user-supplied task and return a verdict-aware exit code."""

    workflow = ReproductionWorkflow(args.task, args.run_dir)
    result, _ = workflow.run(
        backend=args.backend,
        allow_unsafe_local=args.allow_unsafe_local,
    )
    print(f"Verdict: {result.status}")
    print(f"Report: {workflow.run_directory / 'report.md'}")
    return 0 if result.status == "PASS" else 2


def _cmd_demo(args: argparse.Namespace) -> int:
    """Run the dependency-free fixture used for installation smoke tests."""

    task_path = _project_root() / "examples" / "linear-regression" / "task.json"
    workflow = ReproductionWorkflow(task_path, args.run_dir)
    result, _ = workflow.run(
        backend=args.backend,
        allow_unsafe_local=args.backend == "local",
    )
    print(f"Demo verdict: {result.status}")
    print(f"Report: {workflow.run_directory / 'report.md'}")
    return 0 if result.status == "PASS" else 2


def _cmd_extract(args: argparse.Namespace) -> int:
    """Extract an auditable claim draft, optionally enriched by an LLM."""

    pages = extract_pdf_pages(args.pdf)
    draft = find_claim_candidates(pages, args.target)
    if args.llm:
        payload = enrich_claim_draft(pages, args.target, model=args.model)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        write_claim_draft(draft, args.output)
    print(f"Claim draft: {args.output.resolve()}")
    return 0


def _cmd_doctor() -> int:
    """Report required and optional local runtime capabilities."""

    print(f"Python: {sys.version.split()[0]}")
    docker = shutil.which("docker")
    if docker is None:
        print("Docker: not found")
    else:
        try:
            status = subprocess.run(
                [docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            print(f"Docker: installed ({docker}); daemon unavailable")
        else:
            version = status.stdout.strip()
            if status.returncode == 0 and version:
                print(f"Docker: available (server {version})")
            else:
                print(f"Docker: installed ({docker}); daemon unavailable")
    try:
        import pymupdf  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        print("PyMuPDF: not installed (optional)")
    else:
        print("PyMuPDF: available")
    try:
        import openai  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        print("OpenAI SDK: not installed (optional)")
    else:
        print("OpenAI SDK: available")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch one CLI command.

    Exit codes form part of the automation contract: ``0`` means success (and
    PASS for a reproduction), ``1`` means configuration/runtime failure, and
    ``2`` means the run completed but did not produce a PASS verdict.
    """

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return _cmd_validate(args.task)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "demo":
            return _cmd_demo(args)
        if args.command == "extract":
            return _cmd_extract(args)
        if args.command == "doctor":
            return _cmd_doctor()
    # Convert expected boundary errors into concise messages. Unexpected bugs
    # remain uncaught so reviewers receive a full traceback instead of a false
    # impression that the failure was an input problem.
    except (ModelValidationError, WorkflowError, ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Unhandled command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
