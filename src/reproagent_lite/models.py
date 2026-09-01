"""Strict, dependency-free domain models for ReproAgent-Lite.

The JSON boundary is deliberately narrower than the Python API.  Every object
rejects unknown keys and values are validated without implicit string/boolean
coercion.  This keeps a reproduction task auditable and makes schema drift
fail loudly instead of silently changing an experiment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


__version__ = "0.1.0"
SCHEMA_VERSION = "1.0"


class ModelValidationError(ValueError):
    """Raised when a task document does not conform to the task schema."""


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    """Require a JSON object with string keys at a named schema location."""

    if not isinstance(value, Mapping):
        raise ModelValidationError(f"{context} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ModelValidationError(f"{context} keys must be strings")
    return value


def _keys(
    value: Mapping[str, Any],
    *,
    context: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    """Enforce required fields and reject silent schema expansion."""

    optional = optional or set()
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise ModelValidationError(f"{context} is missing required field(s): {', '.join(missing)}")
    if unknown:
        raise ModelValidationError(f"{context} has unknown field(s): {', '.join(unknown)}")


def _string(value: Any, context: str, *, allow_empty: bool = False) -> str:
    """Validate a JSON string without coercing other primitive types."""

    if not isinstance(value, str):
        raise ModelValidationError(f"{context} must be a string")
    if "\x00" in value:
        raise ModelValidationError(f"{context} must not contain a NUL character")
    if not allow_empty and not value.strip():
        raise ModelValidationError(f"{context} must not be empty")
    return value


def _optional_string(value: Any, context: str) -> str | None:
    """Validate a nullable string field."""

    if value is None:
        return None
    return _string(value, context)


def _number(value: Any, context: str, *, minimum: float | None = None) -> float:
    """Validate a finite JSON number; booleans are intentionally rejected."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelValidationError(f"{context} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ModelValidationError(f"{context} must be finite")
    if minimum is not None and result < minimum:
        raise ModelValidationError(f"{context} must be at least {minimum:g}")
    return result


def _integer(value: Any, context: str, *, minimum: int | None = None) -> int:
    """Validate an exact integer with an optional inclusive lower bound."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelValidationError(f"{context} must be an integer")
    if minimum is not None and value < minimum:
        raise ModelValidationError(f"{context} must be at least {minimum}")
    return value


def _boolean(value: Any, context: str) -> bool:
    """Validate an exact JSON boolean rather than a truthy substitute."""

    if not isinstance(value, bool):
        raise ModelValidationError(f"{context} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceSpec:
    """A page-level trace for one extracted claim field."""

    field: str
    quote: str
    page: int | None = None
    table: str | None = None
    cell: str | None = None
    confidence: float | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EvidenceSpec":
        """Validate and construct one evidence record from parsed JSON."""

        data = _mapping(raw, "paper.evidence[]")
        _keys(
            data,
            context="paper.evidence[]",
            required={"field", "quote"},
            optional={"page", "table", "cell", "confidence"},
        )
        page_raw = data.get("page")
        confidence_raw = data.get("confidence")
        confidence = (
            None
            if confidence_raw is None
            else _number(confidence_raw, "paper.evidence[].confidence", minimum=0.0)
        )
        if confidence is not None and confidence > 1.0:
            raise ModelValidationError("paper.evidence[].confidence must be at most 1")
        return cls(
            field=_string(data["field"], "paper.evidence[].field"),
            quote=_string(data["quote"], "paper.evidence[].quote"),
            page=(
                None
                if page_raw is None
                else _integer(page_raw, "paper.evidence[].page", minimum=1)
            ),
            table=_optional_string(data.get("table"), "paper.evidence[].table"),
            cell=_optional_string(data.get("cell"), "paper.evidence[].cell"),
            confidence=confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize only fields that are present in this evidence record."""

        result: dict[str, Any] = {"field": self.field, "quote": self.quote}
        if self.page is not None:
            result["page"] = self.page
        if self.table is not None:
            result["table"] = self.table
        if self.cell is not None:
            result["cell"] = self.cell
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result


@dataclass(frozen=True, slots=True)
class PaperSpec:
    """Paper artifact, source-repository provenance, and supporting quotes."""

    pdf_path: str | None
    repository_url: str | None
    commit_sha: str | None
    evidence: tuple[EvidenceSpec, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PaperSpec":
        """Validate paper artifacts and paired repository provenance fields."""

        data = _mapping(raw, "paper")
        _keys(
            data,
            context="paper",
            required={"pdf_path"},
            optional={"repository_url", "commit_sha", "evidence"},
        )
        evidence_raw = data.get("evidence", [])
        if not isinstance(evidence_raw, list):
            raise ModelValidationError("paper.evidence must be an array")
        repository_url = _optional_string(data.get("repository_url"), "paper.repository_url")
        commit_sha = _optional_string(data.get("commit_sha"), "paper.commit_sha")
        if (repository_url is None) != (commit_sha is None):
            raise ModelValidationError(
                "paper.repository_url and paper.commit_sha must either both be set or both be null"
            )
        return cls(
            pdf_path=_optional_string(data["pdf_path"], "paper.pdf_path"),
            repository_url=repository_url,
            commit_sha=commit_sha,
            evidence=tuple(EvidenceSpec.from_dict(item) for item in evidence_raw),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible paper section."""

        return {
            "pdf_path": self.pdf_path,
            "repository_url": self.repository_url,
            "commit_sha": self.commit_sha,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Registered experiment location, command, and metric artifact contract."""

    directory: str
    command: tuple[str, ...]
    result_file: str
    metric_key: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SourceSpec":
        """Validate an argv-form experiment and its metric output contract."""

        data = _mapping(raw, "source")
        _keys(
            data,
            context="source",
            required={"directory", "command", "result_file", "metric_key"},
        )
        command_raw = data["command"]
        if not isinstance(command_raw, list) or not command_raw:
            raise ModelValidationError("source.command must be a non-empty array")
        command = tuple(
            _string(item, f"source.command[{index}]", allow_empty=True)
            for index, item in enumerate(command_raw)
        )
        return cls(
            directory=_string(data["directory"], "source.directory"),
            command=command,
            result_file=_string(data["result_file"], "source.result_file"),
            metric_key=_string(data["metric_key"], "source.metric_key"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible source section."""

        return {
            "directory": self.directory,
            "command": list(self.command),
            "result_file": self.result_file,
            "metric_key": self.metric_key,
        }


@dataclass(frozen=True, slots=True)
class AcceptanceSpec:
    """A claim-bound tolerance rule.

    ``both`` follows the conventional ``isclose`` interpretation: a value is
    accepted when it satisfies either the absolute or relative tolerance.  The
    tolerances are fixed before execution and the expected value is copied from
    ``claim.reported_value`` when a task is parsed.
    """

    expected: float
    mode: str
    tolerance: float
    relative_tolerance: float | None = None
    min_successful_seeds: int = 1
    aggregation: str = "mean"

    MODES = frozenset({"absolute", "relative", "both"})
    AGGREGATIONS = frozenset({"mean", "median", "min", "max"})

    def __post_init__(self) -> None:
        """Normalize numeric inputs and enforce mode-specific invariants."""

        expected = _number(self.expected, "acceptance.expected")
        tolerance = _number(self.tolerance, "acceptance.tolerance", minimum=0.0)
        if self.mode not in self.MODES:
            allowed = ", ".join(sorted(self.MODES))
            raise ModelValidationError(f"acceptance.mode must be one of: {allowed}")
        relative_tolerance = self.relative_tolerance
        if relative_tolerance is not None:
            relative_tolerance = _number(
                relative_tolerance,
                "acceptance.relative_tolerance",
                minimum=0.0,
            )
        if self.mode == "absolute" and relative_tolerance is not None:
            raise ModelValidationError(
                "acceptance.relative_tolerance is not allowed in absolute mode"
            )
        if self.mode == "both" and relative_tolerance is None:
            raise ModelValidationError(
                "acceptance.relative_tolerance is required in both mode"
            )
        min_seeds = _integer(
            self.min_successful_seeds,
            "acceptance.min_successful_seeds",
            minimum=1,
        )
        if self.aggregation not in self.AGGREGATIONS:
            allowed = ", ".join(sorted(self.AGGREGATIONS))
            raise ModelValidationError(f"acceptance.aggregation must be one of: {allowed}")
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "tolerance", tolerance)
        object.__setattr__(self, "relative_tolerance", relative_tolerance)
        object.__setattr__(self, "min_successful_seeds", min_seeds)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, expected: float) -> "AcceptanceSpec":
        """Bind a parsed tolerance rule to the already validated claim value."""

        data = _mapping(raw, "claim.acceptance")
        _keys(
            data,
            context="claim.acceptance",
            required={"mode", "tolerance"},
            optional={"relative_tolerance", "min_successful_seeds", "aggregation"},
        )
        mode = _string(data["mode"], "claim.acceptance.mode")
        relative_raw = data.get("relative_tolerance")
        return cls(
            expected=expected,
            mode=mode,
            tolerance=_number(data["tolerance"], "claim.acceptance.tolerance", minimum=0.0),
            relative_tolerance=(
                None
                if relative_raw is None
                else _number(
                    relative_raw,
                    "claim.acceptance.relative_tolerance",
                    minimum=0.0,
                )
            ),
            min_successful_seeds=_integer(
                data.get("min_successful_seeds", 1),
                "claim.acceptance.min_successful_seeds",
                minimum=1,
            ),
            aggregation=_string(
                data.get("aggregation", "mean"),
                "claim.acceptance.aggregation",
            ),
        )

    @property
    def absolute_tolerance(self) -> float | None:
        """Return the active absolute tolerance, if the mode defines one."""

        return self.tolerance if self.mode in {"absolute", "both"} else None

    @property
    def effective_relative_tolerance(self) -> float | None:
        """Return the active relative tolerance after normalizing schema modes."""

        if self.mode == "relative":
            return (
                self.relative_tolerance
                if self.relative_tolerance is not None
                else self.tolerance
            )
        if self.mode == "both":
            return self.relative_tolerance
        return None

    def check(self, value: float) -> bool:
        """Return whether *value* falls within the pre-registered tolerance."""

        observed = _number(value, "observed value")
        difference = abs(observed - self.expected)
        absolute_ok = (
            self.absolute_tolerance is not None and difference <= self.absolute_tolerance
        )
        relative = self.effective_relative_tolerance
        relative_ok = relative is not None and difference <= relative * abs(self.expected)
        if self.mode == "absolute":
            return absolute_ok
        if self.mode == "relative":
            return relative_ok
        return absolute_ok or relative_ok

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical acceptance rule without derived properties."""

        result: dict[str, Any] = {
            "mode": self.mode,
            "tolerance": self.tolerance,
            "min_successful_seeds": self.min_successful_seeds,
            "aggregation": self.aggregation,
        }
        if self.relative_tolerance is not None:
            result["relative_tolerance"] = self.relative_tolerance
        return result


@dataclass(frozen=True, slots=True)
class ClaimSpec:
    """One paper-reported metric bound to its acceptance rule."""

    metric: str
    reported_value: float
    unit: str | None
    acceptance: AcceptanceSpec

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ClaimSpec":
        """Validate a paper claim and bind its acceptance baseline."""

        data = _mapping(raw, "claim")
        _keys(
            data,
            context="claim",
            required={"metric", "reported_value", "acceptance"},
            optional={"unit"},
        )
        reported_value = _number(data["reported_value"], "claim.reported_value")
        return cls(
            metric=_string(data["metric"], "claim.metric"),
            reported_value=reported_value,
            unit=_optional_string(data.get("unit"), "claim.unit"),
            acceptance=AcceptanceSpec.from_dict(data["acceptance"], expected=reported_value),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible claim section."""

        return {
            "metric": self.metric,
            "reported_value": self.reported_value,
            "unit": self.unit,
            "acceptance": self.acceptance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    """Registered seed set and sandbox resource/network policy."""

    seeds: tuple[int, ...]
    timeout_seconds: float
    cpu_limit: float
    memory_mb: int
    network: bool
    build_network: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ExecutionSpec":
        """Validate unique seeds and explicit resource/network policy."""

        data = _mapping(raw, "execution")
        _keys(
            data,
            context="execution",
            required={"seeds", "timeout_seconds", "cpu_limit", "memory_mb", "network"},
            optional={"build_network"},
        )
        seeds_raw = data["seeds"]
        if not isinstance(seeds_raw, list) or not seeds_raw:
            raise ModelValidationError("execution.seeds must be a non-empty array")
        seeds = tuple(
            _integer(seed, f"execution.seeds[{index}]")
            for index, seed in enumerate(seeds_raw)
        )
        if len(set(seeds)) != len(seeds):
            raise ModelValidationError("execution.seeds must not contain duplicates")
        return cls(
            seeds=seeds,
            timeout_seconds=_number(
                data["timeout_seconds"],
                "execution.timeout_seconds",
                minimum=0.000001,
            ),
            cpu_limit=_number(data["cpu_limit"], "execution.cpu_limit", minimum=0.000001),
            memory_mb=_integer(data["memory_mb"], "execution.memory_mb", minimum=1),
            network=_boolean(data["network"], "execution.network"),
            build_network=_boolean(
                data.get("build_network", False),
                "execution.build_network",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible execution section."""

        return {
            "seeds": list(self.seeds),
            "timeout_seconds": self.timeout_seconds,
            "cpu_limit": self.cpu_limit,
            "memory_mb": self.memory_mb,
            "network": self.network,
            "build_network": self.build_network,
        }


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Complete immutable reproduction contract loaded from task JSON."""

    schema_version: str
    task_id: str
    title: str
    description: str
    paper: PaperSpec
    source: SourceSpec
    claim: ClaimSpec
    execution: ExecutionSpec

    def __post_init__(self) -> None:
        """Validate invariants that span otherwise independent task sections."""

        if self.schema_version != SCHEMA_VERSION:
            raise ModelValidationError(
                f"unsupported schema_version {self.schema_version!r}; expected {SCHEMA_VERSION!r}"
            )
        if self.claim.acceptance.min_successful_seeds > len(self.execution.seeds):
            raise ModelValidationError(
                "claim.acceptance.min_successful_seeds cannot exceed the number of execution.seeds"
            )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TaskSpec":
        """Construct the complete task after validating every nested section."""

        data = _mapping(raw, "task")
        _keys(
            data,
            context="task",
            required={
                "schema_version",
                "task_id",
                "title",
                "paper",
                "source",
                "claim",
                "execution",
            },
            optional={"description"},
        )
        return cls(
            schema_version=_string(data["schema_version"], "schema_version"),
            task_id=_string(data["task_id"], "task_id"),
            title=_string(data["title"], "title"),
            description=_string(data.get("description", ""), "description", allow_empty=True),
            paper=PaperSpec.from_dict(data["paper"]),
            source=SourceSpec.from_dict(data["source"]),
            claim=ClaimSpec.from_dict(data["claim"]),
            execution=ExecutionSpec.from_dict(data["execution"]),
        )

    @classmethod
    def from_json(cls, text: str) -> "TaskSpec":
        """Parse strict JSON, rejecting duplicate keys and non-finite numbers."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")

        def reject_constant(token: str) -> None:
            """Reject NaN/Infinity spellings accepted by Python's JSON parser."""

            raise ModelValidationError(f"non-standard JSON number {token!r} is not allowed")

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            """Reject ambiguous objects instead of silently keeping a last value."""

            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ModelValidationError(f"duplicate JSON field {key!r} is not allowed")
                result[key] = value
            return result

        try:
            raw = json.loads(
                text,
                parse_constant=reject_constant,
                object_pairs_hook=reject_duplicate_keys,
            )
        except json.JSONDecodeError as exc:
            raise ModelValidationError(
                f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc
        return cls.from_dict(raw)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "TaskSpec":
        """Read a UTF-8 task file and parse it through the strict boundary."""

        json_path = Path(path)
        try:
            text = json_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ModelValidationError(f"task file must be UTF-8: {json_path}") from exc
        return cls.from_json(text)

    @property
    def command(self) -> tuple[str, ...]:
        """Expose the registered process argv without shell interpretation."""

        return self.source.command

    @property
    def seeds(self) -> tuple[int, ...]:
        """Expose the immutable pre-registered seed order."""

        return self.execution.seeds

    @property
    def metric_name(self) -> str:
        """Expose the claim metric used in reports and verdicts."""

        return self.claim.metric

    @property
    def expected_value(self) -> float:
        """Expose the paper-reported comparison baseline."""

        return self.claim.reported_value

    @property
    def acceptance(self) -> AcceptanceSpec:
        """Expose the claim-bound acceptance policy."""

        return self.claim.acceptance

    def to_dict(self) -> dict[str, Any]:
        """Return the stable normalized representation persisted before a run."""

        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "paper": self.paper.to_dict(),
            "source": self.source.to_dict(),
            "claim": self.claim.to_dict(),
            "execution": self.execution.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One seed execution, suitable for deterministic report rendering."""

    seed: int
    status: str
    observed_value: float | None = None
    attempt_id: str | None = None
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    duration_seconds: float | None = None
    error: str | None = None
    evidence_hashes: Mapping[str, str] = field(default_factory=dict)

    STATUSES = frozenset({"SUCCEEDED", "FAILED", "TIMED_OUT", "SKIPPED"})

    def __post_init__(self) -> None:
        """Validate status-dependent fields and freeze nested collections."""

        seed = _integer(self.seed, "attempt.seed")
        if self.status not in self.STATUSES:
            allowed = ", ".join(sorted(self.STATUSES))
            raise ModelValidationError(f"attempt.status must be one of: {allowed}")
        observed = (
            None
            if self.observed_value is None
            else _number(self.observed_value, "attempt.observed_value")
        )
        if self.status == "SUCCEEDED" and observed is None:
            raise ModelValidationError("a successful attempt must include observed_value")
        if self.status != "SUCCEEDED" and observed is not None:
            raise ModelValidationError("an unsuccessful attempt must not include observed_value")
        if self.exit_code is not None:
            _integer(self.exit_code, "attempt.exit_code")
        duration = (
            None
            if self.duration_seconds is None
            else _number(self.duration_seconds, "attempt.duration_seconds", minimum=0.0)
        )
        command = tuple(_string(arg, "attempt.command[]", allow_empty=True) for arg in self.command)
        evidence: dict[str, str] = {}
        for path, digest in self.evidence_hashes.items():
            clean_path = _string(path, "attempt.evidence_hashes key")
            clean_digest = _string(digest, f"attempt.evidence_hashes[{path!r}]")
            if len(clean_digest) != 64 or any(
                char not in "0123456789abcdef" for char in clean_digest
            ):
                raise ModelValidationError("attempt evidence hashes must be lowercase SHA-256 hex")
            evidence[clean_path] = clean_digest
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "observed_value", observed)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "duration_seconds", duration)
        object.__setattr__(self, "evidence_hashes", MappingProxyType(evidence))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible per-seed evidence index."""

        return {
            "attempt_id": self.attempt_id,
            "seed": self.seed,
            "status": self.status,
            "observed_value": self.observed_value,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "evidence_hashes": dict(self.evidence_hashes),
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Deterministic verdict and the values needed to audit it."""

    status: str
    metric_name: str
    expected_value: float
    aggregate_value: float | None
    aggregation: str
    observed_values: tuple[float, ...]
    successful_seeds: int
    required_seeds: int
    absolute_error: float | None
    relative_error: float | None
    absolute_tolerance: float | None
    relative_tolerance: float | None
    evidence_hashes: Mapping[str, str]
    reason: str

    STATUSES = frozenset({"PASS", "FAIL", "INCONCLUSIVE"})

    def __post_init__(self) -> None:
        """Validate verdict state and freeze observed values/evidence hashes."""

        if self.status not in self.STATUSES:
            allowed = ", ".join(sorted(self.STATUSES))
            raise ModelValidationError(f"verification status must be one of: {allowed}")
        if self.successful_seeds != len(self.observed_values):
            raise ModelValidationError("successful_seeds must equal len(observed_values)")
        if self.required_seeds < 1:
            raise ModelValidationError("required_seeds must be at least 1")

    @property
    def passed(self) -> bool | None:
        """Map PASS/FAIL to booleans and INCONCLUSIVE to ``None``."""

        if self.status == "INCONCLUSIVE":
            return None
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        """Return all verdict inputs, math, hashes, and explanation as JSON."""

        return {
            "status": self.status,
            "passed": self.passed,
            "metric_name": self.metric_name,
            "expected_value": self.expected_value,
            "aggregate_value": self.aggregate_value,
            "aggregation": self.aggregation,
            "observed_values": list(self.observed_values),
            "successful_seeds": self.successful_seeds,
            "required_seeds": self.required_seeds,
            "absolute_error": self.absolute_error,
            "relative_error": self.relative_error,
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
            "evidence_hashes": dict(self.evidence_hashes),
            "reason": self.reason,
        }


__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "AcceptanceSpec",
    "AttemptRecord",
    "ClaimSpec",
    "EvidenceSpec",
    "ExecutionSpec",
    "ModelValidationError",
    "PaperSpec",
    "SourceSpec",
    "TaskSpec",
    "VerificationResult",
]
