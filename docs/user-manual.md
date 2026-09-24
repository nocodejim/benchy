# benchy user manual

This manual is for engineers who run benchy, read its results, or add tasks for their own stack.
For a short, non-technical summary of the approach, see
[overview-for-leaders.md](overview-for-leaders.md).

Contents

1. [What benchy measures, and what it does not](#1-what-benchy-measures-and-what-it-does-not)
2. [Two kinds of testing: the benchmark and the benchmark's own tests](#2-two-kinds-of-testing)
3. [Setup on Windows + WSL + Docker Desktop](#3-setup-on-windows--wsl--docker-desktop)
4. [Choosing contenders: models and reasoning levels for all four vendors](#4-choosing-contenders)
5. [Running a batch and rebuilding reports](#5-running-a-batch-and-rebuilding-reports)
6. [Every output, file by file](#6-every-output-file-by-file)
7. [Reading the report](#7-reading-the-report)
8. [The six starter tasks](#8-the-six-starter-tasks)
9. [Adding a task for a new stack (worked example: Java/Maven)](#9-adding-a-task-for-a-new-stack)
10. [How many repeats, and what it will cost](#10-how-many-repeats-and-what-it-will-cost)
11. [Fairness rules](#11-fairness-rules)
12. [Security model](#12-security-model)
13. [Limitations](#13-limitations)
14. [Troubleshooting](#14-troubleshooting)
15. [Command and environment reference](#15-command-and-environment-reference)

---

## 1. What benchy measures, and what it does not

benchy hands an AI coding agent a realistic work ticket inside a real repository, lets it work
unattended in a locked-down container, and then grades the result with checks the agent never
saw. For each **contender** (a harness + model + reasoning effort, e.g. *Copilot CLI ·
gpt-5.4 · high*) it answers three questions:

| Question | Measured by |
|---|---|
| Does it work? | Resolve rate, pass^k, mean score, failure modes |
| What does it cost? | AI Credits / USD per run and per *resolved* task, tokens |
| How does it work? | Wall time, API time, tool calls, turns, lines changed |

**What it does not measure**

- **Interactive use.** Nobody answers the agent's questions (`--no-ask-user`). A model that is
  great in a back-and-forth chat but poor at finishing alone will score low here.
- **IDE agent mode.** VS Code agent mode cannot be driven headlessly, so Copilot is measured
  through Copilot CLI with the same models. Results should transfer, but the harness is not
  identical to the IDE.
- **Code quality beyond the checks.** A run that passes every check is "resolved", even if a
  reviewer would ask for changes. Churn (lines changed) and the screenshots help you spot this,
  but they are not scored.
- **Things that need a live system.** There is no Docker daemon, Kubernetes cluster, or
  Artifactory in the sandbox. Container, Helm and pipeline work is validated statically (linters,
  schemas, structural checks), not by actually building or deploying.
- **General model ranking.** Six tasks on one small Flask repo is a smoke test for *your*
  context. It is not a leaderboard. Its value grows with the tasks you add from your own
  backlog (section 9).

## 2. Two kinds of testing

There are two completely different things called "tests" in this repo. Keep them apart.

### 2.1 Benchmark tasks: these test the AI models

Each task under `tasks/<id>/` is a work ticket handed to a model. The starter tasks happen to be
about GitHub Actions, Artifactory, Rancher/Helm, Docker/Podman and a Python bug, because those
were the example stacks, but the question every task answers is the same: *given this ticket in a
real repo, can this model at this reasoning level finish it correctly, and what did that cost in
time and money?*

The grading checks for each task live in `tasks/<id>/task.yaml` and `tasks/<id>/hidden/`. They are
never mounted into the agent's container. Section 8 describes each task.

### 2.2 benchy's own tests: these test the benchmark

No AI runs here. These exist to prove the scoring can be trusted.

| Test | Command | What it proves |
|---|---|---|
| **Unit tests** (77, in `tests/`) | `./bench test` | Usage parsers read Copilot and Claude output correctly (`tests/test_metrics.py` against fixtures in `tests/fixtures/`); secrets are redacted from logs (`test_redact.py`); bad config is rejected (`test_config.py`); scope globbing works (`test_grading.py`); gitleaks still catches a planted secret even if the agent adds a `.gitleaks.toml`, `.gitleaksignore` or inline `gitleaks:allow` (`test_secret_scan.py`); and each grading check **rejects plausible wrong answers**, e.g. a workflow with write permissions must fail `gha-permissions-read` (`test_checklib.py`). |
| **mock** stand-in agent | `./bench selftest` | Applies the task's own golden answer (`tasks/<id>/hidden/solution.patch`) instead of calling an AI. Every task must score **100%** (resolved, score 1.0). Proves each task is solvable and the pipeline (branches, grading, screenshots, report) works end to end. Costs nothing. |
| **noop** stand-in agent | `./bench selftest` | Changes nothing. Every task must **fail**. Proves no task is already solved in its starting state; without this, a broken task would hand every model a free pass. |
| **probe** stand-in agent | `./bench selftest` | Runs a small script *inside* the agent sandbox and records what an agent could see and do (`out/runs/<id>/raw/probe.json`). The self-test fails if the agent runs as root, has any Linux capabilities, can write the root filesystem, can see hidden grader files (`checklib.py`, `solution.patch`, `test_hidden_tokens.py`, `task.yaml`), has a credential environment variable, sees more than one git commit (history would reveal the planted bugs), sees other runs' workspaces, or has the login volume mounted when it doesn't need it. |

The stand-in agents are defined in `src/benchy/harness/mock.py`. The self-test contenders are in
`tests/selftest/probe.yaml` and `tests/selftest/contenders.yaml` ("Mock A (golden patch)",
"Mock B (golden patch)", "Noop (starting state)"). The assertions are in `src/benchy/selftest.py`.

`./bench selftest` also verifies that every run got its own branch rooted at the pinned upstream
commit, screenshots are real PNGs, the report and `summary.png` were built, workspaces were
cleaned up, and nothing credential-shaped is present in the run outputs.

> **In example reports, "Mock A/B" and "Noop" are these stand-ins, not real models.** The mock's
> tokens, credits, turns and tool calls are synthetic numbers generated from the run ID
> (`MockHarness.harvest`), and its wall time is near zero. Don't read anything into them.

Run the self-test after building images, after changing any task, check, image version or
harness, and before publishing a comparison. CI (`.github/workflows/ci.yml`) runs lint, task
validation, the unit tests, the self-test and a secret scan on every PR.

## 3. Setup on Windows + WSL + Docker Desktop

Your machine needs only Docker and bash. Python, Node and the AI CLIs all live in the two images.
No GitHub PAT is used anywhere.

### 3.1 Prerequisites

1. Docker Desktop for Windows, with **Settings → Resources → WSL integration** enabled for your
   distro (e.g. Ubuntu).
2. In Docker Desktop, give the WSL VM enough memory. Each agent run is capped at 4 CPUs and
   6 GB (`BENCHY_AGENT_CPUS`, `BENCHY_AGENT_MEMORY`); the grader uses up to 2 GB of tmpfs.
   8 GB+ for Docker is comfortable.
3. Your org's Copilot policy must allow **Copilot CLI**, and the models you want to test must be
   enabled for your org (see 4.1).

### 3.2 Clone and build

In a WSL terminal:

```bash
git clone <this repo> ~/benchy && cd ~/benchy   # inside WSL, NOT under /mnt/c
./bench doctor                                  # Docker running? repo location? images? logins?
./bench build                                   # builds benchy-agent:local and benchy-grader:local
./bench selftest                                # zero-cost end-to-end check
```

Cloning under `/mnt/c/...` works but is slow and causes permission problems; `./bench doctor`
warns about it.

`./bench build` passes every pinned version in `docker/versions.env` as a build argument (base
image digests, Copilot CLI `1.0.88`, Claude Code `2.1.281`, actionlint, hadolint, helm,
kubeconform, gitleaks, JFrog CLI, schema commits). Rebuild after changing that file or either
Dockerfile, then rerun the self-test.

### 3.3 Sign in (device flow, no PAT)

```bash
./bench login copilot
```

This runs `copilot login --device-code` **inside** the agent image. It prints a short code; open
`https://github.com/login/device` in your normal Windows browser, enter the code and approve with
your usual SSO/2FA. The resulting OAuth token is stored in the Docker volume `benchy-auth`
(under `/auth/copilot`). It is never written into this repository or into `out/`.

- `./bench login claude` does the same for Claude Code (`claude auth login`), if you also want
  Claude Code as a second harness.
- `./bench doctor` shows which logins are stored.
- `./bench logout` deletes the whole volume; `./bench logout copilot` deletes only that login.
  To revoke server-side: GitHub → Settings → Applications → Authorized OAuth Apps.
- Host variables `GH_TOKEN`, `GITHUB_TOKEN`, `COPILOT_GITHUB_TOKEN`, `ANTHROPIC_API_KEY` are
  never forwarded and are stripped before the harness starts.

**Corporate network.** `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` (either case) are passed through to
the steps that need the network. For a TLS-inspecting proxy, `export
BENCHY_CA_BUNDLE=/path/to/ca.pem` (mounted into the agent as `NODE_EXTRA_CA_CERTS`).

**GitHub Enterprise Cloud with data residency.** Copilot CLI reads `COPILOT_GH_HOST` (verified in
`copilot help environment`). ⚠️ `./bench` does **not** currently forward this variable into the
login or agent containers, so setting it on the host has no effect yet. It needs a small change
to `./bench` (add it to the variables passed through alongside the proxy settings).

### 3.4 Opening reports from WSL

```bash
explorer.exe "$(wslpath -w out/report/latest.html)"
```

## 4. Choosing contenders

A contender is one line in `contenders.yaml` (git-ignored; copy `contenders.example.yaml`):

```yaml
contenders:
  - name: "GPT-5.4 · high"      # label in the report; must be unique
    harness: copilot            # copilot | claude  (mock | noop | probe are for selftest)
    model: gpt-5.4              # id the harness accepts
    effort: high                # reasoning effort
```

Optional per contender (`contenders.example.yaml`):

| Key | Effect |
|---|---|
| `max_ai_credits: 300` | Copilot `--max-ai-credits` soft cap per run. Changes agent behaviour; use sparingly and for every contender or none. |
| `max_budget_usd: 3` | Claude Code `--max-budget-usd` cap per run. |
| `extra_args: [...]` | Extra CLI flags for this contender only. Each must match `^[A-Za-z0-9._:/@+=\-]{1,128}$`. Keep contenders comparable. |

Validation rules (`src/benchy/config.py`): names unique; harness+model+effort combination
unique; `effort` must be one of `none, minimal, low, medium, high, xhigh, max, ultracode`.

### 4.1 One harness for all four vendors

Microsoft (MAI), OpenAI, Google (Gemini) and Anthropic (Claude) models can all be run through the
**same Copilot CLI harness**, changing only `--model` and `--reasoning-effort`, *provided GitHub
offers each model to your org*. That is the fairest setup: one tool, one sandbox, one set of
tasks. Use `harness: claude` (Claude Code) only as a secondary comparison of a different *tool*,
not a different model.

### 4.2 Finding the exact model IDs and reasoning levels

Model IDs depend on your Copilot plan and org policy, and change monthly. benchy does not ship a
list. Get them from Copilot CLI itself:

**Option A: interactive `/model` picker (recommended).** Copilot CLI has no non-interactive
"list models" command (verified: none in `copilot --help` for 1.0.88). Start an interactive
session in the agent image using your stored login:

```bash
docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
  --tmpfs /tmp:rw,exec -v benchy-auth:/auth:ro benchy-agent:local \
  bash -c 'mkdir -p /tmp/ch && cp -r /auth/copilot/. /tmp/ch/ && COPILOT_HOME=/tmp/ch copilot'
```

Then type `/model`. The picker lists every model your org allows, with its ID and the reasoning
levels it supports. Write the IDs down exactly. Type `/exit` to leave. (The command above copies
the login into a throwaway tmpfs, exactly like a real run does. *Not verified end to end here,
because it needs a signed-in account.*)

If you have Copilot CLI on your laptop already, `copilot` → `/model` there shows the same list
for the same account.

**Option B: check with a one-run smoke test.** Add the contender and run a single cheap task:

```bash
./bench run --tasks gha-ci-add --repeats 1
```

Then compare `model_requested` with `models_reported` in `out/runs/<id>/metrics.json` (also in
the report's *Environment* section). If they differ, Copilot silently substituted or routed the
model; fix the ID before a real batch. An unknown ID typically fails fast and shows up as a
"harness error" with the CLI's message in `warnings`.

**Reasoning levels.** Copilot CLI 1.0.88 accepts `--reasoning-effort` values `none, minimal,
low, medium, high, xhigh, max` (verified with `copilot --help`). Not every model supports every
level; the `/model` picker shows which. Claude Code's `--effort` accepts `low, medium, high,
xhigh, max` (verified with `claude --help`). benchy's config also allows `ultracode`, which
neither CLI lists; don't use it unless a CLI adds it.

**Verified flags.** Every flag benchy passes to Copilot CLI (`-p`, `--allow-all`, `--no-ask-user`,
`--no-custom-instructions`, `--disable-builtin-mcps`, `--no-auto-update`, `--no-color`,
`--stream off`, `--output-format json`, `--log-dir`, `--log-level`, `--share`,
`--usage-output-file`, `--model`, `--reasoning-effort`, `--max-ai-credits`) and `copilot login
--device-code` exist in the pinned CLI (checked with `docker run --rm benchy-agent:local copilot
--help` and `copilot login --help`). Re-check after bumping `COPILOT_CLI_VERSION`.

### 4.3 Sample `contenders.yaml`: four vendors, two or more levels

`contenders.example.yaml` already covers all four vendors at two thinking levels each, using
models from GitHub's
[supported models](https://docs.github.com/en/copilot/reference/ai-models/supported-models)
list (as of 2026-09-23: MAI-Code-1.1-Flash, GPT-5.6 Terra, Gemini 3.8 Flash, Claude Sonnet 5).

> ⚠️ GitHub's docs give display names ("MAI-Code-1.1-Flash"), not CLI IDs. The IDs in the example
> are those names lowercased (`mai-code-1.1-flash`), which matches the pattern of the other
> IDs, but **confirm each one in `/model`** (4.2) and run the one-run smoke test before a real
> batch.

Other models in the same list you might add: GPT-6 Sol / Luna / Astra, GPT-5.4, Claude Opus 5.5,
Claude Haiku 4.5, Gemini 3.5–3.7 Flash. Copy a line and change `model`, `effort` and `name`.

8 contenders × 6 tasks × 3 repeats = 144 runs. See section 10 before running something that
size.

If a model is missing from `pricing.yaml` **and** the harness reports no cost, its $ columns show
"—". Copilot normally reports AI Credits, so `pricing.yaml` is only a fallback; add rates per
1M tokens for any model you use there (`input`, `cached_input`, `cache_write`, `output`).

## 5. Running a batch and rebuilding reports

```bash
./bench run                              # starter suite, contenders.yaml, 3 repeats
./bench run --repeats 5
./bench run --tasks gha-ci-add,rancher-deploy
./bench run --suite starter --contenders my-contenders.yaml
./bench run --timeout-scale 1.5          # multiply every task's timeout
./bench run --keep-workspaces            # keep out/work/<run-id>/repo for inspection
./bench run --no-screenshots             # faster; no PNGs or diff.html
```

`--contenders` is a path relative to the repo root. `--repeats` must be 1–50.

### What happens

```
plan      contenders x tasks x repeats, interleaved, rotating who goes first   (grader, no network)
for each run:
  setup     clone repo@pinned SHA -> prepare + task setup -> 1-commit workspace (grader, network)
  agent     copilot -p ... / claude -p ... with a hard timeout                (agent, sandboxed)
  finalize  commit result -> hidden checks -> metrics -> branch -> screenshots (grader, NO network)
report    HTML + Markdown + CSV + PNG                                          (grader, no network)
```

- **Batch ID** is a UTC timestamp; **run ID** is `<batch>-<task>-<harness-model-effort>-r<n>`.
- Order: repeat 1 of every task for every contender, then repeat 2, and so on. The contender
  order rotates each repeat so nobody always goes first (`setup_ws.plan`).
- Each run is independent. A failed setup or finalize is logged and the batch continues; the
  agent step exiting non-zero is recorded and the run is still graded.
- There are **no retries**. The agent is killed at `timeout_s` (SIGTERM, then SIGKILL after
  30 s). The whole container gets an extra 5-minute safety margin.

A batch is long-running and unattended. Leave the terminal open (or run it under `tmux`), and
make sure Windows doesn't sleep.

### Rebuilding reports

```bash
./bench report                      # latest batch
./bench report --batch 20260923T101500Z
./bench report --batch all          # every finished run in out/, all batches together
./bench report --no-screenshot      # skip summary.png
```

Reports are pure functions of `out/runs/*/metrics.json` and `out/batches/*.json`, so you can
rebuild them any time (e.g. after editing templates). Only combine batches with `--batch all`
when versions and dates match (section 13).

## 6. Every output, file by file

Everything lives under `out/` (git-ignored; override with `BENCHY_OUT`). Treat it as
confidential if you benchmark internal code.

```
out/
  batches/<batch>.json            the plan: contenders, tasks, repeats, every run id
  repos/<repo>.git                bare repo with one branch per run
  runs/<run-id>/                  one directory per run (below)
  report/<batch>/                 the report for one batch
  report/latest.html              redirect to the newest report
  cache/repos, cache/venvs, cache/pip   upstream mirror + dependency caches
  work/<run-id>/                  temporary workspace (deleted unless --keep-workspaces)
```

### 6.1 Git branches

`out/repos/<repo>.git` gets a branch `bench/<run-id>` per run with exactly three commits:

1. the pinned upstream commit (e.g. microblog `a975ef6`),
2. `benchy: task setup (<task>)`: the known starting state (repo `prepare` + task `setup`),
3. `benchy: agent result (<contender>)`: everything the agent left in the working tree. Its
   message includes a one-line summary and `Benchy-Run`, `Benchy-Harness`, `Benchy-Model`,
   `Benchy-Effort` trailers.

Branches are never overwritten. Review them like any branch:

```bash
git clone out/repos/microblog.git /tmp/mb
git -C /tmp/mb log --oneline --all
git -C /tmp/mb diff bench/<run-a>~1 bench/<run-a>      # what the agent did
git -C /tmp/mb diff bench/<run-a> bench/<run-b>        # two contenders' answers side by side
```

(The agent itself only ever saw a single orphan "baseline" commit; the three-commit history is
rebuilt afterwards for you.)

### 6.2 Per-run directory `out/runs/<run-id>/`

| File | Contents |
|---|---|
| `run.json` | The run's definition: task, title, category, repeat, contender, timeout, repo URL + SHA, baseline commit, branch name, SHA-256 of the prompt and the task directory, image IDs, benchy version. |
| `prompt.md` | The exact prompt sent: `tasks/_preamble.md` + the task's `prompt.md`. |
| `diff.patch` | Full diff baseline → agent result. |
| `numstat.tsv` | `added  deleted  path` per changed file. |
| `diff.html` | Interactive side-by-side diff (diff2html). |
| `summary.html` | The run card (outcome, checks, metrics). |
| `screenshots/00-summary.png` | PNG of the run card. |
| `screenshots/NN-<path>.png` | Side-by-side diff for each changed file (clipped at 12,000 px; full diff stays in `diff.html`). |
| `grade.json` | Every check: see 6.3. |
| `metrics.json` | Normalized metrics: see 6.4. |
| `aux/` | Grader-only reference data fetched during setup (e.g. `action-shas.txt`), plus `prefetch.log`. Never visible to the agent. |
| `raw/` | Redacted harness output: see 6.5. |

### 6.3 `grade.json`

```json
{
  "resolved": true,              // every REQUIRED check passed
  "score": 0.93,                 // weight of passed checks / total weight
  "checks_passed": 13, "checks_total": 14,
  "regression_ok": true,         // null when the repo has no test_cmd
  "scope_violations": [],        // changed paths outside allowed_paths
  "secrets_found": 0,
  "graded_at": "...",
  "checks": [
    {"id": "actionlint", "title": "...", "required": true, "weight": 2.0,
     "passed": true, "duration_s": 0.4, "output": "<last 4000 chars>"},
    ...
  ]
}
```

The task's own checks come first, then three built-in checks added to every task:
`regression` (required, weight 1), `scope` (required unless `scope_required: false`, weight 1),
`secrets` (required, weight 1). When a run fails, `output` of the failing check tells you why.

### 6.4 `metrics.json`

Rule: **a value the harness could not report is `null`, never 0.** The report shows it as "—" and
leaves it out of medians and totals. Defined in `src/benchy/metrics/schema.py`.

| Field | Meaning |
|---|---|
| `schema` | Schema version (1). |
| `run_id`, `batch`, `task`, `contender`, `harness`, `harness_version` | Identity. |
| `model_requested` / `models_reported` | What you asked for vs. what the harness says it used. Check these match. |
| `effort` | Reasoning effort requested. |
| `outcome.resolved` | Every required check passed. |
| `outcome.score` | Weighted fraction of checks passed, 0–1. |
| `outcome.checks_passed` / `checks_total` | Counts, including the 3 built-ins. |
| `outcome.regression_ok` | Original tests still pass. |
| `outcome.scope_violations` | Number of files changed outside `allowed_paths`. |
| `outcome.secrets_found` | gitleaks findings in the agent's changes. |
| `outcome.exit_status` | `ok`, `timeout`, `error`, or `not_run`. |
| `time.wall_s` | Measured by benchy around the harness process. |
| `time.api_s` | Harness-reported time waiting on the model API. |
| `time.session_s` | Harness-reported session length. |
| `activity.turns` | Model round trips. |
| `activity.tool_calls` | Tool invocations. |
| `activity.tool_calls_by_kind` | Split into `read / edit / shell / search / web / other` by tool name. |
| `tokens.input_fresh` | Uncached input tokens. |
| `tokens.cache_read` / `cache_write` | Cached input read / written. |
| `tokens.output` | Output tokens, **including** reasoning. |
| `tokens.reasoning` | Reasoning subset of output, when reported. |
| `tokens.total` | `input_fresh + cache_read + cache_write + output`. |
| `cost.ai_credits` | GitHub Copilot AI Credits (1 credit = $0.01). |
| `cost.premium_requests` | Legacy request-based plans only. |
| `cost.usd` | Dollars. |
| `cost.usd_source` | `credits` (from AI Credits), `reported` (Claude Code's own estimate), or `estimated-from-tokens` (via `pricing.yaml`). |
| `diff.files_changed`, `added`, `deleted`, `churn` | `churn = added + deleted`. |
| `sources` | Which raw artifact each number came from (e.g. `"tokens": "usage.json"`). |
| `warnings` | Anything suspicious: harness exit message, sources disagreeing on tokens by >5%, missing artifacts, screenshot failures. **Read these before trusting a number.** |
| `branch`, `branch_commit` | Where the result lives in `out/repos/`. |

Where Copilot numbers come from (`src/benchy/metrics/copilot_parse.py`), in priority order:
`--usage-output-file` JSON → session events (`session-state/*/events.jsonl`) → `--output-format
json` stdout stream → OpenTelemetry file export → the human exit summary text. Tool calls and
turns prefer OpenTelemetry. Claude Code numbers come from its `stream-json` `result` message
(`claude_parse.py`), and its cost is Claude Code's own client-side estimate.

> The Copilot parsers are written defensively because Copilot publishes no schema for these
> outputs. They are tested against fixtures, **not yet against a real successful run of the
> pinned CLI**. After your first real batch, check `sources` and `warnings` in a few
> `metrics.json` files and compare credits with your GitHub billing page.

### 6.5 `raw/`

Every file here has been passed through `src/benchy/redact.py` before leaving the agent container.

| File | From |
|---|---|
| `agent.json` | benchy: harness version, the command (prompt replaced by `<prompt.md>`), exit code, `timed_out`, `exit_status`, `wall_s`, start/end times, warnings. |
| `stdout.txt`, `stderr.txt` | The harness process output. For Copilot, stdout is the JSONL event stream; for Claude Code, `stream-json`. |
| `usage.json` | Copilot `--usage-output-file`. |
| `otel.jsonl` | Copilot OpenTelemetry file export. |
| `transcript.md` | Copilot `--share` session transcript: the most readable record of what the agent did. |
| `logs/` | Copilot `--log-dir` logs. |
| `session-state/` | Copilot session events. |
| `mock.json` | Synthetic numbers (mock harness only). |
| `probe.json` | Sandbox probe results (probe harness only). |

### 6.6 Report directory `out/report/<batch>/`

| File | Use |
|---|---|
| `index.html` | The full report (section 7). Links to each run's summary, diff and screenshots. |
| `summary.png` | Screenshot of the headline charts + scorecard. Paste into slides/Teams. |
| `summary.md` | Scorecard + per-task grid as Markdown. Paste into a wiki/PR. |
| `results.csv` | One row per run, all main metrics. For Excel/Power BI. |
| `aggregate.json` | The computed per-contender stats and per-task matrix. |

## 7. Reading the report

The header line shows the batch ID, number of runs, tasks and repeats, and when it was
generated. Each contender keeps the same colour throughout; colour follows the contender, never
its rank.

### 7.1 Conventions

- **Medians, with min–max ranges** in small grey text. With a handful of runs a mean is pulled
  around by one outlier; the median isn't. If two contenders' ranges overlap heavily, treat the
  difference as noise.
- **"—" means unknown** (the harness didn't report it), **never zero**. Unknowns are excluded
  from medians and totals.
- **`*` after Total cost** means some runs reported no cost, so the total is a lower bound.
- **Cost** is USD. Copilot: AI Credits × $0.01. Claude Code: its own estimate. Otherwise
  estimated from tokens via `pricing.yaml`.

### 7.2 Headline charts

| Chart | Question it answers | Better |
|---|---|---|
| **Resolve rate** | How often did this contender fully finish the ticket (every required check passed)? The headline number. | Higher |
| **Cost per resolved task** | What does one *successful* result cost, counting money spent on failed attempts? = total spend ÷ number of resolved runs. A cheap model that fails half the time is not cheap. Shows "— no data" if nothing was resolved. | Lower |
| **Median wall time per run** | How long a developer would wait. | Lower |
| **Median tokens per run** | How much text the model read and wrote (`tokens.total`, which includes cached input and cache writes). Explains cost and shows verbosity. | Lower |

### 7.3 Scorecard

| Column | Meaning / how to read it |
|---|---|
| **Resolved** | `resolved/runs (rate)`. |
| **pass^k** | Share of *tasks* the contender solved in **every** repeat. With 3 repeats, a task solved 2/3 times counts as 0 here. Measures reliability: can a team count on it daily? A contender with 70% resolve rate but 30% pass^k is erratic. |
| **Mean score** | Average partial credit (weighted share of checks passed). Close to the resolve rate = failures were total misses; much higher = near misses. |
| **Cost / resolved** | As in the chart. |
| **Credits / resolved** | Same in AI Credits (Copilot only). |
| **Total cost** | Everything spent in this batch by this contender. |
| **Median time** | Wall time, with min–max. |
| **Median tokens** | With min–max. |
| **Tokens / resolved** | All tokens ÷ resolved runs. |
| **Median tool calls** | With min–max. Many more calls for the same result usually means fumbling. |
| **Median turns** | Model round trips. |
| **Churn (resolved)** | Median lines added+deleted, **only on resolved runs**. Smaller correct diffs are easier to review. |

### 7.4 Per task

A grid of task × contender. Each cell: ✓ (solved every repeat), ◐ (sometimes), ✗ (never),
`resolved/runs`, then median cost and median time for that cell. **This is the section that
tells you which model suits which kind of work**, and the one to use for per-stack
recommendations.

### 7.5 Why runs failed

For each contender, counts of failure modes. Each failed run gets exactly one, the first that
applies in this order (`report/aggregate.py`):

| Mode | Meaning |
|---|---|
| `timeout` | Killed at the task's time limit. Spend still counts. |
| `harness error` | The CLI exited non-zero or never ran (auth, bad model ID, network, crash). Check `metrics.json → warnings` and `raw/stderr.txt`. Often a setup problem, not a model weakness. |
| `secret introduced` | gitleaks found a credential in the agent's changes. |
| `broke existing tests` | The repo's original test suite fails (with original test files restored). |
| `out of scope` | Changed files outside the ticket's `allowed_paths`. |
| `checks failed` | Simply wrong: one or more required task checks failed. |

### 7.6 All runs

Every run: task, contender, repeat #, result (✓ resolved / ✗ failed / ✗ timeout / ✗ error),
score, time, cost, credits, tokens, tool calls, `+added −deleted`, branch name, and links to
its **summary** card, **diff**, and **screenshots** folder. Start here when a number looks odd.

### 7.7 Environment and "How to read this"

*Environment* lists each contender's harness version(s) and the models the harness reported.
If a contender shows two harness versions or an unexpected model, the comparison is compromised.
*How to read this* is a short in-report version of this section.

Not shown in the HTML but available in `metrics.json`/`results.csv`: API time, the token
breakdown (fresh / cached / cache-write / output / reasoning), and tool calls by kind.

## 8. The six starter tasks

All start from [microblog](https://github.com/miguelgrinberg/microblog) (MIT), pinned at
`a975ef64864354867c88e0ed3a17ba7d17dca752` (`repos/microblog.yaml`), with a minimal dependency
bump for Python 3.12 (`repos/microblog/py312-deps.patch`). Every prompt starts with
`tasks/_preamble.md`: work autonomously, no Docker/Kubernetes available (validate statically),
tools on PATH, dependencies in `./.venv`, don't push, stay focused, never write real credentials.

Every task also gets the three built-in checks (**regression**, **scope**, **secrets**; see 6.3).
"Req." = required for *resolved*; "W" = weight in the score.

### 8.1 `bugfix-unit`: revoked API tokens keep working (INC-2041)

**Ticket.** Two support reports: tokens still work after `DELETE /api/tokens`; `POST
/api/tokens` sometimes hands out an already-expired token while valid ones get replaced. Fix the
root cause(s), add a regression test, keep the suite green. `setup/inject-bug.patch` plants two
bugs in the token code. Timeout 15 min. Allowed: `app/**`, `tests.py`.

| Check | Req. | W | Verifies | Why it matters |
|---|---|---|---|---|
| `hidden-token-tests` | ✓ | 4 | Hidden tests (`hidden/test_hidden_tokens.py`) exercise the model and the HTTP API: valid tokens reused, expired/near-expiry/revoked tokens rejected and never reissued. | The agent can't tailor its fix to tests it can see. This is what "the incident is actually fixed" means. |
| `regression-test-added` | – | 1 | A new `def test_…token/revok…` appears in `tests.py`. | Teams require a regression test with every incident fix. |
| `suite-with-new-tests` | ✓ | 1 | The updated `tests.py` passes. | The agent's own test must not be broken. |

### 8.2 `gha-ci-add`: add a GitHub Actions CI workflow (PLAT-318)

**Ticket.** The repo has no CI. Add `.github/workflows/ci.yml` to platform standards: PR and push
to `main`, Python 3.12, pip cache, run unit tests, read-only token, actions pinned to full commit
SHAs of released versions, cancel superseded runs, job timeouts, `actionlint` clean. Timeout
15 min. Allowed: `.github/**`.

| Check | Req. | W | Verifies | Why it matters |
|---|---|---|---|---|
| `actionlint` | ✓ | 2 | No findings. | Broken YAML/expressions fail at push time. |
| `triggers` | ✓ | 1 | PRs to main and pushes to main. | CI that doesn't gate PRs is useless. |
| `read-only-token` | ✓ | 2 | `permissions` read-only. | Least privilege; limits damage from a compromised step. |
| `runs-tests` | ✓ | 1 | Runs the unit tests. | CI that doesn't test is decoration. |
| `python-312` | ✓ | 1 | Uses Python 3.12. | Matches the runtime. |
| `sha-pinned` | ✓ | 2 | Every action pinned to a 40-char SHA. | Supply-chain policy: tags can be moved by an attacker. |
| `real-shas` | ✓ | 2 | Each pinned SHA is a real release tag of that action (reference list fetched at setup by `tasks/_lib/prefetch-action-shas.sh`). | **Catches models that invent plausible-looking SHAs**, which would break CI on day one. |
| `pip-cache` | – | 1 | pip cache configured. | Faster, cheaper CI. |
| `concurrency` | – | 1 | Superseded runs cancelled. | Saves runner minutes. |
| `timeouts` | – | 1 | Every job has `timeout-minutes`. | Stops hung jobs burning minutes. |

### 8.3 `gha-ci-fix`: fix the broken tag-release workflow (REL-77)

**Ticket.** `release.yml` (planted by `setup/broken-release.patch`) no longer publishes on `v*`
tags: actionlint errors, `publish` doesn't run or pushes an empty tag, and the push gets `denied:
permission_denied: write_package`. Four planted bugs: deprecated `::set-output`, a bad
expression, missing `needs`, missing package permission. Keep job names, trigger, SHA pins and a
read-only token except what `publish` needs. Timeout 15 min. Allowed: `.github/**`.

| Check | Req. | W | Verifies | Why it matters |
|---|---|---|---|---|
| `actionlint` | ✓ | 2 | No findings. | |
| `no-set-output` | ✓ | 1 | `::set-output` removed. | Deprecated; GitHub is removing it. |
| `version-output` | ✓ | 2 | `build` exposes `version` via `$GITHUB_OUTPUT`, wired to a job output. | The actual root cause of the empty tag. |
| `publish-needs-build` | ✓ | 1 | `publish` has `needs: build`. | Without it, outputs are unavailable and ordering is wrong. |
| `publish-uses-version` | ✓ | 1 | `publish` uses `needs.build.outputs.version`. | |
| `packages-write` | ✓ | 2 | Only `publish` gets `packages: write`; nothing else writes. | The easy "fix" is `write-all`; this rejects it. Least privilege is the business requirement. |
| `tag-trigger` | ✓ | 1 | Still triggered by `v*`. | Don't change behaviour you weren't asked to. |
| `still-pinned` | – | 1 | Actions still SHA-pinned. | |

### 8.4 `container-harden`: production Dockerfile + Compose (PLAT-402)

**Ticket.** Security review findings: multi-stage build, pinned base, numeric non-root user,
`HEALTHCHECK`, hadolint clean at warning level, `.dockerignore`, and a `compose.yaml` with
PostgreSQL that is Compose-spec valid, has no literal secrets (plus `.env.example`), waits for
a healthy DB, and uses fully-qualified image names so **Podman** doesn't prompt. Timeout 20 min.

| Check | Req. | W | Verifies | Why it matters |
|---|---|---|---|---|
| `hadolint` | ✓ | 2 | No warnings. | Catches common Dockerfile mistakes. |
| `multistage` | ✓ | 1 | More than one stage. | Smaller image, no build tools in production. |
| `pinned-base` | ✓ | 1 | Version tag or digest. | Reproducible builds. |
| `non-root` | ✓ | 2 | Final `USER` isn't root. | Container-escape blast radius. |
| `numeric-uid` | – | 1 | Numeric UID. | Kubernetes `runAsNonRoot` can only verify numeric users. |
| `healthcheck` | ✓ | 1 | `HEALTHCHECK` present. | Orchestrators can restart a hung app. |
| `dockerignore` | ✓ | 1 | Excludes `.git`, `.env`, `.venv`, `__pycache__`. | Secrets and history kept out of the build context. |
| `compose-valid` | ✓ | 2 | Validates against the official Compose spec schema (pinned, offline). | Works on both Docker Desktop and Podman. |
| `compose-secrets` | ✓ | 2 | No literal DB password/secret key. | Credentials in git. |
| `compose-healthy-dep` | – | 1 | `depends_on: condition: service_healthy`. | Avoids race-on-startup bugs. |
| `env-example` | – | 1 | `.env.example` exists, `.env` doesn't. | Developer onboarding without committing secrets. |

### 8.5 `artifactory-route`: route downloads through Artifactory (SEC-219)

**Ticket.** Policy: no direct internet downloads. Pull base images through
`artifactory.example.com/docker-remote/`, pip through the PyPI virtual repo, with credentials
only via a BuildKit build secret; add a workflow that logs in with repository secrets
`ARTIFACTORY_USER`/`ARTIFACTORY_TOKEN`, builds with the build secret and pushes to
`docker-local/microblog:<sha>`; read-only token, pinned actions. Timeout 20 min.

| Check | Req. | W | Verifies | Why it matters |
|---|---|---|---|---|
| `base-via-artifactory` | ✓ | 2 | Every `FROM` uses the docker-remote prefix. | Policy compliance; supply-chain control. |
| `pip-via-artifactory` | ✓ | 2 | The PyPI virtual URL is used. | |
| `pip-build-secret` | ✓ | 2 | pip creds via `RUN --mount=type=secret`. | Credentials never land in an image layer. |
| `no-cred-args` | ✓ | 2 | No credentials in `ARG`/`ENV` or URLs. | `ARG`/`ENV` values are visible in image history. |
| `no-literal-secrets` | ✓ | 2 | No literal credentials in Dockerfile/workflows/pip.conf. | |
| `actionlint` | ✓ | 1 | No findings. | |
| `ci-login` | ✓ | 1 | Workflow logs in using `secrets.*`. | |
| `ci-build-secret` | ✓ | 1 | Workflow passes pip creds as a build secret. | |
| `ci-push-local` | ✓ | 1 | Pushes to `docker-local/microblog`. | |
| `ci-read-only` | – | 1 | Read-only token. | |
| `ci-pinned` | – | 1 | Pinned to real release SHAs. | |
| `hadolint-errors` | – | 1 | No hadolint errors. | |

### 8.6 `rancher-deploy`: Helm chart + Rancher Fleet bundle (PLAT-455)

**Ticket.** Helm chart at `deploy/helm/microblog` (Deployment, Service :80 → 5000, Ingress
`networking.k8s.io/v1`, configurable image/host/class), requests and limits, probes, hardened
security context, `DATABASE_URL`/`SECRET_KEY` from an existing Secret; Fleet bundle
`deploy/fleet.yaml` targeting `env: staging` and `env: production` clusters in namespace
`microblog`, 3 replicas in production. Timeout 25 min. Allowed: `deploy/**`, `README.md`, `docs/**`.

| Check | Req. | W | Verifies | Why it matters |
|---|---|---|---|---|
| `helm-lint` | ✓ | 2 | `helm lint` passes. | |
| `kubeconform` | ✓ | 2 | Rendered output validates with `kubeconform -strict` against pinned offline Kubernetes 1.34 schemas. | Catches invented fields that a cluster would reject. |
| `kinds` | ✓ | 1 | Renders Deployment, Service, Ingress. | |
| `resources` | ✓ | 1 | CPU+memory requests and limits on every container. | Noisy-neighbour protection; many clusters reject pods without them. |
| `probes` | ✓ | 1 | Liveness + readiness. | Zero-downtime rollouts. |
| `security-context` | ✓ | 2 | `runAsNonRoot`, no privilege escalation, read-only root FS, `drop: [ALL]`. | Pod security admission (restricted). |
| `secret-refs` | ✓ | 2 | Both vars via `secretKeyRef`; chart renders no Secret with data. | Secrets stay out of git and values files. |
| `service-port` | – | 1 | Service exposes port 80. | |
| `fleet` | ✓ | 2 | Fleet bundle points at the chart, sets a namespace, targets both envs. | The GitOps deployment actually lands. |
| `fleet-prod-replicas` | – | 1 | 3 replicas in production. | |

## 9. Adding a task for a new stack

The starter tasks are examples. The results that matter for a team come from tasks that look
like *that team's* tickets. This section walks through adding a Java/Maven task; .NET, Terraform,
Angular etc. follow the same steps.

### 9.1 Layout

```
repos/<repo-id>.yaml         target repo: https URL + full 40-char SHA, deps, test command
repos/<repo-id>/*.patch      optional prepare patches (part of every task's starting state)
tasks/<task-id>/
  task.yaml                  title, repo, timeout, setup, allowed_paths, checks
  prompt.md                  the ticket (appended to tasks/_preamble.md)
  setup/*.patch|*.sh         turns the pinned repo into this task's starting state
  prefetch.sh                optional: grader-only reference data, fetched with network at setup
  hidden/solution.patch      the golden answer (required)
  hidden/*                   hidden tests / check scripts
suites/<name>.yaml           list of task ids
```

IDs: lowercase letters, digits, `.` and `-`, max 64 chars. Paths in YAML must stay inside their
directory.

### 9.2 Step 1: make sure the toolchain is in the images

The agent can only use what's in `docker/agent.Dockerfile`, and checks can only use what's in
`docker/grader.Dockerfile` (both run Ubuntu 24.04; the grader is based on the Playwright image).
The starter images contain Python, Node, git and the DevOps linters, **not a JDK or Maven**.

For Java/Maven, add to **both** Dockerfiles (the agent must be able to build and test; the grader
must run the hidden tests), pinned like everything else:

1. Add versions and checksums to `docker/versions.env`, e.g. `TEMURIN_JDK_VERSION`,
   `MAVEN_VERSION`, `MAVEN_SHA256`.
2. Install them in `docker/install-tools.sh` or the Dockerfiles, verifying the SHA-256.
3. Mention the tools in `tasks/_preamble.md` only if they apply to every task; otherwise put
   "`mvn` and JDK 21 are available" in the task's own `prompt.md`. (Changing the preamble changes
   every task's prompt, so don't compare batches across that change.)
4. `./bench build`.

**Grading runs with no network.** Maven must resolve dependencies offline during checks. Download
them during **setup** (which has network) into the workspace, e.g. with
`mvn -q dependency:go-offline -Dmaven.repo.local=.m2` in the repo's `deps`, and run checks with
`mvn -o -Dmaven.repo.local=.m2`. Add `.m2/` to the workspace excludes if it shouldn't count as a
change (see `VENV_EXCLUDES` in `src/benchy/setup_ws.py`, which currently covers Python only;
adding `.m2/` there is a small code change).

> Note: benchy's dependency cache and the "restore pristine dependencies before grading" step
> (`restore_venv`) are built around a `.venv`. For a JVM repo, the simplest option is to keep
> `deps` empty and let setup/check commands handle `.m2` themselves, accepting that an agent
> could in principle modify its local Maven repo. For a first task this is fine.

### 9.3 Step 2: pin the target repository

`repos/petclinic.yaml`:

```yaml
url: https://github.com/spring-projects/spring-petclinic.git
sha: <full 40-char commit SHA>        # pin, never a branch
license: Apache-2.0
prepare: []
deps: |
  ./mvnw -q -B dependency:go-offline -Dmaven.repo.local=.m2
deps_files: [pom.xml]
test_cmd: ./mvnw -q -B -o -Dmaven.repo.local=.m2 test
test_files: [src/test]                # restored from baseline before the regression check
```

`url` must be `https://` (or `file:///` for a local mirror). For internal repos, the grader clones
at setup time, so it needs network access to your Git server; there are no credentials in the
grader, so use a `file:///` mirror you place under `out/` or a repo readable without auth.
**Keep internal tasks and their results private.**

> `test_files` entries are passed to `git checkout <baseline> -- <path>`. A plain directory
> (`src/test`) is the safest pathspec; confirm the regression check behaves with the self-test.

### 9.4 Step 3: design the ticket

Good tasks are:

- **Realistic**: written like a real ticket from that team's backlog, with the business
  constraints ("least privilege", "no secrets in files") that a reviewer would enforce.
- **Checkable without a live system**: every requirement maps to something a script can verify
  offline: hidden tests, a linter, a schema, a structural assertion.
- **Small**: 5–25 minutes for a strong model. Long tasks multiply cost and variance.
- **Not pre-solved and not impossible**: the self-test enforces both.

Worked example: *"ORD-311: `GET /owners?lastName=` returns 500 for names with an apostrophe.
Fix it and add a test."* Plant the bug in `setup/inject-bug.patch`.

`tasks/java-owner-search/prompt.md`:

```markdown
## ORD-311: owner search fails for names with an apostrophe

Searching owners by last name with an apostrophe (e.g. `O'Brien`) returns HTTP 500.
Find and fix the root cause. Add a regression test, and make sure `./mvnw -o test` passes.
JDK 21 and Maven are available; dependencies are already in `./.m2` (use `-o -Dmaven.repo.local=.m2`).
```

### 9.5 Step 4: write `task.yaml` and the checks

```yaml
id: java-owner-search
title: "Fix: owner search 500s on apostrophes (ORD-311)"
category: java                 # free text; shown in run.json
repo: petclinic
timeout_s: 1200                # 30..7200
prompt: prompt.md
setup:
  - patch: setup/inject-bug.patch
allowed_paths: ["src/main/java/**", "src/test/java/**"]
checks:
  - id: hidden-search-tests
    title: Hidden owner-search tests pass
    run: >-
      cp "$HIDDEN/OwnerSearchHiddenTest.java" src/test/java/org/springframework/samples/petclinic/owner/ &&
      ./mvnw -q -B -o -Dmaven.repo.local=.m2 -Dtest=OwnerSearchHiddenTest test
    weight: 4
    timeout_s: 600
  - id: regression-test-added
    title: A new test mentions the apostrophe case
    run: git diff "$BASELINE" -- src/test | grep -E '^\+' | grep -q "O'Brien\|apostrophe"
    required: false
```

Check rules (`src/benchy/grade/engine.py`):

- `run` is a bash command (with `pipefail`) run from the finished workspace. **Exit 0 = pass.**
- The tree is hard-reset and cleaned before *each* check, so checks can't affect each other, and
  files the agent left untracked/ignored are gone (the `.venv` is kept and restored to pristine).
- Available variables: `$HIDDEN` (this task's `hidden/`), `$LIB` (`tasks/_lib`), `$BASELINE`
  (baseline commit), `$WS` (workspace), `$VENV`, `$SCHEMAS` (offline Kubernetes schemas),
  `$AUX` (prefetched reference data).
- `weight` (default 1, must be > 0) sets partial credit; `required` (default true) decides
  whether failing it prevents *resolved*; `timeout_s` defaults to 300.
- IDs `regression`, `scope`, `secrets` are reserved (built-ins). Set `regression: false` or
  `scope_required: false` in `task.yaml` to relax them.
- Only the last 4,000 characters of output are kept in `grade.json`, so make failure messages
  short and specific.

Reusable assertions for workflows, Dockerfiles, Compose, Kubernetes and Fleet are in
`tasks/_lib/checklib.py`: `python3 "$LIB/checklib.py" <check-name> <args>` (e.g. `gha-pinned`,
`docker-nonroot`, `k8s-security`). Add new generic assertions there (e.g. `maven-no-snapshot-deps`)
with a unit test in `tests/test_checklib.py` that shows it **rejects a plausible wrong answer**.

**Design checks that reject the lazy wrong answer.** For every requirement, ask "what would a
model do to make this pass without really meeting it?" (Editing the test, `permissions:
write-all`, a made-up SHA, a secret in an `ENV`.) Then make sure a check fails that.

### 9.6 Step 5: write the golden solution

Make the correct change by hand in a scratch workspace that matches the starting state, then
save it as `tasks/<id>/hidden/solution.patch` (`git diff` from the task's baseline). The mock
agent applies it with `git apply`, so it must apply cleanly to the post-setup tree. Keep it to
what a good engineer would actually submit; it's the "known good" that proves the checks are
satisfiable.

A practical loop: `./bench run --contenders <file with a noop contender> --tasks <id>
--repeats 1 --keep-workspaces`, then work in `out/work/<run-id>/repo` and `git diff >
tasks/<id>/hidden/solution.patch`.

### 9.7 Step 6: add it to a suite and prove it

`suites/java.yaml`:

```yaml
tasks:
  - java-owner-search
```

Then:

```bash
./bench test                  # unit tests, including any checklib additions
./bench selftest              # every task in suites/starter: noop must FAIL, mock must score 100%
```

⚠️ `./bench selftest` runs the **starter** suite only (`cmd_selftest` in `./bench`). To prove a
task in another suite, either add it to `suites/starter.yaml` temporarily, or run the same two
steps by hand:

```bash
./bench run --contenders tests/selftest/contenders.yaml --suite java --repeats 1
# then, inside the grader:
./bench shell grader
python3 -m benchy.cli verify-selftest <batch-id>
```

The self-test fails if the noop run is resolved (task pre-solved: tighten the setup or the
checks), or the mock run isn't resolved with score 1.0 (golden answer or checks wrong:
`grade.json` shows which check failed and its output). CI also runs `python3 -m benchy.cli
validate`, which loads every task, repo and suite.

Finally, run one real contender once (`--repeats 1`) and read the transcript and `grade.json`.
Real models find loopholes the golden answer never tried.

## 10. How many repeats, and what it will cost

### 10.1 Repeats

Models are non-deterministic; the same model on the same ticket can pass once and fail the next
time.

- **3 repeats** (default) is the minimum for a comparison. pass^k with k=3 already separates
  "reliable" from "lucky".
- **5 repeats** before a recommendation you'll publish.
- **1 repeat** only for smoke tests (new task, new model ID).

Treat differences smaller than the min–max ranges as noise. With 6 tasks × 3 repeats = 18 runs
per contender, one run is ~5.6 percentage points of resolve rate.

### 10.2 Estimating cost before a big batch

Cost per batch ≈ contenders × tasks × repeats × average cost per run. You don't know the last
term until you've measured it, so:

1. **Pilot:** `./bench run --repeats 1` with all contenders (one run per task per contender).
2. Read *Total cost* per contender in the report (or sum `cost.usd` in `results.csv`).
3. Multiply by the number of repeats you intend. Add ~20% headroom: failed runs often cost more
   than successful ones because they run until timeout.

Alternatively, from tokens: cost per run ≈ (input_fresh × input rate + cache_read × cached rate +
cache_write × write rate + output × output rate) / 1,000,000, using `pricing.yaml`.

Levers: fewer contenders (drop effort levels that the pilot shows add nothing), `--tasks` to a
subset, and `max_ai_credits` as a per-run safety cap (applies to Copilot only, minimum 30, and it
changes behaviour, so set it identically for every contender or not at all). Compare the batch
total against your GitHub billing page afterwards.

Wall-clock time: runs are sequential. Expect roughly (runs × average wall time) plus ~1 minute of
setup/grading overhead per run.

## 11. Fairness rules

Enforced by the runner:

- Same prompt text for everyone (`tasks/_preamble.md` + ticket; SHA-256 recorded in `run.json`).
- Same image digests and CLI versions (image IDs recorded in `run.json`; harness version in
  `metrics.json`).
- Same repository commit and starting state (single baseline commit, built fresh per run).
- Same CPU/memory limits (`BENCHY_AGENT_CPUS`, `BENCHY_AGENT_MEMORY`) and timeout.
- Same tool permissions (`--allow-all` / `bypassPermissions`).
- No custom instructions (`--no-custom-instructions`; Claude Code: `--setting-sources user`,
  `--strict-mcp-config`), no MCP servers (`--disable-builtin-mcps`), no auto-update.
- Interleaved order, rotated each repeat, to spread API load and time-of-day effects.
- No retries. Timeouts are failures, and their spend still counts.
- Requested and reported model recorded side by side.

Your responsibility:

- Don't give one contender `extra_args`, `max_ai_credits` or a different `--timeout-scale` than
  the others.
- Compare batches only if CLI versions, image versions, prompts and tasks match, and ideally the
  same week.
- Run on a machine that isn't otherwise busy; wall time is affected by host load.
- Don't combine Copilot and Claude Code results as if they were the same harness.

## 12. Security model

Full details in [SECURITY.md](../SECURITY.md). Summary:

| Step | Image | Network | Can see |
|---|---|---|---|
| setup | grader | on | benchy repo (read-only), `out/` |
| agent | agent | on (model API) | its own workspace, its own `raw/`, prompt, stored login (read-only) |
| finalize | grader | **off** | benchy repo (read-only), `out/`, the finished workspace |
| report | grader | **off** | `out/` |

- Every container: your UID (not root), `--cap-drop ALL`, `no-new-privileges`, read-only root
  filesystem, size-limited `/tmp`, PID limit; agent has fixed CPU/memory. No Docker socket.
- Credentials: device-flow OAuth only, in the `benchy-auth` volume, mounted read-only and copied
  into a per-run tmpfs. Never mounted for mock/noop/probe. All raw output is redacted.
- Grading integrity: hidden checks and golden answers are never mounted into the agent; the agent
  sees one commit; grading has no network; original test files are restored before the
  regression check; checks use a pristine venv and a cleaned tree; the secret scan ignores
  agent-added allow-lists.
- **Known limits:** the agent has outbound network access (it must reach the model API), so only
  point benchy at code you're allowed to send to your AI provider anyway;
  `BENCHY_AGENT_NETWORK` can point at a restricted Docker network. An adversarial agent could
  tamper with its own telemetry. `out/` is confidential for internal repos. Containers are not a
  VM boundary.

## 13. Limitations

- **Small sample.** Six tasks, one repository, one language (Python) for the code task. A smoke
  test for your context, not a ranking.
- **Static validation only** for containers, Helm and pipelines: no image is built, no chart
  deployed, no workflow executed.
- **Checks can be incomplete.** A resolved run met every requirement the checks encode; a
  reviewer may still reject it. Spot-check diffs.
- **`real-shas` is best-effort.** It only knows the actions listed in
  `tasks/_lib/prefetch-action-shas.sh`; unknown actions are not checked, and if setup had no
  network the check passes with "skipped".
- **Copilot metrics parsing is unverified against a real run** of the pinned CLI (6.4). Check
  `sources`/`warnings`.
- **Mock numbers are synthetic** (section 2.2).
- **Headless CLI ≠ IDE.** Results come from Copilot CLI, not VS Code agent mode.
- **amd64 only** (Apple Silicon runs under emulation). Podman (`BENCHY_ENGINE=podman`) is
  experimental.
- **Things change monthly**: models, CLI versions, prices, and Copilot's billing. Every report
  records versions and dates; old results go stale.
- **Runs are sequential**; a large batch takes hours.

## 14. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `./bench doctor`: engine not found / not running | Start Docker Desktop; enable WSL integration for your distro. |
| doctor warns repo is on the Windows filesystem | Re-clone under `~` in WSL. |
| `contenders file not found` | `cp contenders.example.yaml contenders.yaml`. Paths are relative to the repo root. |
| `invalid id`, `effort must be one of`, `two contenders share harness+model+effort` | Config validation (`src/benchy/config.py`); fix `contenders.yaml`. |
| Every run is a **harness error** | Check `out/runs/<id>/raw/stderr.txt` and `metrics.json → warnings`. Usually: not logged in (`./bench login copilot`), Copilot CLI not allowed by org policy, model not enabled for your org, or an unknown model ID. |
| `no stored Copilot login found` warning | `./bench login copilot`, then `./bench doctor`. |
| Login hangs or fails behind a proxy | Export `HTTPS_PROXY`/`NO_PROXY`; for TLS inspection set `BENCHY_CA_BUNDLE`. |
| `setup failed` / `dependency install failed` | The grader needs network to clone and `pip install`. Check proxy settings. Delete `out/cache/` to force a clean retry. |
| `run ... already exists; runs are never reused` | Each run ID is used once; start a new batch. |
| Many **timeouts** | Machine too slow or the model is slow: try `--timeout-scale 1.5` for *all* contenders, or raise `BENCHY_AGENT_CPUS`/`MEMORY` if Docker has room. |
| `$` columns show "—" | No cost reported and model not in `pricing.yaml`. Add rates. |
| Warning `token totals disagree across sources` | Copilot output formats changed or the parser is off; compare `raw/usage.json` and `raw/otel.jsonl`. Report it. |
| `model_requested` ≠ `models_reported` | Wrong ID or Copilot routed to another model; fix before trusting results. |
| `screenshots failed` warning | Rendering problem only; the run is still graded. Use `diff.html`. |
| Self-test: `golden solution did not pass (failed: [...])` | The task or its golden patch is wrong; read that check's `output` in `grade.json`. |
| Self-test: `starting state already passes` | The task is pre-solved; tighten setup or checks. |
| Need to look around inside the images | `./bench shell agent` or `./bench shell grader`. |

## 15. Command and environment reference

### `./bench` commands

| Command | Does |
|---|---|
| `./bench build` | Build `benchy-agent:local` and `benchy-grader:local` from `docker/versions.env`. |
| `./bench login copilot\|claude` | Device-flow login stored in the `benchy-auth` volume. |
| `./bench logout [copilot\|claude]` | Delete one or all stored logins. |
| `./bench run [opts]` | Plan, run and report a batch. Options: `--contenders FILE`, `--suite NAME`, `--tasks a,b`, `--repeats N`, `--timeout-scale X`, `--keep-workspaces`, `--no-screenshots`. |
| `./bench report [--batch ID\|latest\|all] [--no-screenshot]` | Rebuild a report. |
| `./bench selftest` | Probe + mock + noop over the starter suite; zero AI cost. |
| `./bench test [pytest args]` | Unit tests. |
| `./bench doctor` | Environment check. |
| `./bench shell agent\|grader` | Debug shell. |

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `BENCHY_OUT` | `./out` | Output directory. |
| `BENCHY_ENGINE` | `docker` | `podman` is experimental. |
| `BENCHY_AGENT_IMAGE` / `BENCHY_GRADER_IMAGE` | `benchy-agent:local` / `benchy-grader:local` | Image names. |
| `BENCHY_AUTH_VOLUME` | `benchy-auth` | Login volume name. |
| `BENCHY_AGENT_CPUS` / `BENCHY_AGENT_MEMORY` | `4` / `6g` | Agent limits. |
| `BENCHY_AGENT_NETWORK` | `bridge` | Docker network for the agent (e.g. an egress-restricted one). |
| `BENCHY_CA_BUNDLE` | – | Extra CA certificate for corporate TLS inspection. |
| `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` | – | Passed through to setup, login and agent steps. |

### Adding another harness

Implement `src/benchy/harness/<name>.py` (`command`, `prepare`, `harvest`, `parse`; see
`base.py`), register it in `src/benchy/harness/__init__.py`, and install its CLI in
`docker/agent.Dockerfile`. Grading, screenshots and reporting don't change.
