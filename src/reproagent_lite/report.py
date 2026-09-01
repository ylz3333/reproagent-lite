"""Render completed results without changing their scientific meaning.

All verdict calculations happen in :mod:`reproagent_lite.verifier`.  Keeping
this module presentation-only makes the Markdown report easy to redesign
without affecting PASS, FAIL, or INCONCLUSIVE decisions.
"""

from __future__ import annotations

from typing import Iterable

from .models import AttemptRecord, TaskSpec, VerificationResult


def _format_number(value: float | None) -> str:
    """Format a metric compactly while preserving useful precision."""

    if value is None:
        return "—"
    return f"{value:.10g}"


def render_markdown(
    task: TaskSpec,
    result: VerificationResult,
    attempts: Iterable[AttemptRecord],
    *,
    backend: str,
) -> str:
    """Render one task, verdict, and attempt list as reviewable Markdown."""

    # Attempt rows are derived from structured records; the report is a view,
    # not the source of truth. Machine consumers should read verdict.json.
    rows = []
    for attempt in attempts:
        rows.append(
            "| {seed} | {status} | {value} | {duration} | {error} |".format(
                seed=attempt.seed,
                status=attempt.status,
                value=_format_number(attempt.observed_value),
                duration=(
                    "—"
                    if attempt.duration_seconds is None
                    else f"{attempt.duration_seconds:.3f}s"
                ),
                error=(attempt.error or "—").replace("|", "\\|"),
            )
        )
    evidence_lines = [
        f"- `{path}`: `{digest}`" for path, digest in sorted(result.evidence_hashes.items())
    ] or ["- No evidence artifacts were available."]
    warning = ""
    # A local run can validate plumbing but cannot claim process isolation.
    if backend == "unsafe-local":
        warning = (
            "\n> **Safety note:** This was a trusted local demo, not an isolated reproduction. "
            "Use the Docker backend before treating the verdict as independent evidence.\n"
        )
    return "\n".join(
        [
            f"# Reproduction report: {task.title}",
            "",
            f"- Task ID: `{task.task_id}`",
            f"- Backend: `{backend}`",
            f"- Verdict: **{result.status}**",
            f"- Metric: `{result.metric_name}`",
            f"- Reported value: `{_format_number(result.expected_value)}`",
            f"- Reproduced aggregate: `{_format_number(result.aggregate_value)}`",
            f"- Aggregation: `{result.aggregation}`",
            f"- Absolute error: `{_format_number(result.absolute_error)}`",
            f"- Reason: {result.reason}",
            warning.rstrip(),
            "",
            "## Attempts",
            "",
            "| Seed | Status | Observed value | Duration | Error |",
            "|---:|---|---:|---:|---|",
            *rows,
            "",
            "## Evidence hashes",
            "",
            *evidence_lines,
            "",
            "## Interpretation",
            "",
            (
                "A PASS means the aggregate result met the tolerance registered before execution. "
                "It does not by itself prove the paper's broader scientific claims."
            ),
            "",
        ]
    )
