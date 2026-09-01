# GCN on Cora: real-paper reproduction case

This case study targets Table 2 of Thomas N. Kipf and Max Welling's
*Semi-Supervised Classification with Graph Convolutional Networks* (ICLR 2017).
The registered claim is `81.5%` Cora test accuracy for the paper's GCN model on
the fixed Planetoid split.

## Frozen inputs

| Input | Frozen value |
|---|---|
| Paper | arXiv `1609.02907`, local PDF SHA-256 `a654f884...a98070` |
| Official repository | `https://github.com/tkipf/gcn.git` |
| Upstream commit | `39a4089fe72ad9f055ed6fdb9746abdcfebc4d81` |
| Dataset | Cora files included by the upstream repository |
| Paper evidence | Page 6, Table 2, `GCN (this paper) / Cora = 81.5` |

The repository is preserved in `experiment/upstream`, including its own Git
metadata. `experiment/upstream/PROVENANCE.json` records the paper and source
hashes. Docker and instrumentation files live inside the checkout so the
workflow can verify the actual Git HEAD before execution.

## Auditable instrumentation

The scientific model, hyperparameters, dataset split, early stopping, and
accuracy calculation are unchanged. One patch does only two things:

1. replaces the hard-coded seed `123` with `REPRO_SEED`; and
2. writes the already-computed test result and runtime versions to
   `REPRO_OUTPUT_DIR/metrics.json`.

The upstream `requirements.txt` simultaneously pins NumPy `1.15.4` and
TensorFlow `1.15.4`, although that TensorFlow release declares NumPy
`>=1.16,<1.19`. The Docker environment therefore records a narrow dependency
repair to NumPy `1.18.5` and Protobuf `3.20.3`. This changes environment
compatibility, not model logic, and is recorded in `PROVENANCE.json`.

The exact patch is stored at
`experiment/upstream/patches/0001-reproagent-instrumentation.patch`. From the
upstream repository, verify it with:

```bash
git diff -- gcn/train.py
git apply --reverse --check patches/0001-reproagent-instrumentation.patch
```

## Run the three-seed smoke task

Start Docker Desktop, open PowerShell at the ReproAgent-Lite project root, and
double-click `run-gcn-smoke.cmd`. The equivalent PowerShell command is:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m reproagent_lite validate case-studies\gcn-cora\task-smoke.json
python -m reproagent_lite run case-studies\gcn-cora\task-smoke.json `
  --run-dir runs\gcn-cora-smoke
```

The image build may take several minutes because it downloads the pinned
TensorFlow 1.15 environment. Runtime networking remains disabled. The three
seed task checks infrastructure and instrumentation; its looser `±3.0`
percentage-point tolerance is not the paper-level verdict.

## Run the paper-aligned task

After the smoke task succeeds:

Double-click `run-gcn-full.cmd`, or run:

```powershell
python -m reproagent_lite run case-studies\gcn-cora\task-full.json `
  --run-dir runs\gcn-cora-full
```

The full task pre-registers seeds `0..99`, requires all 100 usable results,
aggregates their mean, and compares it with `81.5%` using an engineering
tolerance of `±1.0` percentage point. The paper reports the target and 100-run
protocol but does not publish an uncertainty interval for the fixed split, so
the tolerance is explicitly identified as ours rather than attributed to the
authors.

## Interpretation

A PASS supports reproduction of this one numerical claim under the frozen
code, data split, dependency versions, seed list, and tolerance. It does not
validate every result or conclusion in the paper.
