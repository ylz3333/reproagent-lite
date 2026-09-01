# Security policy and threat model

## Intended use

ReproAgent-Lite executes scientific experiment code. Repository and paper contents should be
treated as untrusted inputs. The Docker backend reduces risk and makes runs more repeatable;
it is not a hardened multi-tenant sandbox.

## Controls in this MVP

- Experiment commands are argument arrays and run with `shell=False`.
- Workspace paths are canonicalized and rejected when they escape the allowed root.
- Local runs receive a small environment that excludes API keys and credential-like values.
- Docker receives only the registered seed and output path—not the host environment.
- Docker build and experiment runtime have separate network policies, so dependency fetching
  does not require granting network access to the trained experiment.
- Source and container root filesystems are read-only; only the per-attempt output mount and
  bounded `/tmp` are writable.
- Containers run without root privileges, Linux capabilities, privilege escalation, network
  access by default, or a shared IPC namespace.
- CPU, memory, PID, file-descriptor, temporary-storage, and wall-clock limits are applied.
- A unique container name allows forced cleanup after a timeout.
- Source, inputs, outputs, logs, and execution metadata are hashed for later auditing.

## Explicit non-goals

This MVP does not defend against Docker daemon compromise, container runtime or kernel
vulnerabilities, malicious resource use during an explicitly network-enabled build, poisoned
base images, side channels, or attacks on other services reachable from the host. It also
does not verify dataset licenses or automatically determine whether downloaded artifacts are
safe.

For unknown or hostile repositories, use a disposable VM or microVM worker with a fresh
Docker daemon, no personal files or credentials, an outbound network allowlist, and host-level
resource quotas. Destroy the worker after the evidence bundle has been exported.

## Local backend

The local backend is for bundled or user-authored fixtures only. It is guarded by the
`--allow-unsafe-local` flag, but that flag is an acknowledgement—not a sandbox. A local child
process can access anything available to the current operating-system account.

## Sensitive data

Do not place secrets in task files, source repositories, command arguments, paper metadata,
or output logs. Evidence bundles are designed for sharing and may preserve stdout, stderr,
paths, repository URLs, and exact paper quotes.

## Reporting a vulnerability

When sharing a security report, include the affected version, backend, operating system,
minimal reproduction, and whether untrusted code was executed. Do not include live secrets or
private datasets.
