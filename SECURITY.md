# Security model

benchy lets an AI coding agent run arbitrary commands with every permission its CLI offers
(`--allow-all`, `bypassPermissions`). That is only acceptable because the **container is the
sandbox**. This page explains what is protected, how, and what is not.

## What runs where

| Step | Image | Network | Can see |
|---|---|---|---|
| setup | grader | on (clone repo, install deps, fetch reference data) | benchy repo (read-only), `out/` |
| agent | agent | on (model API) | its own workspace, its own `raw/` dir, prompt, stored login (read-only) |
| finalize (grade, screenshots) | grader | **off** | benchy repo (read-only), `out/`, the finished workspace |
| report | grader | **off** | `out/` |

Every container: non-root (`--user` = your uid), `--cap-drop ALL`, `--security-opt
no-new-privileges`, read-only root filesystem with a size-limited tmpfs `/tmp`, a PID limit,
and (agent) fixed CPU/memory limits. No container ever gets the Docker socket.
`./bench selftest` runs a *probe* harness that checks these properties from inside the agent
container and fails if any is missing.

## Credentials

- **No PATs.** Copilot CLI signs in with the OAuth device flow (`copilot login --device-code`),
  like the CLI on your laptop. Claude Code uses `claude auth login`.
- Tokens live only in the named Docker volume `benchy-auth`. It is never a bind mount into this
  repository, never baked into an image, and is mounted **read-only** into agent runs (copied
  into a per-run tmpfs so each run's session state is isolated and discarded).
- Environment tokens (`GH_TOKEN`, `GITHUB_TOKEN`, `COPILOT_GITHUB_TOKEN`, `ANTHROPIC_API_KEY`) are
  never forwarded into containers and are stripped before the harness starts, so a stray host
  variable can't silently override the stored login.
- Every artifact copied out of the agent container (stdout/stderr, telemetry, session logs,
  transcripts) is passed through `src/benchy/redact.py` first. The selftest scans `out/` for
  credential-shaped strings.
- `./bench logout` deletes the volume. Revoke server-side under GitHub → Settings →
  Applications → Authorized OAuth Apps (and the equivalent for Claude).

## Grading integrity

- Hidden checks and golden solutions (`tasks/*/hidden`, `tasks/_lib`) are never mounted into
  the agent container. The agent's workspace is a fresh single-commit repository, so git
  history can't reveal what the task setup changed.
- Grading runs with **no network**, because it executes agent-written code (tests).
- The regression check restores the original test files before running them, so editing tests
  can't make a failure disappear.
- Checks run against a pristine copy of the dependency virtualenv and a tree cleaned of
  untracked/ignored files, so an agent can't patch the interpreter or leave stray artifacts
  that make checks pass.
- The secret scan uses benchy's own gitleaks config, ignores any `.gitleaksignore` and inline
  `gitleaks:allow` comments the agent adds, and never records the secret value itself.

## Known limits (be honest about them)

- **The agent has outbound network access** (it must reach its model API). It could fetch
  arbitrary content or send workspace content elsewhere. Only point benchy at repositories you
  are allowed to send to your AI provider anyway. An egress allow-list proxy is a planned
  hardening step; set `BENCHY_AGENT_NETWORK` to a restricted Docker network if you have one.
- A deliberately adversarial agent could tamper with its own `raw/` telemetry. benchy assumes
  agents are not adversarial toward the benchmark. Cross-check cost against your GitHub billing
  page for anything important.
- `out/` contains transcripts and diffs of the target repository. If you benchmark internal
  code, treat `out/` as confidential. It is git-ignored for that reason.
- Container isolation is not a VM boundary. Keep Docker Desktop updated.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting (Security → Report a vulnerability) on this
repository rather than a public issue.
