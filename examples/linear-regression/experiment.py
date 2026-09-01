"""Trusted offline fixture used to exercise the reproduction pipeline.

The fixture fits ordinary least squares to a fixed synthetic dataset and writes
machine-readable evidence to ``REPRO_OUTPUT_DIR``.  It intentionally uses only
the Python standard library so the demo works without downloading packages.
"""

from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path


def dataset() -> list[tuple[float, float]]:
    """Build a fixed linear dataset with small deterministic perturbations."""

    rows: list[tuple[float, float]] = []
    for index in range(1, 61):
        x_value = float(index)
        deterministic_noise = (((index * 17) % 11) - 5) * 0.15
        y_value = 3.0 * x_value + 2.0 + deterministic_noise
        rows.append((x_value, y_value))
    return rows


def fit_ordinary_least_squares(rows: list[tuple[float, float]]) -> tuple[float, float]:
    """Return slope and intercept for an ordinary least-squares line."""

    mean_x = sum(row[0] for row in rows) / len(rows)
    mean_y = sum(row[1] for row in rows) / len(rows)
    denominator = sum((x_value - mean_x) ** 2 for x_value, _ in rows)
    slope = sum(
        (x_value - mean_x) * (y_value - mean_y) for x_value, y_value in rows
    ) / denominator
    intercept = mean_y - slope * mean_x
    return slope, intercept


def main() -> None:
    """Split by the registered seed, evaluate RMSE, and write metrics.json."""

    seed = int(os.environ.get("REPRO_SEED", "0"))
    output_directory = Path(os.environ.get("REPRO_OUTPUT_DIR", "."))
    output_directory.mkdir(parents=True, exist_ok=True)

    # The seed changes only the train/test split; the underlying dataset stays
    # fixed so repeated runs isolate stochastic sampling behavior.
    rows = dataset()
    indices = list(range(len(rows)))
    random.Random(seed).shuffle(indices)
    test_indices = set(indices[:15])
    train_rows = [row for index, row in enumerate(rows) if index not in test_indices]
    test_rows = [row for index, row in enumerate(rows) if index in test_indices]

    slope, intercept = fit_ordinary_least_squares(train_rows)
    squared_errors = [
        (y_value - (slope * x_value + intercept)) ** 2
        for x_value, y_value in test_rows
    ]
    rmse = math.sqrt(sum(squared_errors) / len(squared_errors))

    # The workflow reads rmse, while the extra fields make the result auditable.
    evidence = {
        "rmse": rmse,
        "seed": seed,
        "n_train": len(train_rows),
        "n_test": len(test_rows),
        "slope": slope,
        "intercept": intercept,
    }
    (output_directory / "metrics.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
