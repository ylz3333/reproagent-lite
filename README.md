# ReproAgent-Lite

An evidence-first scientific reproduction agent that turns a pre-registered paper claim
into an executable experiment, a deterministic verdict, and an auditable evidence bundle.

This repository is a working MVP, not a chat-only prototype. It includes strict task
validation, page-linked claim discovery, multi-seed experiment execution, sandbox-oriented
Docker controls, deterministic metric verification, SHA-256 evidence manifests, and a
complete offline demo.

## What it does

```text
paper / claim hint
        ↓
candidate values + page evidence
        ↓ human confirmation
pre-registered task and tolerance
        ↓
source hash → isolated runs → machine-readable metrics
        ↓
deterministic PASS / FAIL / INCONCLUSIVE
        ↓
report + logs + manifests + evidence hashes
```

The optional model step may propose a structured claim draft. It never decides the final
verdict. Verification is deterministic and uses the acceptance rule recorded before the
experiment runs.

## Quick start

ReproAgent-Lite requires Python 3.11 or newer. The bundled demo uses only the standard
library and does not require an API key.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\reproagent.exe doctor
.\.venv\Scripts\reproagent.exe demo --run-dir runs/demo
```

On macOS or Linux, replace the last three commands with:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/reproagent doctor
.venv/bin/reproagent demo --run-dir runs/demo
```

The demo should finish with `Demo verdict: PASS`. Its human-readable result is written to
`runs/demo/report.md`; the JSON verdict and every supporting artifact are stored beside it.

## Included real-paper case study

`case-studies/gcn-cora` contains a complete reproduction target for Kipf and Welling's
*Semi-Supervised Classification with Graph Convolutional Networks* (ICLR 2017). It includes
the paper PDF, the author's official repository frozen at commit
`39a4089fe72ad9f055ed6fdb9746abdcfebc4d81`, Cora data, an auditable instrumentation patch,
a pinned TensorFlow 1.15 Docker environment, a three-seed smoke task, and the paper-aligned
100-seed task.

After starting Docker Desktop, run the smoke task first:

On Windows, the simplest option is to double-click `run-gcn-smoke.cmd` in the project
folder. After it succeeds, `run-gcn-full.cmd` launches the 100-seed paper-aligned run.

The equivalent command-line invocation is:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m reproagent_lite run case-studies\gcn-cora\task-smoke.json `
  --run-dir runs\gcn-cora-smoke
```

See the [case-study protocol](case-studies/gcn-cora/README.md) before interpreting its
verdict. Image construction may access the network to download pinned dependencies, while
experiment runtime networking remains disabled.

## Run a reproduction task

Validate the task first:

```bash
reproagent validate examples/linear-regression/task.json
```

Run untrusted or third-party experiment code with Docker, which is the default backend:

```bash
reproagent run path/to/task.json --run-dir runs/paper-001
```

For a fixture you wrote and trust, local execution is available only with an explicit
acknowledgement:

```bash
reproagent run path/to/task.json \
  --run-dir runs/trusted-fixture \
  --backend local \
  --allow-unsafe-local
```

Do not use the local backend on downloaded repositories.

## Extract claim candidates from a paper

PDF support and model assistance are optional:

```bash
python -m pip install -e ".[pdf,openai]"
reproagent extract \
  --pdf paper.pdf \
  --target "Adult test AUC in Table 2" \
  --output claim-draft.json
```

The deterministic extractor returns numeric candidates with exact page evidence. To ask an
OpenAI model to structure the candidate while retaining the evidence requirement, configure
`OPENAI_API_KEY` and either `OPENAI_MODEL` or `--model`, then add `--llm`.

Paper text is treated as untrusted data in the model instructions. A user must still confirm
the selected metric, value, unit, and tolerance before promoting the draft to a runnable
task. The model integration uses the Responses API and follows the separation between
orchestration, guardrails, and sandboxed execution described in the official
[agent orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration),
[guardrails](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals), and
[sandbox](https://developers.openai.com/api/docs/guides/agents/sandboxes) guides.

## Evidence bundle

Each run directory contains:

| Artifact | Purpose |
|---|---|
| `task.normalized.json` | Canonical validated task |
| `claim.json` | Claim and pre-registered acceptance rule |
| `plan.json` | Seeds, metric, backend, and fixed workflow stages |
| `source_manifest.json` | Task, paper, repository, commit, and source hashes |
| `attempts/seed-*/execution.json` | Command, runtime, exit status, and backend |
| `attempts/seed-*/stdout.log` | Captured standard output |
| `attempts/seed-*/stderr.log` | Captured standard error |
| `attempts/seed-*/metrics.json` | Machine-readable experiment result |
| `attempts.json` | Normalized records for all seeds |
| `verdict.json` | Deterministic verdict and tolerance math |
| `report.md` | Human-readable report |
| `state.json` | Latest persisted workflow state |

A `PASS` means only that the registered aggregate metric met the registered tolerance. It
does not establish every scientific claim in the paper.

## Isolation model

The Docker backend uses a read-only root filesystem and source mount, a dedicated writable
output mount, a non-root user, dropped Linux capabilities, `no-new-privileges`, no IPC
namespace, PID/CPU/memory/file-descriptor limits, a bounded temporary filesystem, and no
network unless the task explicitly enables it. Images are content-addressed and built once
per workflow. Timed-out containers are forcibly removed.

Docker is still a containment layer, not a proof of safety. A Docker daemon is privileged,
and a malicious Dockerfile or kernel exploit remains outside this MVP's guarantees. Run
hostile repositories on a disposable VM or remote worker with no personal credentials. See
[SECURITY.md](SECURITY.md) for the full trust model.

## Task definition

The strict JSON task schema records:

- the claim and its source evidence;
- the immutable repository commit when one is used;
- an argument-list command, never a shell command string;
- the result file and metric key;
- seeds and resource/network policy; and
- the expected value, aggregation rule, and tolerance fixed before execution.

Unknown fields, duplicate JSON keys, non-finite numbers, path escapes, duplicate seeds, and
inconsistent repository metadata are rejected. See [docs/TASK_FORMAT.md](docs/TASK_FORMAT.md)
and the runnable [example task](examples/linear-regression/task.json).

## Development and verification

The test suite has no third-party dependency:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests examples
```

The tests cover strict schema validation, claim evidence extraction, optional Responses API
integration with an injected client, path and credential controls, Docker isolation command
construction and timeout cleanup, metric verification, and the full local workflow.

## Research roadmap

The MVP deliberately keeps autonomous actions narrow. Strong next steps are:

1. add a repository resolver that requires immutable commits and records dataset licenses;
2. propose dependency and command repairs as reviewable patches instead of silently changing
   the experiment;
3. support typed result adapters for common ML frameworks while preserving raw artifacts;
4. run each attempt on a disposable VM or microVM worker rather than a developer machine;
5. evaluate claim extraction, execution success, metric fidelity, and evidence completeness
   separately on a fixed benchmark set; and
6. add an approval UI that freezes the claim and tolerance before execution.

Start a code review with the [file-by-file review guide](docs/CODE_REVIEW_GUIDE.md).
The component design and trust boundaries are also summarized in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT
