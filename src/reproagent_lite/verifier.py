"""Deterministic metric extraction and claim verification."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .hashing import evidence_hashes
from .models import TaskSpec, VerificationResult


class MetricReadError(ValueError):
    """Raised when an experiment artifact cannot provide a finite metric."""


def read_metric(path: str | Path, key: str) -> float:
    """Read a finite numeric value from a dot-delimited JSON key path."""

    metric_path = Path(path)
    if not metric_path.is_file():
        raise MetricReadError(f"Metric artifact does not exist: {metric_path}")
    try:
        payload = json.loads(metric_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricReadError(f"Metric artifact is not valid UTF-8 JSON: {metric_path}") from exc
    value: object = payload
    for component in key.split("."):
        if not isinstance(value, Mapping) or component not in value:
            raise MetricReadError(f"Metric key {key!r} was not found in {metric_path}")
        value = value[component]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricReadError(f"Metric {key!r} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise MetricReadError(f"Metric {key!r} must be finite")
    return numeric


def _aggregate(values: Sequence[float], mode: str) -> float:
    """Apply the aggregation method registered in the task before execution."""

    if mode == "mean":
        return statistics.fmean(values)
    if mode == "median":
        return float(statistics.median(values))
    if mode == "min":
        return min(values)
    if mode == "max":
        return max(values)
    raise ValueError(f"Unsupported aggregation: {mode}")


def verify(
    task: TaskSpec,
    observed_values: Iterable[float],
    evidence_paths: Iterable[str | Path] | None = None,
    *,
    evidence_root: str | Path | None = None,
) -> VerificationResult:
    """Compare observed metrics with the task's pre-registered acceptance rule.

    The verifier is deterministic and model-free.  It returns INCONCLUSIVE
    when too few seeds produced valid metrics, rather than treating missing
    evidence as either a scientific success or failure.
    """

    values = tuple(float(value) for value in observed_values)
    required = task.acceptance.min_successful_seeds
    hashes = evidence_hashes(evidence_paths or (), relative_to=evidence_root)
    # Evidence sufficiency is evaluated before any tolerance calculation.
    if len(values) < required:
        return VerificationResult(
            status="INCONCLUSIVE",
            metric_name=task.metric_name,
            expected_value=task.expected_value,
            aggregate_value=None,
            aggregation=task.acceptance.aggregation,
            observed_values=values,
            successful_seeds=len(values),
            required_seeds=required,
            absolute_error=None,
            relative_error=None,
            absolute_tolerance=task.acceptance.absolute_tolerance,
            relative_tolerance=task.acceptance.effective_relative_tolerance,
            evidence_hashes=hashes,
            reason=(
                f"Only {len(values)} successful seed(s); {required} required for a verdict."
            ),
        )

    aggregate = _aggregate(values, task.acceptance.aggregation)
    absolute_error = abs(aggregate - task.expected_value)
    # Relative error is undefined around a zero baseline. Represent that case
    # explicitly while the registered absolute tolerance remains usable.
    if task.expected_value == 0:
        relative_error = 0.0 if absolute_error == 0 else math.inf
    else:
        relative_error = absolute_error / abs(task.expected_value)
    passed = task.acceptance.check(aggregate)
    return VerificationResult(
        status="PASS" if passed else "FAIL",
        metric_name=task.metric_name,
        expected_value=task.expected_value,
        aggregate_value=aggregate,
        aggregation=task.acceptance.aggregation,
        observed_values=values,
        successful_seeds=len(values),
        required_seeds=required,
        absolute_error=absolute_error,
        relative_error=relative_error,
        absolute_tolerance=task.acceptance.absolute_tolerance,
        relative_tolerance=task.acceptance.effective_relative_tolerance,
        evidence_hashes=hashes,
        reason=(
            "Aggregate metric is within the pre-registered tolerance."
            if passed
            else "Aggregate metric is outside the pre-registered tolerance."
        ),
    )
