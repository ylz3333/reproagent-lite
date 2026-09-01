# Task format

ReproAgent-Lite accepts UTF-8 JSON with schema version `1.0`. The parser is intentionally
strict: all required fields must be present and unknown fields are errors.

## Complete example

```json
{
  "schema_version": "1.0",
  "task_id": "paper-dataset-metric-v1",
  "title": "Reproduce the primary test-set metric",
  "description": "One claim, one immutable implementation, three seeds.",
  "paper": {
    "pdf_path": "paper.pdf",
    "repository_url": "https://github.com/example/project.git",
    "commit_sha": "0123456789abcdef0123456789abcdef01234567",
    "evidence": [
      {
        "field": "reported_value",
        "quote": "Our method obtains test RMSE of 0.5057.",
        "page": 7,
        "table": "Table 2",
        "cell": "Ours / RMSE",
        "confidence": 1.0
      }
    ]
  },
  "source": {
    "directory": "repository",
    "command": ["{python}", "run_experiment.py", "--seed-env", "REPRO_SEED"],
    "result_file": "metrics.json",
    "metric_key": "test.rmse"
  },
  "claim": {
    "metric": "test.rmse",
    "reported_value": 0.5057,
    "unit": "absolute",
    "acceptance": {
      "mode": "absolute",
      "tolerance": 0.01,
      "min_successful_seeds": 3,
      "aggregation": "mean"
    }
  },
  "execution": {
    "seeds": [7, 19, 42],
    "timeout_seconds": 1800,
    "cpu_limit": 4.0,
    "memory_mb": 8192,
    "build_network": false,
    "network": false
  }
}
```

Paths are resolved relative to the task file. The run directory must be outside the source
directory so generated evidence cannot change the registered source hash.

## Field rules

### `paper`

- `pdf_path` may be `null` for a synthetic fixture.
- `repository_url` and `commit_sha` must either both be strings or both be `null`.
- Each evidence object requires `field` and an exact `quote`; `page`, `table`, `cell`, and
  `confidence` are optional.
- `confidence` is a trace of extraction certainty, not scientific confidence, and must be in
  `[0, 1]`.

### `source`

- `directory` and `result_file` must remain inside the task/source roots after path
  resolution.
- `command` is a non-empty JSON array. Shell strings are not accepted.
- `{python}` resolves to the active interpreter locally and `python` inside Docker.
- `metric_key` supports dot-separated traversal, such as `test.rmse`.

### `claim.acceptance`

- `absolute`: accept when `abs(observed - expected) <= tolerance`.
- `relative`: accept when the absolute difference is at most `tolerance * abs(expected)`.
- `both`: accept when either the absolute `tolerance` or `relative_tolerance` condition is
  met, matching conventional `isclose` behavior.
- `aggregation` is one of `mean`, `median`, `min`, or `max`.
- `min_successful_seeds` cannot exceed the number of registered seeds.

When the expected value is zero, relative error is infinite for any non-zero observation;
use an absolute tolerance for that case.

### `execution`

- Seeds must be unique integers.
- Network access defaults to a deny policy in the example and should be enabled only when the
  experiment genuinely requires it.
- `build_network` controls Docker image construction separately from runtime `network`.
  Enable it only when a pinned dependency must be downloaded while building the image.
- Docker enforces the requested timeout, CPU, memory, and PID controls. The local trusted
  fixture backend enforces only the process timeout.

## Experiment output contract

The command receives:

- `REPRO_SEED`: the current registered seed; and
- `REPRO_OUTPUT_DIR`: the directory in which to write artifacts.

It must exit with status `0` and write the configured `result_file` as UTF-8 JSON. The value
at `metric_key` must be a finite JSON number. Booleans, strings, `NaN`, and infinities are
rejected.
