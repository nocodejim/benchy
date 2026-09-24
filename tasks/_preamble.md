You are working autonomously in a git repository at /work/repo (the current directory).
Nobody will answer questions: make reasonable decisions, finish the whole task, then stop.

Environment:
- Linux container. There is no Docker/Podman daemon and no Kubernetes cluster. Use static
  validation instead; these tools are on PATH: git, python3, actionlint, hadolint, helm,
  kubeconform, shellcheck, yamllint, jf (JFrog CLI), jq, rg.
- The project's Python dependencies are installed in ./.venv (use .venv/bin/python).
- Leave your changes in the working tree. Do not push, and do not rewrite existing git history.
- Keep changes focused on the task. Never put real credentials in files.

Task:
