You're right: I never clearly separated the two kinds of testing going on, so here it is.

## What is being tested

There are two different things, and I blurred them.

**1. The benchmark tasks. This is where the AI models get tested.**
The six tasks are not testing your tech stack. Each one is a work ticket handed to an AI model. Your stack only decided what kind of tickets they are: GitHub Actions, Artifactory, Rancher, Docker/Podman. The question every task answers is: *given this ticket in a real repo, can this model at this thinking level finish it correctly, and what did that cost in time and money?*

| Task                | The ticket the AI gets                                                                                 | How we know it did the job                                                                                                                                                                             |
| ------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `bugfix-unit`       | "Revoked API tokens still work." Two bugs are planted in the app's login-token code.                   | Secret tests we wrote call the app and its API and check tokens really expire and revoke. The AI never sees these tests.                                                                               |
| `gha-ci-add`        | "This repo has no CI. Add a GitHub Actions workflow to our standards."                                 | The workflow linter passes, it runs on PRs and pushes, it runs the tests, and its token is read-only. Actions must be pinned to commit IDs that **really exist**, which catches AIs that make them up. |
| `gha-ci-fix`        | "The release pipeline broke." It has four planted bugs.                                                | All four bugs are fixed, the linter is clean, and the publish job gets write access to the package registry and nothing more.                                                                          |
| `container-harden`  | "Make our Dockerfile production-ready and add a Compose file that works in Docker Desktop and Podman." | Dockerfile linter, no running as root, pinned base image, healthcheck, no passwords in files, and a Compose file that matches the official spec.                                                       |
| `artifactory-route` | "All downloads must go through Artifactory."                                                           | Images and pip packages come from the Artifactory address, and credentials only arrive through secrets. Nothing sensitive ends up baked into the image or written in a file.                           |
| `rancher-deploy`    | "Write a Helm chart and a Fleet bundle for staging and production."                                    | Helm lint, a check against the official Kubernetes schemas, resource limits, health probes, locked-down security settings, secrets pulled from Kubernetes, and correct Fleet targets.                  |

Every task also gets three extra checks:
- the app's original tests still pass;
- the AI only touched files related to the ticket;
- no credentials were added.

These tasks are just the starter set. You can add tasks for any stack your teams use: Java, .NET, Terraform, Angular, whatever you have.

**2. Tests of the benchmark itself.** No AI runs here. They exist to prove the scoring can be trusted.

| Test              | What it proves                                                                                                                                                                                                               |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit tests (77)   | The scoring code reads usage numbers correctly, hides secrets in logs, and rejects bad config. It also checks that each grading check **rejects plausible wrong answers**, e.g. a workflow with write permissions must fail. |
| **mock** "agent"  | It applies our own known-correct answer instead of calling an AI, and must score 100%. This proves every task can be solved and the pipeline (branches, screenshots, report) works. It costs nothing.                        |
| **noop** "agent"  | It changes nothing and must **fail**. This proves no task passes before any work is done. Without it, a broken task would give every model a free pass.                                                                      |
| **probe** "agent" | It inspects the sandbox from inside and fails the self-test if an AI could run as admin or see the hidden answers. It also checks the AI can't see git history that would give away the planted bugs, or any login tokens.   |

In the example report, "Mock A/B" and "Noop" are these stand-ins, not real models. That's why the times show 0s.

## What each section of the report tells you

| Section                           | Question it answers                                                                                                              |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Resolve rate** chart            | How often did this model fully finish the ticket? This is the headline number.                                                   |
| **Cost per resolved task**        | What does one *successful* result cost, counting the money spent on failed attempts? A cheap model that fails often isn't cheap. |
| **Median wall time**              | How long a developer would wait for it.                                                                                          |
| **Median tokens**                 | How much text the model read and wrote. It explains cost and shows how verbose a model is.                                       |
| **Scorecard: pass^k**             | Did it solve the task *every* time it was run? This measures reliability.                                                        |
| **Scorecard: mean score**         | Partial credit, i.e. how close the failures came.                                                                                |
| **Scorecard: tool calls / turns** | How many steps it took. A high count for the same result usually means it was fumbling.                                          |
| **Scorecard: churn**              | How many lines it changed when it succeeded. Smaller is easier to review.                                                        |
| **Per task** grid                 | Which models are good at which *kind* of work. This is the part that helps you recommend a model per stack.                      |
| **Why runs failed**               | Timeout, broke existing code, edited the wrong files, leaked a secret, or simply wrong.                                          |
| **All runs**                      | Every run, with links to its screenshots, diff, and git branch.                                                                  |

## Your four vendors

All four vendors (Microsoft MAI, OpenAI, Gemini, Claude) can run through the same Copilot CLI harness using `--model` and `--reasoning-effort`, provided GitHub offers each model to your org. That keeps the comparison fair: one tool, one sandbox, one set of tasks, and only the model changes. I haven't checked which MAI or Gemini model IDs your Copilot plan exposes. The new session should check this with `copilot` → `/model`.

## Prompt for a new session

Paste this into a fresh Claude Code session started in `~/projects/benchy`:

```
You are documenting an existing project in this repo: "benchy", a containerized benchmark that
compares AI coding models (via GitHub Copilot CLI, with Claude Code as a secondary harness) on
realistic work tickets. Read the code before writing anything: README.md, SECURITY.md,
bench, src/benchy/**, tasks/** (including tasks/*/prompt.md, task.yaml, hidden/, tasks/_lib/checklib.py),
tests/**, suites/, repos/, pricing.yaml, contenders.example.yaml. Do not change code.

Context about me and my goal:
- I run AI enablement at a company. We are allowed to use models from four vendors: Microsoft
  (MAI), OpenAI, Google (Gemini) and Anthropic (Claude), each at several thinking/reasoning levels.
- I want to compare them at work so I can (a) recommend defaults and (b) let each team see which
  model + thinking level works best for THEIR tech stack. We have many stacks. The six starter tasks
  (GitHub Actions, Artifactory, Rancher/Helm, Docker/Podman, a Python bug fix) are examples only.
- Users run Windows + WSL + Docker Desktop. No GitHub PATs are allowed (device-flow login only).

Produce two documents as files under docs/:

1. docs/user-manual.md — a complete manual for engineers who will run and extend benchy:
   - What benchy measures and what it does NOT measure; the difference between the benchmark
     tasks (which test the AI models) and benchy's own tests (unit tests, the mock/noop/probe
     stand-in agents, selftest), which test the benchmark itself. Explain each stand-in agent.
   - Setup on Windows/WSL/Docker Desktop, login, choosing contenders, running, re-running reports.
   - How to find the exact model IDs and reasoning levels available in Copilot CLI for all four
     vendors, and a sample contenders.yaml covering all four at two or more thinking levels.
     Verify flags against `docker run --rm benchy-agent:local copilot --help`; mark anything you
     could not verify.
   - Every output: git branches, screenshots, diff, metrics.json fields, grade.json, raw/ files.
   - Every section and column of the report, what question it answers, and how to read it
     (including pass^k, cost per resolved task, "—" meaning unknown, min–max ranges).
   - Each starter task: the ticket, what the hidden checks verify and why each matters in a
     business setting.
   - A step-by-step guide to adding a task for a NEW stack (use a worked example such as a
     Java/Maven or .NET service), including golden solution, checks, and proving it with selftest.
   - How many repeats to run, cost estimation before running, fairness rules, limitations,
     security model, troubleshooting.

2. docs/overview-for-leaders.md — a short, plain-language guide for non-technical managers
   (don't label it as "for managers" or "ELI5"; title it something like "Choosing AI coding
   models: how we test and what the results mean"). Use analogies, no jargon (or define it in
   one line). Cover: why we test instead of trusting vendor claims, what one "run" is, why the
   same test is repeated, the three questions the report answers (does it work, what does it
   cost, how reliable is it), how to read the headline chart and scorecard with a worked example
   using made-up numbers clearly labeled as illustrative, what the results can and cannot tell
   us, and how recommendations per team/stack will be made. Max ~2 pages.

Keep both accurate to the code; quote real file paths and commands. When done, list anything in
the code that contradicts the README so I can fix it.
```

Want me to also save that prompt as `docs/PROMPT-docs.md` in the repo, and make the initial commit?